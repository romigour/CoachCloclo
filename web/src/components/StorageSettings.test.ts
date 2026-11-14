import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import StorageSettings from "./StorageSettings.svelte";

type View = { mode: "local" | "turso"; turso_url: string | null; has_turso_token: boolean };
const local: View = { mode: "local", turso_url: null, has_turso_token: false };
const cloud: View = { mode: "turso", turso_url: "libsql://coach-x.turso.io", has_turso_token: true };

let storage: View;
let calls: { method: string; url: string; body: unknown }[];
let responses: { status: number; body: unknown }[]; // réponses forcées, consommées dans l'ordre
let getStatus: number;

beforeEach(() => {
  storage = { ...local };
  calls = [];
  responses = [];
  getStatus = 200;
  vi.stubGlobal("confirm", vi.fn(() => true));
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/storage" && method === "GET") {
        if (getStatus !== 200) return new Response("{}", { status: getStatus });
        return new Response(JSON.stringify(storage), { status: 200 });
      }
      calls.push({ method, url, body: init?.body ? JSON.parse(init.body as string) : undefined });
      const forced = responses.shift();
      if (forced) return new Response(JSON.stringify(forced.body), { status: forced.status });
      if (url === "/api/storage/cloud" && method === "POST") storage = { ...cloud };
      else storage = { ...local };
      return new Response(JSON.stringify(storage), { status: 200 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

async function fill(url = "libsql://coach-x.turso.io", token = "secret") {
  await fireEvent.input(await screen.findByLabelText("URL de la base"), { target: { value: url } });
  await fireEvent.input(screen.getByLabelText("Jeton d'accès"), { target: { value: token } });
}

test("mode local : explication, guide, champs et bouton", async () => {
  render(StorageSettings);
  expect(await screen.findByRole("button", { name: "Stocker mes données dans le cloud" })).toBeTruthy();
  expect((screen.getByLabelText("Jeton d'accès") as HTMLInputElement).type).toBe("password");
  const guide = screen.getByRole("link", { name: /guide/i }) as HTMLAnchorElement;
  expect(guide.href).toBe("https://github.com/romigour/CoachCloclo#stockage-dans-le-cloud-turso");
});

test("mode cloud : URL, pas de jeton, deux actions", async () => {
  storage = { ...cloud };
  render(StorageSettings);
  expect(await screen.findByText("libsql://coach-x.turso.io")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Revenir au stockage local" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Effacer mes données du cloud" })).toBeTruthy();
  expect(screen.queryByLabelText("Jeton d'accès")).toBeNull();
});

test("activation : envoie url, jeton, replace_local=false puis affiche le mode cloud", async () => {
  render(StorageSettings);
  await fill();
  await fireEvent.click(screen.getByRole("button", { name: "Stocker mes données dans le cloud" }));
  expect(await screen.findByRole("button", { name: "Revenir au stockage local" })).toBeTruthy();
  expect(calls).toEqual([
    { method: "POST", url: "/api/storage/cloud", body: { url: "libsql://coach-x.turso.io", token: "secret", replace_local: false } },
  ]);
});

test("needs_confirmation : confirme puis renvoie avec replace_local=true", async () => {
  responses = [{ status: 409, body: { code: "needs_confirmation", detail: "La base cloud contient déjà des données." } }];
  render(StorageSettings);
  await fill();
  await fireEvent.click(screen.getByRole("button", { name: "Stocker mes données dans le cloud" }));
  expect(await screen.findByRole("button", { name: "Revenir au stockage local" })).toBeTruthy();
  expect(confirm).toHaveBeenCalledWith("La base cloud contient déjà des données.");
  expect(calls.map((c) => (c.body as { replace_local: boolean }).replace_local)).toEqual([false, true]);
});

test("needs_confirmation refusée : pas de second appel", async () => {
  vi.stubGlobal("confirm", vi.fn(() => false));
  responses = [{ status: 409, body: { code: "needs_confirmation", detail: "Remplacer ?" } }];
  render(StorageSettings);
  await fill();
  await fireEvent.click(screen.getByRole("button", { name: "Stocker mes données dans le cloud" }));
  await screen.findByRole("button", { name: "Stocker mes données dans le cloud" });
  expect(calls).toHaveLength(1);
});

test("pendant le transfert : bouton désactivé « Transfert en cours… »", async () => {
  let release: (r: Response) => void = () => {};
  const f = fetch as unknown as ReturnType<typeof vi.fn>;
  const impl = f.getMockImplementation()!;
  f.mockImplementation((url: string, init?: RequestInit) =>
    url === "/api/storage/cloud" ? new Promise<Response>((r) => (release = r)) : impl(url, init),
  );
  render(StorageSettings);
  await fill();
  await fireEvent.click(screen.getByRole("button", { name: "Stocker mes données dans le cloud" }));
  const busy = (await screen.findByRole("button", { name: "Transfert en cours…" })) as HTMLButtonElement;
  expect(busy.disabled).toBe(true);
  release(new Response(JSON.stringify(cloud), { status: 200 }));
});

test("affiche le message d'erreur cloud_unreachable", async () => {
  responses = [{ status: 422, body: { code: "cloud_unreachable", detail: "Base cloud injoignable" } }];
  render(StorageSettings);
  await fill();
  await fireEvent.click(screen.getByRole("button", { name: "Stocker mes données dans le cloud" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Base cloud injoignable");
  expect(screen.getByRole("button", { name: "Stocker mes données dans le cloud" })).toBeTruthy();
});

test("revenir au local : DELETE puis mode local", async () => {
  storage = { ...cloud };
  render(StorageSettings);
  await fireEvent.click(await screen.findByRole("button", { name: "Revenir au stockage local" }));
  expect(await screen.findByRole("button", { name: "Stocker mes données dans le cloud" })).toBeTruthy();
  expect(calls).toEqual([{ method: "DELETE", url: "/api/storage/cloud", body: undefined }]);
});

test("effacer : confirmation avant l'appel, rien si refusée", async () => {
  storage = { ...cloud };
  vi.stubGlobal("confirm", vi.fn(() => false));
  render(StorageSettings);
  await fireEvent.click(await screen.findByRole("button", { name: "Effacer mes données du cloud" }));
  expect(confirm).toHaveBeenCalledWith(
    "Les données seront supprimées du cloud pour tous tes PC. Cette action est irréversible.",
  );
  expect(calls).toEqual([]);
});

test("effacer confirmé : POST wipe puis mode local", async () => {
  storage = { ...cloud };
  render(StorageSettings);
  await fireEvent.click(await screen.findByRole("button", { name: "Effacer mes données du cloud" }));
  expect(await screen.findByRole("button", { name: "Stocker mes données dans le cloud" })).toBeTruthy();
  expect(calls).toEqual([{ method: "POST", url: "/api/storage/cloud/wipe", body: {} }]);
});

test("depuis un téléphone (403) : indication, pas de formulaire", async () => {
  getStatus = 403;
  render(StorageSettings);
  expect(await screen.findByText("Disponible uniquement sur le PC")).toBeTruthy();
  expect(screen.queryByLabelText("URL de la base")).toBeNull();
});

test("sans route (404) : bloc masqué", async () => {
  getStatus = 404;
  const { container } = render(StorageSettings);
  await new Promise((r) => setTimeout(r, 20));
  expect(container.querySelector("section")).toBeNull();
});
