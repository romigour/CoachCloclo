import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Today from "./Today.svelte";
import type { Plan, Session } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const s = (id: number, title: string, suggested_day: Session["suggested_day"], status: Session["status"]): Session => ({
  id, order: id, type: "seuil", title, description: "", target_kind: "pace", status, suggested_day,
  sport: "run", scheduled_date: null, chaining_note: null, sync_error: null,
  steps: [{ kind: "warmup", duration_s: 1200, zone: "EF" }, { kind: "active", duration_s: 1800, zone: "seuil" }],
});

const plan: Plan = {
  cycle: { id: 1, status: "active", plan_start: "2026-10-26", end_date: "2026-12-06", sessions_per_week: 3, available_days: ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"], long_run_day: null, include_bike: false, plan_accepted: true, needs_generation: false },
  goals: [{ id: 1, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2026-12-06", priority: "principal", status: "active", gpx_summary: null, target_time_s: null, target_source: null }],
  horizon: [],
  open_injury: null,
  weeks: [{ week_index: 1, week_monday: "2026-10-26", sessions: [s(1, "Endurance 50 min", "lundi", "done"), s(2, "Seuil 3 × 10 min", "vendredi", "todo")] }],
};

function mock() {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.startsWith("/api/plan") ? plan : []), { status: 200 })));
}

test("today's session is the focus, with its single main action", async () => {
  mock();
  render(Today, { today: "2026-10-30" });
  expect(await screen.findByRole("heading", { name: "Seuil 3 × 10 min" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Envoyer sur la montre" })).toBeVisible();
  expect(screen.getByText("J-37")).toBeVisible();
  expect(screen.getAllByText("Repos")).toHaveLength(5);
});

test("on a rest day the next session of the week is shown", async () => {
  mock();
  render(Today, { today: "2026-10-28" });
  expect(await screen.findByRole("heading", { name: "Seuil 3 × 10 min" })).toBeVisible();
});

test("once the week is over, it says so", async () => {
  mock();
  render(Today, { today: "2026-10-31" });
  expect(await screen.findByRole("heading", { name: "Repos aujourd'hui" })).toBeVisible();
});

test("Signaler un imprévu opens the event dialog", async () => {
  mock();
  render(Today, { today: "2026-10-30" });
  await fireEvent.click(await screen.findByRole("button", { name: "Signaler un imprévu" }));
  expect(screen.getByRole("dialog", { name: "Signaler un imprévu" })).toBeVisible();
});
