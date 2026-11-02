import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Plan from "./Plan.svelte";
import type { CoachEvent, Plan as PlanData } from "../lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
  location.hash = "";
});

const injury: CoachEvent = {
  id: 4, kind: "injury", start_date: "2026-11-01", end_date: null, max_sessions: null, days: null,
  session_id: null, note: null,
};
const goal = {
  id: 1, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2026-12-06", sessions_per_week: 3,
  plan_start: "2026-10-26", plan_accepted: true, gpx_summary: null, target_time_s: null, target_source: null,
  available_days: null, long_run_day: null,
} as PlanData["goal"];
const planWith = (open_injury: CoachEvent | null): PlanData => ({
  goal, weeks: [{ week_index: 1, week_monday: "2026-10-26", sessions: [] }], open_injury,
});

/** `resumed` : après la reprise, le plan n'a plus d'arrêt ouvert et l'imprévu est clos. */
function mock(opts: { injury: boolean }) {
  let resumed = false;
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (url === "/api/plan") return json(planWith(opts.injury && !resumed ? injury : null));
    if (url === "/api/goals/1/events")
      return json(opts.injury ? [{ ...injury, end_date: resumed ? "2026-11-02" : null }] : []);
    if (url === "/api/events/4/resume") {
      resumed = true;
      return json({ event_id: 4, proposal_id: 8, error: null });
    }
    return json([]);
  });
  vi.stubGlobal("fetch", f);
  return f;
}
const planCalls = (f: ReturnType<typeof mock>) => f.mock.calls.filter((c) => c[0] === "/api/plan").length;

test("the banner shows for an open injury and not otherwise", async () => {
  mock({ injury: true });
  const { unmount } = render(Plan, { today: "2026-11-03" });
  expect(await screen.findByText("Arrêt depuis le 01/11")).toBeVisible();
  unmount();
  mock({ injury: false });
  render(Plan, { today: "2026-11-03" });
  await screen.findByRole("heading", { name: "Programme" });
  await waitFor(() => expect(screen.queryByText(/Arrêt depuis/)).toBeNull());
});

test("resuming reloads the plan, clears the list and goes to the proposal", async () => {
  const f = mock({ injury: true });
  render(Plan, { today: "2026-11-03" });
  await screen.findByText(/Blessure \/ maladie · depuis le 01\/11/);
  const before = planCalls(f);
  await fireEvent.click(await screen.findByRole("button", { name: "Signaler la reprise" }));
  await fireEvent.click(screen.getByRole("button", { name: "Confirmer la reprise" }));
  await waitFor(() => expect(location.hash).toBe("#/proposal"));
  await waitFor(() => expect(planCalls(f)).toBeGreaterThan(before));
  await waitFor(() => expect(screen.queryByText(/Arrêt depuis/)).toBeNull());
  await waitFor(() => expect(screen.queryByRole("button", { name: "Supprimer" })).toBeNull());
});
