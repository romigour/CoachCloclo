import { it, expect, vi } from "vitest";

it("themeColors() est réactif au changement de prefers-color-scheme", async () => {
  let listener: ((e: { matches: boolean }) => void) | undefined;
  window.matchMedia = vi.fn(() => ({
    matches: false,
    addEventListener: (_: string, l: typeof listener) => (listener = l),
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  vi.resetModules();
  const { themeColors } = await import("./theme.svelte");

  const seen: string[] = [];
  const stop = $effect.root(() => {
    $effect(() => {
      seen.push(themeColors().accent);
    });
  });
  document.documentElement.style.setProperty("--accent", "#111111");
  await Promise.resolve();
  expect(seen).toEqual(["#111111"]); // premier calcul
  document.documentElement.style.setProperty("--accent", "#222222");
  listener!({ matches: true });
  await Promise.resolve();
  expect(seen.at(-1)).toBe("#222222");
  expect(seen.length).toBe(2);
  stop();
});
