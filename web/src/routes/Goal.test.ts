import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Goal from "./Goal.svelte";

afterEach(() => vi.unstubAllGlobals());

const noPlan = () =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ goal: null, weeks: [] }), { status: 200 })));

test("goal form bounds match the backend (2 to 7 sessions, positive distance)", () => {
  noPlan();
  render(Goal);
  const perWeek = within(screen.getByRole("group", { name: "Séances par semaine" }));
  expect(perWeek.getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["2", "3", "4", "5", "6", "7"]);
  const distance = screen.getByLabelText("Distance (km)") as HTMLInputElement;
  expect(Number(distance.min)).toBeGreaterThan(0);
});

test("distance presets fill the distance field", async () => {
  noPlan();
  render(Goal);
  await fireEvent.click(screen.getByRole("button", { name: "Marathon · 42,2 km" }));
  expect((screen.getByLabelText("Distance (km)") as HTMLInputElement).value).toBe("42.2");
  expect(screen.getByRole("button", { name: "Marathon · 42,2 km" })).toHaveAttribute("aria-pressed", "true");
});
