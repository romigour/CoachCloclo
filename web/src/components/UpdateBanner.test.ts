import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import UpdateBanner from "./UpdateBanner.svelte";
import UpdateSettings from "./UpdateSettings.svelte";
import { waitForVersion } from "../lib/update";

type View = Record<string, unknown>;
const idle: View = { current: "0.1.0", latest: "0.2.0", available: true, state: "idle", progress: 0, error: null };

let update: View;
let version: string | "down";
let checkResult: View;
let reload: ReturnType<typeof vi.fn>;

beforeEach(() => {
  update = { ...idle };
  checkResult = { ...idle, available: false, latest: null };
  version = "0.1.0";
  localStorage.clear();
  reload = vi.fn();
  vi.stubGlobal("location", { ...window.location, reload, hash: "" });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === "/api/update") return new Response(JSON.stringify(update), { status: 200 });
      if (url === "/api/update/check") return new Response(JSON.stringify(checkResult), { status: 200 });
      if (url === "/api/update/install") return new Response(JSON.stringify({ status: "started" }), { status: 202 });
      if (url === "/api/version") {
        if (version === "down") throw new TypeError("fetch failed");
        return new Response(JSON.stringify({ version }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("affiche le bandeau quand une version est disponible", async () => {
  render(UpdateBanner);
  expect(await screen.findByText(/Version 0\.2\.0 disponible/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Mettre à jour" })).toBeTruthy();
});

test("Plus tard masque cette version, la suivante réapparaît", async () => {
  const first = render(UpdateBanner);
  await screen.findByText(/Version 0\.2\.0 disponible/);
  await fireEvent.click(screen.getByRole("button", { name: "Plus tard" }));
  expect(screen.queryByText(/disponible/)).toBeNull();
  expect(localStorage.getItem("coach.updateDismissed")).toBe("0.2.0");
  first.unmount();

  render(UpdateBanner);
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.queryByText(/disponible/)).toBeNull();
  vi.unstubAllGlobals();
  update = { ...idle, latest: "0.3.0" };
  vi.stubGlobal("location", { ...window.location, reload, hash: "" });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(update), { status: 200 })));
  render(UpdateBanner);
  expect(await screen.findByText(/Version 0\.3\.0 disponible/)).toBeTruthy();
});

test("montre la progression puis recharge quand la nouvelle version répond", async () => {
  render(UpdateBanner);
  await screen.findByText(/Version 0\.2\.0 disponible/);
  vi.useFakeTimers();
  update = { ...idle, state: "downloading", progress: 42 };
  await fireEvent.click(screen.getByRole("button", { name: "Mettre à jour" }));
  await vi.advanceTimersByTimeAsync(1100);
  expect(screen.getByText(/Téléchargement… 42 %/)).toBeTruthy();
  update = { ...idle, state: "installing", progress: 100 };
  await vi.advanceTimersByTimeAsync(1000);
  expect(screen.getByText("Mise à jour en cours, CoachCloclo va redémarrer…")).toBeTruthy();
  version = "down";
  await vi.advanceTimersByTimeAsync(4000);
  expect(reload).not.toHaveBeenCalled();
  version = "0.2.0";
  await vi.advanceTimersByTimeAsync(2100);
  expect(reload).toHaveBeenCalled();
});

test("signale une mise à jour bloquée après le délai", async () => {
  render(UpdateBanner);
  await screen.findByText(/Version 0\.2\.0 disponible/);
  vi.useFakeTimers();
  update = { ...idle, state: "installing", progress: 100 };
  await fireEvent.click(screen.getByRole("button", { name: "Mettre à jour" }));
  await vi.advanceTimersByTimeAsync(1100);
  await vi.advanceTimersByTimeAsync(125_000);
  expect(screen.getByText(/La mise à jour semble bloquée : relance CoachCloclo depuis l'icône du bureau/)).toBeTruthy();
  expect(reload).not.toHaveBeenCalled();
});

test("affiche l'erreur et Réessayer en cas d'échec", async () => {
  render(UpdateBanner);
  await screen.findByText(/Version 0\.2\.0 disponible/);
  vi.useFakeTimers();
  update = { ...idle, state: "failed", error: "Le fichier téléchargé est corrompu, réessaie" };
  await fireEvent.click(screen.getByRole("button", { name: "Mettre à jour" }));
  await vi.advanceTimersByTimeAsync(1100);
  expect(screen.getByText(/Le fichier téléchargé est corrompu, réessaie/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Réessayer" })).toBeTruthy();
});

test("waitForVersion ignore les erreurs réseau pendant le redémarrage", async () => {
  let t = 0;
  const now = () => t;
  let calls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      calls++;
      t += 10;
      if (calls < 3) throw new TypeError("fetch failed");
      return new Response(JSON.stringify({ version: calls < 4 ? "0.1.0" : "0.2.0" }), { status: 200 });
    }),
  );
  expect(await waitForVersion("0.1.0", { intervalMs: 1, timeoutMs: 1000, now })).toBe(true);
  expect(calls).toBe(4);
  t = 0;
  vi.stubGlobal("fetch", vi.fn(async () => { t += 600; throw new TypeError("x"); }));
  expect(await waitForVersion("0.1.0", { intervalMs: 1, timeoutMs: 1000, now })).toBe(false);
});

test("le bouton des Réglages affiche À jour", async () => {
  render(UpdateSettings);
  expect(await screen.findByText("Version installée : 0.1.0")).toBeTruthy();
  await fireEvent.click(screen.getByRole("button", { name: "Vérifier les mises à jour" }));
  expect(await screen.findByText("CoachCloclo est à jour")).toBeTruthy();
});
