import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Plan from "./Plan.svelte";
import type { CoachEvent, Cycle, Goal, Plan as PlanData } from "../lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
  location.hash = "";
});

const injury: CoachEvent = {
  id: 4, kind: "injury", start_date: "2026-11-01", end_date: null, max_sessions: null, days: null,
  session_id: null, note: null,
};
const cycle: Cycle = {
  id: 1, status: "active", plan_start: "2026-10-26", end_date: "2026-12-06", sessions_per_week: 3,
  available_days: ["lundi", "mercredi", "samedi"], long_run_day: null, include_bike: false, plan_accepted: true,
  needs_generation: false,
};
const goal: Goal = {
  id: 1, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2026-12-06", priority: "principal", status: "active",
  gpx_summary: null, target_time_s: null, target_source: null,
};
const planWith = (open_injury: CoachEvent | null, over: Partial<PlanData> = {}): PlanData => ({
  cycle, goals: [goal], horizon: [], weeks: [{ week_index: 1, week_monday: "2026-10-26", sessions: [] }], open_injury, ...over,
});

/** `resumed` : après la reprise, le plan n'a plus d'arrêt ouvert et l'imprévu est clos. */
function mock(opts: { injury: boolean }) {
  let resumed = false;
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (url === "/api/plan") return json(planWith(opts.injury && !resumed ? injury : null));
    if (url === "/api/cycle/events")
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

test("the header shows the cycle's goal and the plan is read from the cycle", async () => {
  mock({ injury: false });
  render(Plan, { today: "2026-11-03" });
  expect(await screen.findByText(/21,1 km route · course le/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Signaler un imprévu" })).toBeVisible();
});

test("without a cycle, the plan invites to create a goal", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify({ cycle: null, goals: [], horizon: [], open_injury: null, weeks: [] }), { status: 200 })));
  render(Plan, { today: "2026-11-03" });
  expect(await screen.findByRole("link", { name: "Créer un objectif" })).toHaveAttribute("href", "#/goal");
});

test("a draft cycle sends back to the draft", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify(planWith(null, { cycle: { ...cycle, plan_accepted: false } })), { status: 200 })));
  render(Plan, { today: "2026-11-03" });
  expect(await screen.findByRole("link", { name: "Relire le brouillon" })).toBeVisible();
});

const week = { week_index: 1, week_monday: "2026-11-30", sessions: [] };
const secondary: Goal = { ...goal, id: 2, type: "trail", distance_km: 20, d_plus_m: 800, race_date: "2026-12-05", priority: "secondaire" };
const later: Goal = { ...goal, id: 3, distance_km: 10, race_date: "2027-03-14", priority: "plaisir" };

test("montre une carte Course le jour d'un objectif dans le plan", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url === "/api/plan" ? planWith(null, { goals: [secondary, goal], weeks: [week] }) : []), { status: 200 })));
  render(Plan, { today: "2026-12-01" });
  const calendar = await screen.findByRole("table", { name: "Calendrier du programme" });
  const races = await within(calendar).findAllByRole("note", { name: /^Course/ });
  expect(races).toHaveLength(2);
  expect(races[0]).toHaveTextContent("Trail de 20 km");
  expect(races[0]).toHaveTextContent("Secondaire");
  expect(races[1]).toHaveTextContent("Course sur route de 21,1 km");
  expect(races[1]).toHaveTextContent("Principal");
  // samedi puis dimanche de la semaine
  const cells = within(calendar).getAllByRole("cell");
  expect(within(cells[5]).getByText("Trail de 20 km")).toBeVisible();
  expect(within(cells[6]).getByText("Course sur route de 21,1 km")).toBeVisible();
});

test("liste les objectifs de l'horizon sous le plan", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url === "/api/plan" ? planWith(null, { horizon: [later] }) : []), { status: 200 })));
  render(Plan, { today: "2026-11-03" });
  const next = await screen.findByRole("region", { name: "Ensuite" });
  expect(next).toHaveTextContent("Course sur route de 10 km");
  expect(next).toHaveTextContent("Plaisir");
  expect(next).toHaveTextContent("14 mars 2027");
});

test("sans horizon, pas de liste Ensuite", async () => {
  mock({ injury: false });
  render(Plan, { today: "2026-11-03" });
  await screen.findByRole("heading", { name: "Programme" });
  expect(screen.queryByRole("region", { name: "Ensuite" })).toBeNull();
});

// --- plan à recalculer ---------------------------------------------------------------------

const todo = {
  id: 11, order: 1, type: "seuil", title: "Seuil 3 × 10 min", description: "", target_kind: "pace", status: "todo",
  suggested_day: "jeudi", sport: "run", scheduled_date: null, chaining_note: null, sync_error: null,
  steps: [{ kind: "active", duration_s: 1800, zone: "seuil" }],
} as const;

test("plan à recalculer : le plan précédent reste affiché, en lecture seule, avec Générer", async () => {
  let generated = false;
  const stale = planWith(null, {
    cycle: { ...cycle, plan_accepted: false, needs_generation: true },
    weeks: [{ week_index: 2, week_monday: "2026-11-02", sessions: [todo] }],
  });
  const f = vi.fn(async (url: string) => {
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (url === "/api/cycle/generate") {
      generated = true;
      return json({ summary: "ok", weeks: 6 });
    }
    if (url === "/api/plan") return json(generated ? { ...stale, cycle: { ...cycle, plan_accepted: false } } : stale);
    return json([]);
  });
  vi.stubGlobal("fetch", f);
  render(Plan, { today: "2026-11-03" });
  const banner = await screen.findByRole("region", { name: "Plan à recalculer" });
  expect(banner).toHaveTextContent("Le plan doit être recalculé");
  expect(screen.queryByRole("link", { name: "Relire le brouillon" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Signaler un imprévu" })).toBeNull();
  const calendar = screen.getByRole("table", { name: "Calendrier du programme" });
  await fireEvent.click(within(calendar).getByRole("button", { name: /Seuil 3 × 10 min/ }));
  const side = screen.getByRole("complementary", { name: "Séance sélectionnée" });
  expect(within(side).getByRole("heading", { name: "Seuil 3 × 10 min" })).toBeVisible();
  expect(within(side).queryByRole("button", { name: "Envoyer sur la montre" })).toBeNull();
  await fireEvent.click(within(banner).getByRole("button", { name: "Générer" }));
  await waitFor(() => expect(f.mock.calls.some(([u, i]) => u === "/api/cycle/generate" && i?.method === "POST")).toBe(true));
  expect(await screen.findByRole("link", { name: "Relire le brouillon" })).toBeVisible();
});

test("plan à recalculer sans séance : renvoie aux objectifs", async () => {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify(planWith(null, { cycle: { ...cycle, plan_accepted: false, needs_generation: true } })), { status: 200 })));
  render(Plan, { today: "2026-11-03" });
  expect(await screen.findByRole("link", { name: "Relire le brouillon" })).toBeVisible();
  expect(screen.queryByRole("region", { name: "Plan à recalculer" })).toBeNull();
});
