import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeAll, expect, test, vi } from "vitest";

let ThemeSettings: typeof import("./ThemeSettings.svelte").default;

beforeAll(async () => {
  window.matchMedia = vi.fn(() => ({
    matches: false,
    addEventListener: () => {},
    removeEventListener: () => {},
  })) as unknown as typeof window.matchMedia;
  localStorage.clear();
  ThemeSettings = (await import("./ThemeSettings.svelte")).default;
});

test("Auto par défaut, puis Sombre appliqué et mémorisé", async () => {
  render(ThemeSettings);
  expect(screen.getByLabelText("Auto")).toBeChecked();

  await fireEvent.click(screen.getByLabelText("Sombre"));
  expect(screen.getByLabelText("Sombre")).toBeChecked();
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("coach.theme")).toBe("dark");
});
