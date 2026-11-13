import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Race from "./Race.svelte";
import type { Goal, RaceSegment, RaceView } from "../lib/api";

vi.mock("../components/stats/EChart.svelte", () => import("../test/EChartStub.svelte"));

afterEach(() => vi.unstubAllGlobals());

const goal: Goal = {
  id: 7, type: "route", distance_km: 10, d_plus_m: 0, race_date: "2026-12-06", priority: "principal", status: "active",
  gpx_summary: null, target_time_s: null, target_source: null,
};

const segments: RaceSegment[] = Array.from({ length: 10 }, (_, i) => ({
  kind: "plat", start_km: i, end_km: i + 1, eq_km: 1, d_plus_m: 0, d_minus_m: 0, index: i + 1, avg_grade_pct: 0,
  time_s: 288, pace_s_km: 288, elapsed_s: 288 * (i + 1), clock: "08:04", target_kind: "pace",
  target_low: 283, target_high: 293, target_zone: null,
}));

const view = (over: Partial<RaceView> = {}): RaceView => ({
  goal_id: 7, goal_type: "route", race_date: "2026-12-06",
  settings: { start_time: "08:00", carbs_g_h: 60, water_ml_h: 500, carry_ml: 1000, aid_stations: [] },
  basis_date: "2026-10-30", profile: null, workout_id: null, export_error: null, export_stale: false,
  plan: {
    distance_km: 10, eq_km: 10, stops_s: 0, target_time_s: null, reference_time_s: 2880,
    segments, aid_passages: [], nutrition: [], warnings: [],
  },
  target_time_s: null, target_source: null,
  ...over,
});

const targeted = (seconds: number, source: "claude" | "user") =>
  view({ target_time_s: seconds, target_source: source, plan: { ...view().plan, target_time_s: seconds, reference_time_s: seconds } });

function mock(data = view()) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(data), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const calls = (f: ReturnType<typeof mock>) =>
  f.mock.calls.map((c) => `${(c[1] as RequestInit).method} ${c[0]}`);

test("a road goal shows the reference time and its 10 segments, without aid stations", async () => {
  mock();
  render(Race, { goal });
  expect(await screen.findByText("48 min")).toBeVisible();
  const table = screen.getByRole("table", { name: "Segments" });
  expect(within(table).getAllByRole("row")).toHaveLength(11); // en-tête + 10
  expect(screen.queryByText("Ravitaillements")).toBeNull();
});

test("the target time is the only time shown, without Garmin data on the road", async () => {
  mock(targeted(6720, "claude"));
  render(Race, { goal });
  expect(await screen.findByText("Temps visé")).toBeVisible();
  expect(screen.getByText("1 h 52")).toBeVisible();
  expect(screen.getByText("estimé par Claude")).toBeVisible();
  expect(screen.queryByText(/prédit/i)).toBeNull();
  expect(screen.queryByRole("button", { name: "Actualiser" })).toBeNull();
});

test("a trail goal with a target keeps the Garmin data refresh for the heart-rate zones", async () => {
  const v = trailView();
  mock({ ...v, target_time_s: 3600, target_source: "user", plan: { ...v.plan, target_time_s: 3600, reference_time_s: 3600 } });
  render(Race, { goal: trailGoal });
  expect(await screen.findByRole("button", { name: "Actualiser" })).toBeVisible();
});

test("target time is read-only, editing the goal opens the prefilled dialog", async () => {
  mock(targeted(6720, "claude"));
  render(Race, { goal });
  expect(await screen.findByText("estimé par Claude")).toBeVisible();
  expect(screen.queryByLabelText("Temps visé")).toBeNull();
  await fireEvent.click(screen.getByRole("button", { name: "Modifier l'objectif" }));
  const dialog = screen.getByRole("dialog", { name: "Modifier l'objectif" });
  expect(within(dialog).getByLabelText("Date de la course")).toHaveValue("2026-12-06");
  await fireEvent.click(within(dialog).getByRole("button", { name: "Annuler" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("saving the goal edit refreshes the app and shows the proposal", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) =>
      new Response(JSON.stringify(init?.method === "PATCH" ? { goal, proposal_id: 9 } : view()), { status: 200 }),
    ),
  );
  const onchanged = vi.fn();
  location.hash = "#/race";
  render(Race, { goal, onchanged });
  await fireEvent.click(await screen.findByRole("button", { name: "Modifier l'objectif" }));
  const dialog = screen.getByRole("dialog", { name: "Modifier l'objectif" });
  await fireEvent.input(within(dialog).getByLabelText("Date de la course"), { target: { value: "2026-12-13" } });
  await fireEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(location.hash).toBe("#/proposal"));
  expect(onchanged).toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a user-set target time says so", async () => {
  mock(targeted(6600, "user"));
  render(Race, { goal });
  expect(await screen.findByText("fixé par toi")).toBeVisible();
});

test("no goal time falls back on the Garmin estimate", async () => {
  mock();
  render(Race, { goal });
  expect(await screen.findByText("Estimation d'après tes données Garmin")).toBeVisible();
  expect(screen.getByText("Pas de temps visé")).toBeVisible();
  expect(screen.getByRole("button", { name: "Actualiser" })).toBeVisible();
});

test("saving sends no target time", async () => {
  const f = mock();
  render(Race, { goal });
  await fireEvent.input(await screen.findByLabelText("Heure de départ"), { target: { value: "09:00" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  const put = f.mock.calls.find((c) => (c[1] as RequestInit).method === "PUT")!;
  expect(JSON.parse((put[1] as RequestInit).body as string)).not.toHaveProperty("target_time_s");
});

test("sending to the watch posts the export", async () => {
  const f = mock();
  render(Race, { goal });
  await fireEvent.click(await screen.findByRole("button", { name: "Envoyer à la montre" }));
  expect(calls(f)).toContain("POST /api/goals/7/race-plan/export");
});

const trailGoal: Goal = { ...goal, type: "trail", d_plus_m: 800 };
const station = { km: 5, name: "Ravito Col", kind: "complet" as const, cutoff: "09:30", stop_min: 3 };
const trailView = (): RaceView =>
  view({
    goal_type: "trail",
    profile: [[0, 100], [5, 300], [10, 120]],
    settings: { ...view().settings, aid_stations: [station] },
    plan: {
      ...view().plan,
      stops_s: 180,
      aid_passages: [
        { station, passage: { elapsed_s: 5400, clock: "09:30", margin_min: 12, status: "serré" } },
      ],
      nutrition: [
        { from_name: "Départ", to_name: "Ravito Col", from_km: 0, to_km: 5, duration_s: 5400, carbs_g: 90, water_ml: 1200, over_capacity: true },
        { from_name: "Ravito Col", to_name: "Arrivée", from_km: 5, to_km: 10, duration_s: 3600, carbs_g: 60, water_ml: 500, over_capacity: false },
      ],
    },
  });

test("a trail goal lists aid stations with their status, the nutrition legs and the profile", async () => {
  mock(trailView());
  render(Race, { goal: trailGoal });
  const table = await screen.findByRole("table", { name: "Ravitaillements" });
  expect(within(table).getByDisplayValue("Ravito Col")).toBeVisible();
  expect(within(table).getByText("serré")).toBeVisible();
  expect(within(table).getByText("09:30", { selector: "td" })).toBeVisible();
  expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toContain("Heure de passage");
  expect(within(table).queryByText("Heure visée")).toBeNull();
  const nutrition = screen.getByRole("table", { name: "Nutrition" });
  expect(within(nutrition).getAllByRole("row")).toHaveLength(3); // en-tête + 2 tronçons
  expect(within(nutrition).getByText(/contenance/i)).toBeVisible();
  expect(screen.getByRole("img", { name: /profil/i })).toBeInTheDocument();
});

test("a road goal has no elevation chart", async () => {
  mock();
  render(Race, { goal });
  await screen.findByText("48 min");
  expect(screen.queryByRole("img", { name: /profil/i })).toBeNull();
});

test("adding an aid station flags unsaved changes and is saved with the PUT", async () => {
  const f = mock(trailView());
  render(Race, { goal: trailGoal });
  await fireEvent.click(await screen.findByRole("button", { name: "Ajouter un ravitaillement" }));
  expect(screen.getByText("Modifications non enregistrées")).toBeVisible();
  expect(screen.getByRole("button", { name: "Réimporter depuis le GPX" })).toBeDisabled();
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  const put = f.mock.calls.find((c) => (c[1] as RequestInit).method === "PUT")!;
  const body = JSON.parse((put[1] as RequestInit).body as string);
  expect(body.aid_stations).toHaveLength(2);
  expect(body.aid_stations[1]).toMatchObject({ kind: "complet", stop_min: 3 });
});

test("switching a station to water sets a one-minute stop", async () => {
  mock(trailView());
  render(Race, { goal: trailGoal });
  await fireEvent.change(await screen.findByLabelText("Type du ravitaillement 1"), { target: { value: "eau" } });
  expect(screen.getByLabelText("Arrêt du ravitaillement 1 (min)")).toHaveValue(1);
});

test("removing an aid station marks the page dirty", async () => {
  mock(trailView());
  render(Race, { goal: trailGoal });
  await fireEvent.click(await screen.findByRole("button", { name: "Supprimer le ravitaillement 1" }));
  expect(screen.getByText("Modifications non enregistrées")).toBeVisible();
  expect(screen.queryByDisplayValue("Ravito Col")).toBeNull();
});

test("editing the nutrition settings marks the page dirty", async () => {
  mock(trailView());
  render(Race, { goal: trailGoal });
  await fireEvent.input(await screen.findByLabelText("Glucides (g/h)"), { target: { value: "70" } });
  expect(screen.getByText("Modifications non enregistrées")).toBeVisible();
});

test("reimporting from the GPX posts to reimport", async () => {
  const f = mock(trailView());
  render(Race, { goal: trailGoal });
  await fireEvent.click(await screen.findByRole("button", { name: "Réimporter depuis le GPX" }));
  expect(calls(f)).toContain("POST /api/goals/7/race-plan/reimport");
});

test("duplicate warnings and aid stations at the same km render without key clash", async () => {
  const late = "Barrière hors délai au ravito « Col » avec le temps prédit";
  const v = trailView();
  const twin = { ...station, km: 5 };
  v.settings.aid_stations = [station, twin];
  v.plan.warnings = [late, late];
  v.plan.nutrition = [
    { from_name: "Départ", to_name: "Col", from_km: 0, to_km: 5, duration_s: 1800, carbs_g: 30, water_ml: 250, over_capacity: false },
    { from_name: "Col", to_name: "Col", from_km: 5, to_km: 5, duration_s: 0, carbs_g: 0, water_ml: 0, over_capacity: false },
    { from_name: "Col", to_name: "Arrivée", from_km: 5, to_km: 10, duration_s: 1800, carbs_g: 30, water_ml: 250, over_capacity: false },
  ];
  mock(v);
  render(Race, { goal: trailGoal });
  expect(await screen.findAllByText(late)).toHaveLength(2);
  expect(within(screen.getByRole("table", { name: "Nutrition" })).getAllByRole("row")).toHaveLength(4);
});

test("the watch status says whether the sent plan is outdated", async () => {
  mock(view({ workout_id: 12 }));
  const { unmount } = render(Race, { goal });
  expect(await screen.findByText("Envoyé à la montre")).toBeVisible();
  unmount();
  mock(view({ workout_id: 12, export_stale: true }));
  render(Race, { goal });
  expect(await screen.findByText("Plan modifié depuis l'envoi : renvoie-le à la montre")).toBeVisible();
  expect(screen.queryByText("Envoyé à la montre")).toBeNull();
});

test("refreshing is disabled while the draft has unsaved changes", async () => {
  mock();
  render(Race, { goal });
  const refresh = await screen.findByRole("button", { name: "Actualiser" });
  expect(refresh).toBeEnabled();
  await fireEvent.input(screen.getByLabelText("Heure de départ"), { target: { value: "09:00" } });
  expect(refresh).toBeDisabled();
});

test("an emptied aid station km blocks saving with a French message", async () => {
  const f = mock(trailView());
  render(Race, { goal: trailGoal });
  await fireEvent.input(await screen.findByLabelText("Km du ravitaillement 1"), { target: { value: "" } });
  expect(screen.getByRole("alert")).toHaveTextContent("Ravitaillement 1");
  const save = screen.getByRole("button", { name: "Enregistrer" });
  expect(save).toBeDisabled();
  await fireEvent.click(save);
  expect(calls(f).some((c) => c.startsWith("PUT"))).toBe(false);
});

test("a new aid station stays before the finish", async () => {
  const f = mock(trailView());
  render(Race, { goal: trailGoal });
  await fireEvent.click(await screen.findByRole("button", { name: "Ajouter un ravitaillement" }));
  expect(screen.getByLabelText("Km du ravitaillement 2")).toHaveValue(9.9);
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(calls(f)).toContain("PUT /api/goals/7/race-plan");
});

test("the trail header labels the elevation gain as computed from the profile", async () => {
  mock(trailView());
  render(Race, { goal: trailGoal });
  expect(await screen.findByText("D+ (profil)")).toBeVisible();
});
