import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Race from "./Race.svelte";
import type { Cycle, Goal, RaceGuide, RaceSegment, RaceView } from "../lib/api";

vi.mock("../components/stats/EChart.svelte", () => import("../test/EChartStub.svelte"));

afterEach(() => vi.unstubAllGlobals());

const goal: Goal = {
  id: 7, type: "route", distance_km: 10, d_plus_m: 0, race_date: "2026-12-06", priority: "principal", status: "active",
  gpx_summary: null, target_time_s: null, target_source: null,
};

/** Cycle qui se termine par la course de `goal`. */
const cycle: Cycle = {
  id: 1, status: "active", plan_start: "2026-10-26", end_date: "2026-12-06", sessions_per_week: 3,
  available_days: ["lundi"], long_run_day: null, include_bike: false, plan_accepted: true, needs_generation: false, adjust_due: false,
};

const segments: RaceSegment[] = Array.from({ length: 10 }, (_, i) => ({
  kind: "plat", start_km: i, end_km: i + 1, eq_km: 1, d_plus_m: 0, d_minus_m: 0, index: i + 1, avg_grade_pct: 0,
  time_s: 288, pace_s_km: 288, elapsed_s: 288 * (i + 1), clock: "08:04", target_kind: "pace",
  target_low: 283, target_high: 293, target_zone: null,
}));

const phase = (name: RaceGuide["phases"][number]["name"], start_km: number, end_km: number, pace: number, clock: string) => ({
  name, start_km, end_km, pace_low_s_km: pace - 5, pace_high_s_km: pace + 5, hr_zone: null, hr_low: null, hr_high: null,
  elapsed_end_s: Math.round(end_km * 288), clock_end: clock, terrain: [] as string[], advice: `Conseil ${name}`,
});

const guide = (over: Partial<RaceGuide> = {}): RaceGuide => ({
  band: "court", reference_time_s: 2880, avg_pace_s_km: 288,
  phases: [phase("Départ", 0, 1.5, 298, "08:07"), phase("Cœur de course", 1.5, 8.5, 288, "08:41"), phase("Final", 8.5, 10, 280, "08:48")],
  splits: [{ km: 5, label: "5 km", elapsed_s: 1440, clock: "08:24" }, { km: 10, label: "Arrivée", elapsed_s: 2880, clock: "08:48" }],
  nutrition: { carbs_g_h: 0, water_ml_h: 0, recommended: true, principle: "Moins de 1 h 15 de course : pas besoin de glucides.", intakes: [] },
  morning: [
    { clock: "06:00", label: "Petit-déjeuner : un repas connu" },
    { clock: "07:30", label: "Échauffement : 15–20 min de footing" },
    { clock: "08:00", label: "Départ" },
  ],
  preparation: [
    { title: "La semaine d'avant", items: ["Dors bien."] },
    { title: "La veille", items: ["Prépare ton dossard."] },
    { title: "Le matin", items: ["Rien de nouveau aujourd'hui."] },
  ],
  ...over,
});

const view = (over: Partial<RaceView> = {}): RaceView => ({
  goal_id: 7, goal_type: "route", race_date: "2026-12-06",
  settings: { start_time: "08:00", carbs_g_h: null, water_ml_h: null, carry_ml: 1000, aid_stations: [] },
  guide: guide(), advice: null, advice_at: null, advice_stale: false, updated_at: null,
  basis_date: "2026-10-30", profile: null, workout_id: null, export_error: null, export_stale: false,
  plan: {
    distance_km: 10, eq_km: 10, stops_s: 0, target_time_s: null, reference_time_s: 2880,
    segments, aid_passages: [], nutrition: [], warnings: [],
  },
  target_time_s: null, target_source: null,
  ...over,
});

const targeted = (seconds: number, source: "claude" | "user") =>
  view({
    target_time_s: seconds, target_source: source,
    plan: { ...view().plan, target_time_s: seconds, reference_time_s: seconds },
    guide: guide({ reference_time_s: seconds }),
  });

function mock(data = view()) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(data), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const calls = (f: ReturnType<typeof mock>) =>
  f.mock.calls.map((c) => `${(c[1] as RequestInit).method} ${c[0]}`);

test("a road goal without GPX shows phases and splits, no segment table", async () => {
  mock();
  render(Race, { goals: [goal], goalId: goal.id });
  const box = await screen.findByRole("region", { name: "À retenir le matin" });
  expect(within(box).getByText("48 min")).toBeVisible();
  expect(within(box).getByText("4:48 /km")).toBeVisible();
  expect(within(box).getByText(/4:53–5:03 \/km jusqu'au km 1,5/)).toBeVisible();
  expect(within(box).getByText(/5 km 24:00/)).toBeVisible();
  expect(within(box).getByText(/06:00 Petit-déjeuner/)).toBeVisible();
  const phases = screen.getByRole("region", { name: "Pendant la course" });
  expect(within(phases).getByText("Cœur de course")).toBeVisible();
  expect(within(phases).getByText("Conseil Final")).toBeVisible();
  const splits = screen.getByRole("table", { name: "Passages" });
  expect(within(splits).getAllByRole("row")).toHaveLength(3); // en-tête + 5 km + arrivée
  expect(within(splits).getByText("08:24")).toBeVisible();
  expect(screen.getByRole("region", { name: "Préparation" })).toHaveTextContent("Prépare ton dossard.");
  expect(screen.queryByRole("table", { name: "Segments" })).toBeNull();
  expect(screen.queryByText("Parcours")).toBeNull();
  expect(screen.queryByText("Ravitaillements")).toBeNull();
});

test("a road goal with a profile keeps the segment table folded", async () => {
  mock(view({ profile: [[0, 100], [5, 140], [10, 110]] }));
  render(Race, { goals: [goal], goalId: goal.id });
  const table = await screen.findByRole("table", { name: "Segments" });
  expect(within(table).getAllByRole("row")).toHaveLength(11); // en-tête + 10
  expect(table).not.toBeVisible();
  await fireEvent.click(screen.getByText("Parcours"));
  expect(table).toBeVisible();
});

test("empty carbs show the recommended value", async () => {
  const f = mock(view({ guide: guide({ nutrition: { ...guide().nutrition, carbs_g_h: 45, water_ml_h: 400 } }) }));
  render(Race, { goals: [goal], goalId: goal.id });
  const carbs = await screen.findByLabelText("Glucides (g/h)");
  expect(carbs).toHaveValue(null);
  expect(carbs).toHaveAttribute("placeholder", "recommandé : 45");
  expect(screen.getByLabelText("Eau (ml/h)")).toHaveAttribute("placeholder", "recommandé : 400");
  await fireEvent.input(carbs, { target: { value: "70" } });
  await fireEvent.input(carbs, { target: { value: "" } });
  await fireEvent.input(screen.getByLabelText("Heure de départ"), { target: { value: "09:00" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  const put = f.mock.calls.find((c) => (c[1] as RequestInit).method === "PUT")!;
  expect(JSON.parse((put[1] as RequestInit).body as string)).toMatchObject({ carbs_g_h: null, water_ml_h: null });
});

test("coach advice button posts and renders tips", async () => {
  const advised = view({
    advice: { tips: [{ title: "Pars doucement", text: "Ton dernier 10 km est parti trop vite." }] },
    advice_at: "2026-11-26T09:12:00Z",
  });
  const f = vi.fn(async (_url: string, init?: RequestInit) =>
    new Response(JSON.stringify(init?.method === "POST" ? advised : view()), { status: 200 }));
  vi.stubGlobal("fetch", f);
  render(Race, { goals: [goal], goalId: goal.id });
  const section = await screen.findByRole("region", { name: "Conseils du coach" });
  await fireEvent.click(within(section).getByRole("button", { name: "Demander les conseils du coach" }));
  expect(await within(section).findByText("Pars doucement")).toBeVisible();
  expect(within(section).getByText("Ton dernier 10 km est parti trop vite.")).toBeVisible();
  expect(within(section).getByText(/26 nov\. 2026/)).toBeVisible();
  expect(calls(f as never)).toContain("POST /api/goals/7/race-plan/advice");
});

test("stale advice shows the redo hint", async () => {
  mock(view({ advice: { tips: [{ title: "Pars doucement", text: "Texte." }] }, advice_at: "2026-11-20T09:00:00Z", advice_stale: true }));
  render(Race, { goals: [goal], goalId: goal.id });
  expect(await screen.findByText("Objectif modifié depuis : redemande les conseils")).toBeVisible();
  expect(screen.getByText("Pars doucement")).toBeVisible();
});

test("advice error stays inside its section", async () => {
  const onerror = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "POST"
        ? new Response(JSON.stringify({ code: "llm_timeout", detail: "Claude a mis trop de temps à répondre" }), { status: 502 })
        : new Response(JSON.stringify(view()), { status: 200 }),
    ),
  );
  render(Race, { goals: [goal], goalId: goal.id, onerror });
  const section = await screen.findByRole("region", { name: "Conseils du coach" });
  await fireEvent.click(within(section).getByRole("button", { name: "Demander les conseils du coach" }));
  expect(await within(section).findByText(/Claude a mis trop de temps à répondre/)).toBeVisible();
  expect(onerror).not.toHaveBeenCalled();
  expect(screen.getByRole("region", { name: "À retenir le matin" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Enregistrer" })).toBeVisible();
});

test("a guide without reference time keeps advice and preparation, without pace, passage or phases", async () => {
  mock(view({
    plan: { ...view().plan, reference_time_s: null, warnings: ["Pas de temps de référence : fixe un temps visé sur l'objectif"] },
    guide: guide({ reference_time_s: null, avg_pace_s_km: null, phases: [], splits: [] }),
  }));
  render(Race, { goals: [goal], goalId: goal.id, cycle });
  const box = await screen.findByRole("region", { name: "À retenir le matin" });
  expect(within(box).queryByText(/\/km/)).toBeNull();
  expect(within(box).queryByText("Départ", { selector: "dt" })).toBeNull();
  expect(within(box).queryByText("Passages")).toBeNull();
  expect(within(box).getByText("Pas de temps de référence : fixe un temps visé sur l'objectif")).toBeVisible();
  expect(screen.queryByRole("region", { name: "Pendant la course" })).toBeNull();
  expect(screen.queryByRole("table", { name: "Passages" })).toBeNull();
  expect(screen.getByRole("region", { name: "Préparation" })).toHaveTextContent("Prépare ton dossard.");
  expect(screen.getByRole("region", { name: "Conseils du coach" })).toBeVisible();
  const nutrition = screen.getByRole("region", { name: "Eau et nutrition" });
  expect(nutrition).not.toHaveTextContent(/\b0 g/);
  expect(nutrition).toHaveTextContent("pas besoin de glucides");
});

test("an advice error does not follow the runner to another goal", async () => {
  const other: Goal = { ...goal, id: 8, race_date: "2027-01-17" };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) =>
      init?.method === "POST"
        ? new Response(JSON.stringify({ code: "llm_timeout", detail: "Claude a mis trop de temps à répondre" }), { status: 502 })
        : new Response(JSON.stringify(url.includes("/goals/8/") ? view({ goal_id: 8, race_date: "2027-01-17" }) : view()), { status: 200 }),
    ),
  );
  render(Race, { goals: [goal, other], goalId: 7 });
  const section = await screen.findByRole("region", { name: "Conseils du coach" });
  await fireEvent.click(within(section).getByRole("button", { name: "Demander les conseils du coach" }));
  expect(await within(section).findByText(/Claude a mis trop de temps à répondre/)).toBeVisible();
  await fireEvent.change(screen.getByLabelText("Objectif"), { target: { value: "8" } });
  expect(await screen.findByText("17 janv. 2027")).toBeVisible();
  expect(screen.queryByText(/Conseils indisponibles/)).toBeNull();
});

test("a trail morning box gives the heart-rate cue, the aid passages with their margin and the water to carry", async () => {
  mock(trailView());
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  const box = await screen.findByRole("region", { name: "À retenir le matin" });
  expect(within(box).getByText(/Z2 · 130–145 bpm/)).toBeVisible();
  expect(within(box).getByText(/Ravito Col 09:30/)).toHaveTextContent("12 min de marge");
  expect(within(box).getByText(/emporte 1\s000 ml/)).toBeVisible();
  const phases = screen.getByRole("region", { name: "Pendant la course" });
  expect(within(phases).getByText("Montée km 1.05–4, +200 m")).toBeVisible();
  expect(screen.queryByRole("table", { name: "Passages" })).toBeNull();
});

test("the target time is the only time shown, without Garmin data on the road", async () => {
  mock(targeted(6720, "claude"));
  render(Race, { goals: [goal], goalId: goal.id });
  expect(await screen.findByText("Temps visé")).toBeVisible();
  expect(screen.getByText("1 h 52")).toBeVisible();
  expect(screen.getByText("estimé par Claude")).toBeVisible();
  expect(screen.queryByText(/prédit/i)).toBeNull();
  expect(screen.queryByRole("button", { name: "Actualiser" })).toBeNull();
});

test("a trail goal with a target keeps the Garmin data refresh for the heart-rate zones", async () => {
  const v = trailView();
  mock({ ...v, target_time_s: 3600, target_source: "user", plan: { ...v.plan, target_time_s: 3600, reference_time_s: 3600 } });
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  expect(await screen.findByRole("button", { name: "Actualiser" })).toBeVisible();
});

test("target time is read-only, editing the goal opens the prefilled dialog", async () => {
  mock(targeted(6720, "claude"));
  render(Race, { goals: [goal], goalId: goal.id });
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
  render(Race, { goals: [goal], goalId: goal.id, onchanged });
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
  render(Race, { goals: [goal], goalId: goal.id });
  expect(await screen.findByText("fixé par toi")).toBeVisible();
});

test("no goal time falls back on the Garmin estimate", async () => {
  mock();
  render(Race, { goals: [goal], goalId: goal.id, cycle });
  expect(await screen.findByText("Estimation d'après tes données Garmin")).toBeVisible();
  expect(screen.getByText("Pas de temps visé")).toBeVisible();
  expect(screen.getByRole("button", { name: "Actualiser" })).toBeVisible();
});

test("saving sends no target time", async () => {
  const f = mock();
  render(Race, { goals: [goal], goalId: goal.id });
  await fireEvent.input(await screen.findByLabelText("Heure de départ"), { target: { value: "09:00" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  const put = f.mock.calls.find((c) => (c[1] as RequestInit).method === "PUT")!;
  expect(JSON.parse((put[1] as RequestInit).body as string)).not.toHaveProperty("target_time_s");
});

test("sending to the watch posts the export", async () => {
  const f = mock();
  render(Race, { goals: [goal], goalId: goal.id });
  await fireEvent.click(await screen.findByRole("button", { name: "Envoyer à la montre" }));
  expect(calls(f)).toContain("POST /api/goals/7/race-plan/export");
});

const trailGoal: Goal = { ...goal, type: "trail", d_plus_m: 800 };
const station = { km: 5, name: "Ravito Col", kind: "complet" as const, cutoff: "09:30", stop_min: 3 };
const trailView = (): RaceView =>
  view({
    goal_type: "trail",
    profile: [[0, 100], [5, 300], [10, 120]],
    settings: { ...view().settings, carbs_g_h: 60, water_ml_h: 500, aid_stations: [station] },
    guide: guide({
      avg_pace_s_km: null,
      splits: [],
      nutrition: { carbs_g_h: 60, water_ml_h: 500, recommended: false, principle: "Mange régulièrement.", intakes: [] },
      phases: [
        { ...phase("Départ", 0, 5, 0, "09:30"), pace_low_s_km: null, pace_high_s_km: null, hr_zone: "Z2", hr_low: 130, hr_high: 145, terrain: ["Montée km 1.05–4, +200 m"] },
        { ...phase("Cœur de course", 5, 8.5, 0, "10:00"), pace_low_s_km: null, pace_high_s_km: null, hr_zone: "Z3", hr_low: 145, hr_high: 160 },
        { ...phase("Final", 8.5, 10, 0, "10:33"), pace_low_s_km: null, pace_high_s_km: null, hr_zone: "Z3", hr_low: 145, hr_high: 160 },
      ],
    }),
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
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
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
  render(Race, { goals: [goal], goalId: goal.id });
  await screen.findByText("48 min");
  expect(screen.queryByRole("img", { name: /profil/i })).toBeNull();
});

test("adding an aid station flags unsaved changes and is saved with the PUT", async () => {
  const f = mock(trailView());
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
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
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  await fireEvent.change(await screen.findByLabelText("Type du ravitaillement 1"), { target: { value: "eau" } });
  expect(screen.getByLabelText("Arrêt du ravitaillement 1 (min)")).toHaveValue(1);
});

test("removing an aid station marks the page dirty", async () => {
  mock(trailView());
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  await fireEvent.click(await screen.findByRole("button", { name: "Supprimer le ravitaillement 1" }));
  expect(screen.getByText("Modifications non enregistrées")).toBeVisible();
  expect(screen.queryByDisplayValue("Ravito Col")).toBeNull();
});

test("editing the nutrition settings marks the page dirty", async () => {
  mock(trailView());
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  await fireEvent.input(await screen.findByLabelText("Glucides (g/h)"), { target: { value: "70" } });
  expect(screen.getByText("Modifications non enregistrées")).toBeVisible();
});

test("reimporting from the GPX posts to reimport", async () => {
  const f = mock(trailView());
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
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
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  expect(await screen.findAllByText(late)).toHaveLength(2);
  expect(within(screen.getByRole("table", { name: "Nutrition" })).getAllByRole("row")).toHaveLength(4);
});

test("the watch status says whether the sent plan is outdated", async () => {
  mock(view({ workout_id: 12 }));
  const { unmount } = render(Race, { goals: [goal], goalId: goal.id });
  expect(await screen.findByText("Envoyé à la montre")).toBeVisible();
  unmount();
  mock(view({ workout_id: 12, export_stale: true }));
  render(Race, { goals: [goal], goalId: goal.id });
  expect(await screen.findByText("Plan modifié depuis l'envoi : renvoie-le à la montre")).toBeVisible();
  expect(screen.queryByText("Envoyé à la montre")).toBeNull();
});

test("refreshing is disabled while the draft has unsaved changes", async () => {
  mock();
  render(Race, { goals: [goal], goalId: goal.id });
  const refresh = await screen.findByRole("button", { name: "Actualiser" });
  expect(refresh).toBeEnabled();
  await fireEvent.input(screen.getByLabelText("Heure de départ"), { target: { value: "09:00" } });
  expect(refresh).toBeDisabled();
});

test("an emptied aid station km blocks saving with a French message", async () => {
  const f = mock(trailView());
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  await fireEvent.input(await screen.findByLabelText("Km du ravitaillement 1"), { target: { value: "" } });
  expect(screen.getByRole("alert")).toHaveTextContent("Ravitaillement 1");
  const save = screen.getByRole("button", { name: "Enregistrer" });
  expect(save).toBeDisabled();
  await fireEvent.click(save);
  expect(calls(f).some((c) => c.startsWith("PUT"))).toBe(false);
});

test("a new aid station stays before the finish", async () => {
  const f = mock(trailView());
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  await fireEvent.click(await screen.findByRole("button", { name: "Ajouter un ravitaillement" }));
  expect(screen.getByLabelText("Km du ravitaillement 2")).toHaveValue(9.9);
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(calls(f)).toContain("PUT /api/goals/7/race-plan");
});

test("the trail header labels the elevation gain as computed from the profile", async () => {
  mock(trailView());
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  expect(await screen.findByText("D+ (profil)")).toBeVisible();
});

test("change d'objectif dans le sélecteur Jour J", async () => {
  const other: Goal = { ...goal, id: 8, type: "trail", distance_km: 20, d_plus_m: 800, race_date: "2027-01-17", priority: "plaisir" };
  const f = vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.includes("/goals/8/") ? view({ goal_id: 8, race_date: "2027-01-17" }) : view()), { status: 200 }));
  vi.stubGlobal("fetch", f);
  render(Race, { goals: [goal, other], goalId: 7 });
  const select = (await screen.findByLabelText("Objectif")) as HTMLSelectElement;
  expect(select.value).toBe("7");
  expect([...select.options].map((o) => o.textContent)).toEqual([
    "Course sur route de 10 km · 6 décembre 2026 (Principal)",
    "Trail de 20 km · 17 janvier 2027 (Plaisir)",
  ]);
  await fireEvent.change(select, { target: { value: "8" } });
  await waitFor(() => expect(calls(f as never)).toContain("GET /api/goals/8/race-plan"));
  expect(await screen.findByText("17 janv. 2027")).toBeVisible();
});

test("an horizon goal without a time says it will be estimated with its cycle", async () => {
  const far: Goal = { ...goal, race_date: "2027-04-11" };
  const v = view({ plan: { ...view().plan, reference_time_s: null, warnings: ["Pas de temps de référence : fixe un temps visé sur l'objectif"] } });
  mock(v);
  render(Race, { goals: [far], goalId: far.id, cycle });
  expect(await screen.findByText("Temps estimé à la préparation de son cycle, ou fixe un temps visé")).toBeVisible();
  expect(screen.queryByText(/Pas de temps de référence/)).toBeNull();
  expect(screen.queryByText("Pas de temps visé")).toBeNull();
});

test("a goal edit that leaves the plan to update goes to the goals page and its banner", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) =>
      new Response(
        JSON.stringify(
          init?.method === "PATCH" ? { goal, proposal_id: null, needs_generation: false, adjust_due: true } : view(),
        ),
        { status: 200 },
      ),
    ),
  );
  location.hash = "#/race";
  render(Race, { goals: [goal], goalId: goal.id });
  await fireEvent.click(await screen.findByRole("button", { name: "Modifier l'objectif" }));
  const dialog = screen.getByRole("dialog", { name: "Modifier l'objectif" });
  await fireEvent.input(within(dialog).getByLabelText("Date de la course"), { target: { value: "2026-12-13" } });
  await fireEvent.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(location.hash).toBe("#/goal"));
});
