import { render, screen } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Goal from "./Goal.svelte";

afterEach(() => vi.unstubAllGlobals());

test("goal form bounds match the backend (2 to 7 sessions, positive distance)", () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ goal: null, weeks: [] }), { status: 200 })));
  render(Goal);
  const perWeek = screen.getByLabelText("Séances par semaine") as HTMLInputElement;
  expect(perWeek.min).toBe("2");
  expect(perWeek.max).toBe("7");
  const distance = screen.getByLabelText("Distance (km)") as HTMLInputElement;
  expect(Number(distance.min)).toBeGreaterThan(0);
});
