import { flushSync } from "svelte";
import { beforeAll, expect, it, vi } from "vitest";

let systemDark = false;
let listener: ((e: { matches: boolean }) => void) | undefined;
let theme: typeof import("./theme.svelte");

beforeAll(async () => {
  window.matchMedia = vi.fn(() => ({
    get matches() {
      return systemDark;
    },
    addEventListener: (_: string, l: typeof listener) => (listener = l),
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  localStorage.setItem("coach.theme", "dark");
  // import dynamique après le stub matchMedia et le choix mémorisé
  theme = await import("./theme.svelte");
});

const attr = () => document.documentElement.dataset.theme;

it("reprend le choix mémorisé au chargement", () => {
  expect(theme.themeChoice()).toBe("dark");
  expect(theme.effectiveScheme()).toBe("dark");
});

it("un choix forcé pose data-theme et est mémorisé", () => {
  theme.setThemeChoice("light");
  expect(attr()).toBe("light");
  expect(localStorage.getItem("coach.theme")).toBe("light");
  // le système passe en sombre : sans effet sur un choix forcé
  systemDark = true;
  listener!({ matches: true });
  expect(attr()).toBe("light");
});

it("auto suit le système, y compris quand il change", () => {
  systemDark = false;
  listener!({ matches: false });
  theme.setThemeChoice("auto");
  expect(localStorage.getItem("coach.theme")).toBe("auto");
  expect(attr()).toBe("light");

  const seen: string[] = [];
  const stop = $effect.root(() => {
    $effect(() => {
      seen.push(theme.effectiveScheme());
    });
  });
  flushSync();
  systemDark = true;
  listener!({ matches: true });
  flushSync();
  expect(attr()).toBe("dark");
  expect(seen).toEqual(["light", "dark"]);
  stop();
});

it("stockage indisponible : le choix s'applique quand même", () => {
  const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("bloqué");
  });
  theme.setThemeChoice("dark");
  expect(attr()).toBe("dark");
  expect(theme.themeChoice()).toBe("dark");
  spy.mockRestore();
});
