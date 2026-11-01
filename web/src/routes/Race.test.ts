import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Race from "./Race.svelte";
import type { Goal, RaceSegment, RaceView } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const goal: Goal = {
  id: 7, type: "route", distance_km: 10, d_plus_m: 0, race_date: "2026-12-06", sessions_per_week: 3,
  plan_start: "2026-10-26", plan_accepted: true, gpx_summary: null,
};

const segments: RaceSegment[] = Array.from({ length: 10 }, (_, i) => ({
  kind: "plat", start_km: i, end_km: i + 1, eq_km: 1, d_plus_m: 0, d_minus_m: 0, index: i + 1, avg_grade_pct: 0,
  time_s: 288, pace_s_km: 288, elapsed_s: 288 * (i + 1), clock: "08:04", target_kind: "pace",
  target_low: 283, target_high: 293, target_zone: null,
}));

const view = (over: Partial<RaceView> = {}): RaceView => ({
  goal_id: 7, goal_type: "route", race_date: "2026-12-06",
  settings: { target_time_s: null, start_time: "08:00", carbs_g_h: 60, water_ml_h: 500, carry_ml: 1000, aid_stations: [] },
  basis_date: "2026-10-30", profile: null, workout_id: null, export_error: null,
  plan: {
    distance_km: 10, eq_km: 10, stops_s: 0, predicted_time_s: 2880, target_time_s: null, reference_time_s: 2880,
    segments, aid_passages: [], nutrition: [], warnings: [],
  },
  ...over,
});

function mock(data = view()) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(data), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const calls = (f: ReturnType<typeof mock>) =>
  f.mock.calls.map((c) => `${(c[1] as RequestInit).method} ${c[0]}`);

test("a road goal shows the predicted time and its 10 segments, without aid stations", async () => {
  mock();
  render(Race, { goal });
  expect(await screen.findByText("48 min")).toBeVisible();
  const table = screen.getByRole("table", { name: "Segments" });
  expect(within(table).getAllByRole("row")).toHaveLength(11); // en-tête + 10
  expect(screen.queryByText("Ravitaillements")).toBeNull();
});

test("editing the target time flags unsaved changes, saving sends a PUT", async () => {
  const f = mock();
  render(Race, { goal });
  const input = await screen.findByLabelText("Temps visé");
  expect(screen.queryByText("Modifications non enregistrées")).toBeNull();
  await fireEvent.input(input, { target: { value: "0:45:00" } });
  expect(screen.getByText("Modifications non enregistrées")).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(calls(f)).toContain("PUT /api/goals/7/race-plan");
  const put = f.mock.calls.find((c) => (c[1] as RequestInit).method === "PUT")!;
  expect(JSON.parse((put[1] as RequestInit).body as string).target_time_s).toBe(2700);
});

test("an invalid target time is refused before any request", async () => {
  const f = mock();
  render(Race, { goal });
  await fireEvent.input(await screen.findByLabelText("Temps visé"), { target: { value: "abc" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Temps visé invalide");
  expect(calls(f).some((c) => c.startsWith("PUT"))).toBe(false);
});

test("sending to the watch posts the export", async () => {
  const f = mock();
  render(Race, { goal });
  await fireEvent.click(await screen.findByRole("button", { name: "Envoyer à la montre" }));
  expect(calls(f)).toContain("POST /api/goals/7/race-plan/export");
});
