import { flushSync } from "svelte";
import { it, expect, vi } from "vitest";

it("themeColors() est réactif au changement de prefers-color-scheme", async () => {
  let listener: ((e: { matches: boolean }) => void) | undefined;
  window.matchMedia = vi.fn(() => ({
    matches: false,
    addEventListener: (_: string, l: typeof listener) => (listener = l),
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  // import dynamique après le stub matchMedia ; pas de resetModules (dupliquerait svelte et son graphe de signaux)
  const { themeColors } = await import("./theme.svelte");

  const seen: string[] = [];
  const stop = $effect.root(() => {
    $effect(() => {
      seen.push(themeColors().accent);
    });
  });
  document.documentElement.style.setProperty("--accent", "#111111");
  flushSync();
  expect(seen).toEqual(["#111111"]); // premier calcul
  document.documentElement.style.setProperty("--accent", "#222222");
  listener!({ matches: true });
  flushSync();
  expect(seen.at(-1)).toBe("#222222");
  expect(seen.length).toBe(2);
  stop();
});
