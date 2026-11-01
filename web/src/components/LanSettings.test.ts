import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import LanSettings from "./LanSettings.svelte";

type View = { enabled: boolean; has_pin: boolean; addresses: string[]; local: boolean };
const off: View = { enabled: false, has_pin: false, addresses: [], local: true };

let lan: View;
let posts: unknown[];
let postResponse: { status: number; body: unknown } | null;
let writeText: ReturnType<typeof vi.fn>;

beforeEach(() => {
  lan = { ...off };
  posts = [];
  postResponse = null;
  writeText = vi.fn(async () => {});
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/lan" && init?.method === "POST") {
        const body = JSON.parse(init.body as string);
        posts.push(body);
        if (postResponse) return new Response(JSON.stringify(postResponse.body), { status: postResponse.status });
        lan = {
          ...lan,
          enabled: body.enabled,
          has_pin: lan.has_pin || !!body.pin,
          addresses: body.enabled ? ["http://192.168.1.20:8765"] : [],
        };
        return new Response(JSON.stringify(lan), { status: 200 });
      }
      if (url === "/api/lan") return new Response(JSON.stringify(lan), { status: 200 });
      return new Response("{}", { status: 404 });
    }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function fillPins(a: string, b: string) {
  await fireEvent.input(screen.getByLabelText("PIN (4 à 12 chiffres)"), { target: { value: a } });
  await fireEvent.input(screen.getByLabelText("Confirmer le PIN"), { target: { value: b } });
}

test("demande un PIN à la première activation et l'envoie", async () => {
  render(LanSettings);
  await fireEvent.click(await screen.findByRole("switch"));
  const pin = screen.getByLabelText("PIN (4 à 12 chiffres)") as HTMLInputElement;
  expect(pin.type).toBe("password");
  expect(pin.getAttribute("inputmode")).toBe("numeric");
  expect(pin.getAttribute("autocomplete")).toBe("new-password");
  await fillPins("1234", "1234");
  vi.useFakeTimers();
  await fireEvent.click(screen.getByRole("button", { name: "Activer" }));
  await vi.advanceTimersByTimeAsync(1100);
  expect(posts).toEqual([{ enabled: true, pin: "1234" }]);
  expect(screen.getByText("http://192.168.1.20:8765")).toBeTruthy();
});

test("refuse deux PIN différents ou trop courts sans appeler l'API", async () => {
  render(LanSettings);
  await fireEvent.click(await screen.findByRole("switch"));
  await fillPins("1234", "1235");
  await fireEvent.click(screen.getByRole("button", { name: "Activer" }));
  expect(screen.getByText(/ne sont pas identiques/)).toBeTruthy();
  await fillPins("123", "123");
  await fireEvent.click(screen.getByRole("button", { name: "Activer" }));
  expect(screen.getByText(/4 à 12 chiffres/, { selector: "p" })).toBeTruthy();
  await fillPins("12ab", "12ab");
  await fireEvent.click(screen.getByRole("button", { name: "Activer" }));
  expect(screen.getByText(/4 à 12 chiffres/, { selector: "p" })).toBeTruthy();
  expect(posts).toEqual([]);
});

test("affiche les adresses une fois activé, avec Copier", async () => {
  lan = { enabled: true, has_pin: true, addresses: ["http://192.168.1.20:8765"], local: true };
  render(LanSettings);
  expect(await screen.findByText("http://192.168.1.20:8765")).toBeTruthy();
  await fireEvent.click(screen.getByRole("button", { name: "Copier" }));
  expect(writeText).toHaveBeenCalledWith("http://192.168.1.20:8765");
  expect(screen.getByText(/Vérifie le pare-feu Windows/)).toBeTruthy();
});

test("désactive sans demander de PIN", async () => {
  lan = { enabled: true, has_pin: true, addresses: ["http://192.168.1.20:8765"], local: true };
  render(LanSettings);
  const sw = await screen.findByRole("switch");
  vi.useFakeTimers();
  await fireEvent.click(sw);
  await vi.advanceTimersByTimeAsync(1100);
  expect(posts).toEqual([{ enabled: false }]);
  expect(screen.queryByText("http://192.168.1.20:8765")).toBeNull();
});

test("réactive avec un PIN déjà enregistré sans le redemander", async () => {
  lan = { ...off, has_pin: true };
  render(LanSettings);
  await fireEvent.click(await screen.findByRole("switch"));
  expect(screen.queryByLabelText("PIN (4 à 12 chiffres)")).toBeNull();
  vi.useFakeTimers();
  await fireEvent.click(screen.getByRole("button", { name: "Activer" }));
  await vi.advanceTimersByTimeAsync(1100);
  expect(posts).toEqual([{ enabled: true }]);
});

test("Changer le PIN envoie le nouveau PIN en restant activé", async () => {
  lan = { enabled: true, has_pin: true, addresses: ["http://192.168.1.20:8765"], local: true };
  render(LanSettings);
  await fireEvent.click(await screen.findByRole("button", { name: "Changer le PIN" }));
  await fillPins("987654", "987654");
  vi.useFakeTimers();
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer le PIN" }));
  await vi.advanceTimersByTimeAsync(1100);
  expect(posts).toEqual([{ enabled: true, pin: "987654" }]);
});

test("est en lecture seule depuis un téléphone", async () => {
  lan = { enabled: true, has_pin: true, addresses: ["http://192.168.1.20:8765"], local: false };
  render(LanSettings);
  expect(await screen.findByText("Modifiable seulement depuis l'ordinateur")).toBeTruthy();
  expect((screen.getByRole("switch") as HTMLInputElement).disabled).toBe(true);
  expect(screen.queryByRole("button", { name: "Changer le PIN" })).toBeNull();
});

test("affiche l'avertissement pare-feu avant l'activation", async () => {
  render(LanSettings);
  expect(screen.queryByText(/Windows va te demander l'autorisation/)).toBeNull();
  await fireEvent.click(await screen.findByRole("switch"));
  expect(screen.getByText(/Windows va te demander l'autorisation/)).toBeTruthy();
  expect(posts).toEqual([]);
});

test("affiche l'erreur du serveur sous les champs", async () => {
  render(LanSettings);
  await fireEvent.click(await screen.findByRole("switch"));
  await fillPins("1234", "1234");
  postResponse = { status: 422, body: { code: "invalid_pin", detail: "PIN invalide" } };
  await fireEvent.click(screen.getByRole("button", { name: "Activer" }));
  expect(await screen.findByText("PIN invalide")).toBeTruthy();
});

test("réessaie la relecture si le serveur redémarre encore", async () => {
  render(LanSettings);
  await fireEvent.click(await screen.findByRole("switch"));
  await fillPins("1234", "1234");
  const f = fetch as unknown as ReturnType<typeof vi.fn>;
  const impl = f.getMockImplementation()!;
  let reads = 0;
  f.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/lan" && init?.method !== "POST" && reads++ < 2) throw new TypeError("fetch failed");
    return impl(url, init);
  });
  vi.useFakeTimers();
  await fireEvent.click(screen.getByRole("button", { name: "Activer" }));
  await vi.advanceTimersByTimeAsync(4000);
  expect(screen.getByText("http://192.168.1.20:8765")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("sans appli de bureau (404) : bloc masqué", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  const { container } = render(LanSettings);
  await new Promise((r) => setTimeout(r, 20));
  expect(container.querySelector("section")).toBeNull();
});
