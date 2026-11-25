import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Week from "./Week.svelte";
import { api, type CoachEvent, type Cycle, type Goal, type Plan, type Session, type Status, type Zones } from "../lib/api";
import { addDays } from "../lib/dates";
import { loadZones, resetZones } from "../lib/zones.svelte";

afterEach(() => {
  vi.unstubAllGlobals();
  location.hash = "";
  resetZones();
});

const s = (id: number, title: string, suggested_day: Session["suggested_day"], status: Session["status"], type = "seuil"): Session => ({
  id, order: id, type, title, description: "", target_kind: "pace", status, suggested_day,
  sport: "run", scheduled_date: null, chaining_note: null, sync_error: null,
  steps: [{ kind: "warmup", duration_s: 1200, zone: "EF" }, { kind: "active", duration_s: 1800, zone: "seuil" }],
});

const cycle: Cycle = {
  id: 1, status: "active", plan_start: "2026-10-26", end_date: "2026-12-06", sessions_per_week: 3,
  available_days: ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"], long_run_day: null,
  include_bike: false, plan_accepted: true, needs_generation: false, adjust_due: false,
};
const goal: Goal = {
  id: 1, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2026-12-06", priority: "principal", status: "active",
  gpx_summary: null, target_time_s: null, target_source: null,
};

const plan: Plan = {
  cycle,
  goals: [goal],
  horizon: [],
  open_injury: null,
  weeks: [
    { week_index: 1, week_monday: "2026-10-26", sessions: [s(1, "Endurance 50 min", "lundi", "done", "EF"), s(2, "Seuil 3 × 10 min", "vendredi", "todo")] },
    { week_index: 2, week_monday: "2026-11-02", sessions: [s(3, "VMA 6 × 1 min", "mardi", "todo", "VMA"), s(4, "Sortie longue 1 h 30", "dimanche", "todo", "sortie_longue")] },
  ],
};

const event: CoachEvent = {
  id: 3, kind: "unavailable", start_date: "2026-11-05", end_date: "2026-11-08", max_sessions: null, days: null,
  session_id: null, note: null,
};

function mock(body: Plan = plan) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.startsWith("/api/plan") ? body : []), { status: 200 })));
}

const focus = () => screen.getByRole("region", { name: "Séance sélectionnée" });

// --- la séance mise en avant -----------------------------------------------------------------

test("today's session is the focus, with its single main action", async () => {
  mock();
  render(Week, { today: "2026-10-30" });
  expect(await screen.findByRole("heading", { name: "Ma semaine", level: 1 })).toBeVisible();
  const card = await screen.findByRole("region", { name: "Séance sélectionnée" });
  expect(within(card).getByRole("heading", { name: "Seuil 3 × 10 min" })).toBeVisible();
  expect(within(card).getByText(/^Aujourd'hui · Vendredi 30 octobre/)).toBeVisible();
  expect(within(card).getByRole("button", { name: "Envoyer sur la montre" })).toBeVisible();
  expect(screen.getByText("J-37")).toBeVisible();
  expect(screen.getAllByText("Repos")).toHaveLength(5);
});

test("on a rest day the next session of the week is shown", async () => {
  mock();
  render(Week, { today: "2026-10-28" });
  expect(await within(await screen.findByRole("region", { name: "Séance sélectionnée" })).findByRole("heading", { name: "Seuil 3 × 10 min" })).toBeVisible();
});

test("once the week is over, it says so and offers the next week", async () => {
  mock();
  render(Week, { today: "2026-10-31" });
  expect(await screen.findByRole("heading", { name: "Repos aujourd'hui" })).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: "Voir la semaine suivante" }));
  expect(screen.getByRole("heading", { name: "Semaine prochaine" })).toBeVisible();
  expect(within(focus()).getByRole("heading", { name: "VMA 6 × 1 min" })).toBeVisible();
});

test("clicking a day of the week puts its session in focus", async () => {
  mock();
  render(Week, { today: "2026-10-30" });
  await fireEvent.click(await screen.findByRole("button", { name: /Endurance 50 min/ }));
  expect(within(focus()).getByRole("heading", { name: "Endurance 50 min" })).toBeVisible();
  expect(screen.getByRole("button", { name: /Endurance 50 min/ })).toHaveAttribute("aria-pressed", "true");
});

// --- navigation entre les semaines ------------------------------------------------------------

test("the arrows and the timeline move through the weeks", async () => {
  mock();
  render(Week, { today: "2026-10-30" });
  expect(await screen.findByRole("heading", { name: "Cette semaine" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Semaine précédente" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Revenir à cette semaine" })).toBeNull();

  await fireEvent.click(screen.getByRole("button", { name: "Semaine suivante" }));
  expect(screen.getByRole("heading", { name: "Semaine prochaine" })).toBeVisible();
  expect(screen.getByText(/2 – 8 nov\./)).toBeVisible();
  expect(screen.getByRole("button", { name: /VMA 6 × 1 min/ })).toBeVisible();
  expect(screen.getByRole("button", { name: "Semaine suivante" })).toBeDisabled();
  // autre semaine : sa première séance à faire est mise en avant
  expect(within(focus()).getByRole("heading", { name: "VMA 6 × 1 min" })).toBeVisible();

  await fireEvent.click(screen.getByRole("button", { name: "Revenir à cette semaine" }));
  expect(screen.getByRole("heading", { name: "Cette semaine" })).toBeVisible();

  const timeline = screen.getByRole("group", { name: "Aller à une semaine du plan" });
  await fireEvent.click(within(timeline).getByRole("button", { name: "Semaine 2" }));
  expect(within(timeline).getByRole("button", { name: "Semaine 2" })).toHaveAttribute("aria-current", "true");
  expect(screen.getByRole("heading", { name: "Semaine prochaine" })).toBeVisible();
});

test("the week summary counts the sessions done", async () => {
  mock();
  render(Week, { today: "2026-10-30" });
  const summary = await screen.findByRole("region", { name: "Bilan de la semaine" });
  expect(summary).toHaveTextContent("Semaine 1 sur 2");
  expect(summary).toHaveTextContent("1/2 séances faites");
});

const zones: Zones = { pace: { EF: [340, 380] }, hr: {}, source: [] };

/** Bilan d'une semaine à une seule séance ; `trail` : sorties de /api/activities/trail (null : erreur 500). */
async function summaryOf(over: Partial<Session>, z: Zones | null = zones, trail: object[] | null = []) {
  const session: Session = { ...s(1, "Séance", "vendredi", "todo"), steps: [{ kind: "active", duration_s: 3600, zone: "EF" }], ...over };
  const body: Plan = { ...plan, weeks: [{ ...plan.weeks[0], sessions: [session] }] };
  const fetched = vi.fn(async (url: string) => {
    if (url.startsWith("/api/activities/trail") && !trail) return new Response("{}", { status: 500 });
    const data = url.startsWith("/api/plan") ? body : url.startsWith("/api/zones") ? z
      : url.startsWith("/api/activities/trail") ? trail : [];
    return new Response(JSON.stringify(data), { status: 200 });
  });
  vi.stubGlobal("fetch", fetched);
  await loadZones();
  render(Week, { today: "2026-10-30" });
  return { summary: await screen.findByRole("region", { name: "Bilan de la semaine" }), fetched };
}

test("le bilan estime les km et le D+ de la semaine", async () => {
  const { summary } = await summaryOf({ d_plus_m: 450 });
  expect(summary).toHaveTextContent("≈ 10 km · ≈ 450 m D+");
});

test("sans D+ au programme, seuls les km s'affichent et les sorties ne sont pas lues", async () => {
  const { summary, fetched } = await summaryOf({ target_kind: "hr" });
  expect(summary).toHaveTextContent("≈ 10 km");
  expect(summary).not.toHaveTextContent("D+");
  expect(fetched.mock.calls.some(([url]) => url.startsWith("/api/activities/trail"))).toBe(false);
});

test("sans zones, le D+ reste affiché sans km", async () => {
  const { summary } = await summaryOf({ d_plus_m: 450 }, null);
  expect(summary).toHaveTextContent("≈ 450 m D+");
  expect(summary).not.toHaveTextContent("km");
});

test("une séance en FC avec D+ suit l'allure des sorties trail", async () => {
  const outing = { date: addDays("2026-10-30", -5), duration_s: 3600, distance_m: 8000 };
  const { summary } = await summaryOf({ target_kind: "hr", d_plus_m: 450 }, zones, [outing]);
  await waitFor(() => expect(summary).toHaveTextContent("≈ 8 km · ≈ 450 m D+"));
});

test("sorties illisibles : le bilan reste affiché, sans erreur", async () => {
  const { summary, fetched } = await summaryOf({ target_kind: "hr", d_plus_m: 450 }, zones, null);
  await waitFor(() => expect(fetched.mock.calls.some(([url]) => url.startsWith("/api/activities/trail"))).toBe(true));
  await new Promise((r) => setTimeout(r));
  expect(summary).toHaveTextContent("≈ 10 km · ≈ 450 m D+");
  expect(summary).toHaveTextContent("0/1 séances faites");
  expect(screen.queryByRole("alert")).toBeNull();
});

test("une semaine de vélo n'affiche ni km ni D+", async () => {
  const { summary } = await summaryOf({ sport: "bike", d_plus_m: 450 });
  expect(summary).not.toHaveTextContent("≈");
});

test("la dernière activité ignore une sortie d'une autre semaine rattachée à une séance", async () => {
  const before = {
    id: 9, date: "2026-10-25", type_key: "running", duration_s: 2580, distance_m: 10000, d_plus_m: 0,
    avg_hr: 162, session_id: 1, match_source: "auto",
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.startsWith("/api/plan") ? plan : url.startsWith("/api/activities") ? [before] : []), { status: 200 })));
  render(Week, { today: "2026-10-30" });
  // la séance du lundi retrouve sa sortie du dimanche précédent (activités chargées)
  await fireEvent.click(await screen.findByRole("button", { name: /Endurance 50 min/ }));
  expect(await within(focus()).findByText(/dim\. 25\/10/)).toBeVisible();
  const card = screen.getByRole("region", { name: "Dernière activité" });
  expect(within(card).getByText("Aucune activité cette semaine.")).toBeVisible();
});

// --- propositions et imprévus -----------------------------------------------------------------

test("a pending proposal shows as a banner linking to it", async () => {
  mock();
  const status = { pending_proposal_id: 7 } as Status;
  render(Week, { today: "2026-10-30", status });
  const banner = await screen.findByRole("link", { name: /Claude propose des changements/ });
  expect(banner).toHaveAttribute("href", "#/proposal");
});

test("without a pending proposal, no banner", async () => {
  mock();
  render(Week, { today: "2026-10-30", status: { pending_proposal_id: null } as Status });
  await screen.findByRole("region", { name: "Séance sélectionnée" });
  expect(screen.queryByRole("link", { name: /Claude propose/ })).toBeNull();
});

test("Signaler un imprévu opens the event dialog", async () => {
  mock();
  render(Week, { today: "2026-10-30" });
  await fireEvent.click(await screen.findByRole("button", { name: "Signaler un imprévu" }));
  expect(screen.getByRole("dialog", { name: "Signaler un imprévu" })).toBeVisible();
});

const injury: CoachEvent = {
  id: 4, kind: "injury", start_date: "2026-11-01", end_date: null, max_sessions: null, days: null,
  session_id: null, note: null,
};

/** `resumed` : après la reprise, le plan n'a plus d'arrêt ouvert et l'imprévu est clos. */
function mockInjury(opts: { injury: boolean }) {
  let resumed = false;
  const f = vi.fn(async (url: string) => {
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (url === "/api/plan") return json({ ...plan, open_injury: opts.injury && !resumed ? injury : null });
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
const planCalls = (f: ReturnType<typeof mockInjury>) => f.mock.calls.filter((c) => c[0] === "/api/plan").length;

test("the injury banner shows for an open injury and not otherwise", async () => {
  mockInjury({ injury: true });
  const { unmount } = render(Week, { today: "2026-11-03" });
  expect(await screen.findByText("Arrêt depuis le 01/11")).toBeVisible();
  unmount();
  mockInjury({ injury: false });
  render(Week, { today: "2026-11-03" });
  await screen.findByRole("heading", { name: "Ma semaine" });
  await waitFor(() => expect(screen.queryByText(/Arrêt depuis/)).toBeNull());
});

test("resuming reloads the plan, clears the list and goes to the proposal", async () => {
  const f = mockInjury({ injury: true });
  render(Week, { today: "2026-11-03" });
  await screen.findByText(/Blessure \/ maladie · depuis le 01\/11/);
  const before = planCalls(f);
  await fireEvent.click(await screen.findByRole("button", { name: "Signaler la reprise" }));
  await fireEvent.click(screen.getByRole("button", { name: "Confirmer la reprise" }));
  await waitFor(() => expect(location.hash).toBe("#/proposal"));
  await waitFor(() => expect(planCalls(f)).toBeGreaterThan(before));
  await waitFor(() => expect(screen.queryByText(/Arrêt depuis/)).toBeNull());
  await waitFor(() => expect(screen.queryByRole("button", { name: "Supprimer" })).toBeNull());
});

// --- états du cycle ---------------------------------------------------------------------------

test("without a cycle, the page invites to create a goal", async () => {
  mock({ cycle: null, goals: [], horizon: [], open_injury: null, weeks: [] });
  render(Week, { today: "2026-11-03" });
  expect(await screen.findByRole("link", { name: "Créer un objectif" })).toHaveAttribute("href", "#/goal");
});

test("a draft cycle sends back to the draft", async () => {
  mock({ ...plan, cycle: { ...cycle, plan_accepted: false } });
  render(Week, { today: "2026-11-03" });
  expect(await screen.findByRole("link", { name: "Relire le brouillon" })).toBeVisible();
});

test("plan à recalculer : le plan précédent reste affiché, en lecture seule, avec Générer", async () => {
  let generated = false;
  const stale: Plan = { ...plan, cycle: { ...cycle, plan_accepted: false, needs_generation: true } };
  const f = vi.fn(async (url: string, _init?: RequestInit) => {
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (url === "/api/cycle/generate") {
      generated = true;
      return json({ summary: "ok", weeks: 6 });
    }
    if (url === "/api/plan") return json(generated ? { ...stale, cycle: { ...cycle, plan_accepted: false } } : stale);
    return json([]);
  });
  vi.stubGlobal("fetch", f);
  render(Week, { today: "2026-10-30" });
  const banner = await screen.findByRole("region", { name: "Plan à recalculer" });
  expect(banner).toHaveTextContent("Le plan doit être recalculé");
  expect(screen.queryByRole("link", { name: "Relire le brouillon" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Signaler un imprévu" })).toBeNull();
  expect(within(focus()).getByRole("heading", { name: "Seuil 3 × 10 min" })).toBeVisible();
  expect(within(focus()).queryByRole("button", { name: "Envoyer sur la montre" })).toBeNull();
  await fireEvent.click(within(banner).getByRole("button", { name: "Générer" }));
  await waitFor(() => expect(f.mock.calls.some(([u, i]) => u === "/api/cycle/generate" && i?.method === "POST")).toBe(true));
  expect(await screen.findByRole("link", { name: "Relire le brouillon" })).toBeVisible();
});

test("plan à recalculer sans séance : renvoie aux objectifs", async () => {
  mock({ ...plan, cycle: { ...cycle, plan_accepted: false, needs_generation: true }, weeks: [{ week_index: 1, week_monday: "2026-10-26", sessions: [] }] });
  render(Week, { today: "2026-11-03" });
  expect(await screen.findByRole("link", { name: "Relire le brouillon" })).toBeVisible();
  expect(screen.queryByRole("region", { name: "Plan à recalculer" })).toBeNull();
});

// --- courses ----------------------------------------------------------------------------------

const secondary: Goal = { ...goal, id: 2, type: "trail", distance_km: 20, d_plus_m: 800, race_date: "2026-12-05", priority: "secondaire" };
const later: Goal = { ...goal, id: 3, distance_km: 10, race_date: "2027-03-14", priority: "plaisir" };

test("montre une carte Course le jour d'un objectif, et la semaine de course dans la frise", async () => {
  mock({ ...plan, goals: [secondary, goal], weeks: [{ week_index: 6, week_monday: "2026-11-30", sessions: [] }] });
  render(Week, { today: "2026-12-01" });
  const races = await screen.findAllByRole("note", { name: /^Course/ });
  expect(races).toHaveLength(2);
  expect(races[0]).toHaveTextContent("Trail de 20 km");
  expect(races[0]).toHaveTextContent("Secondaire");
  expect(races[1]).toHaveTextContent("Course sur route de 21,1 km");
  expect(screen.getByRole("button", { name: "Semaine 6 (course)" })).toBeVisible();
});

test("la semaine est au-dessus du détail de la séance, sans liste Ensuite", async () => {
  mock({ ...plan, horizon: [later] });
  render(Week, { today: "2026-10-30" });
  const week = await screen.findByRole("region", { name: "Cette semaine" });
  expect(week.compareDocumentPosition(focus()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByRole("region", { name: "Ensuite" })).toBeNull();
});

test("goals changed on the accepted plan: the update banner leads to the proposal", async () => {
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
    if (init?.method === "POST" && url === "/api/cycle/adjust") return json({ proposal_id: 12 });
    return json(url === "/api/plan" ? { ...plan, cycle: { ...cycle, adjust_due: true } } : []);
  });
  vi.stubGlobal("fetch", f);
  render(Week, { today: "2026-10-30" });
  const banner = await screen.findByRole("region", { name: "Plan à mettre à jour" });
  await fireEvent.click(within(banner).getByRole("button", { name: "Mettre à jour l'entraînement" }));
  await waitFor(() => expect(location.hash).toBe("#/proposal"));
});

test("nothing pending: no update banner", async () => {
  mock();
  render(Week, { today: "2026-10-30" });
  await screen.findByRole("region", { name: "Séance sélectionnée" });
  expect(screen.queryByRole("region", { name: "Plan à mettre à jour" })).toBeNull();
});

// --- cache et lectures parallèles -------------------------------------------------------------

const ok = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
const run = (id: number, date: string, session_id: number | null) => ({
  id, date, type_key: "running", duration_s: 2640, distance_m: 8300, d_plus_m: 0, avg_hr: 139, session_id, match_source: "auto",
});
const urls = (prefix: string) => vi.mocked(fetch).mock.calls.map((c) => String(c[0])).filter((u) => u.startsWith(prefix));
const settle = () => new Promise((r) => setTimeout(r, 20));

test("Week : retour sur la page, plan affiché sans attendre", async () => {
  mock();
  const first = render(Week, { today: "2026-10-30" });
  await screen.findByRole("heading", { name: "Cette semaine" });
  first.unmount();
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  render(Week, { today: "2026-10-30" });
  await Promise.resolve();
  expect(screen.getByRole("heading", { name: "Cette semaine" })).toBeVisible();
  expect(screen.queryByText("Chargement…")).toBeNull();
});

test("Week : /plan et /cycle/events partent ensemble", async () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
  render(Week, { today: "2026-10-30" });
  await settle();
  expect(urls("/api").sort()).toEqual(["/api/cycle/events", "/api/plan"]);
});

test.each(["events", "plan"])("Week : une seule lecture /cycle/events par affichage (%s répond d'abord)", async (first) => {
  let release = () => {};
  const held = new Promise<void>((r) => (release = r));
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.startsWith("/api/plan") !== (first === "plan")) await held;
    const body = url.startsWith("/api/plan") ? plan : url === "/api/cycle/events" ? [event] : [];
    return new Response(JSON.stringify(body), { status: 200 });
  }));
  const view = render(Week, { today: "2026-10-30", version: 0 });
  await settle();
  release();
  await screen.findByText(/Indisponible/);
  await settle();
  expect(urls("/api/cycle/events")).toHaveLength(1);
  await view.rerender({ version: 1 });
  await settle();
  expect(urls("/api/cycle/events")).toHaveLength(2);
  view.unmount();
  render(Week, { today: "2026-10-30" }); // retour sur la page : liste affichée sans attendre
  await Promise.resolve();
  expect(screen.getByText(/Indisponible/)).toBeVisible();
  await settle();
  expect(urls("/api/cycle/events")).toHaveLength(3);
});

test("Week : imprévu supprimé, liste et plan relus une fois", async () => {
  let list = [event];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") list = [];
    const body = url.startsWith("/api/plan") ? plan : url === "/api/cycle/events" ? list : [];
    return new Response(JSON.stringify(body), { status: 200 });
  }));
  render(Week, { today: "2026-10-30" });
  await fireEvent.click(await screen.findByRole("button", { name: "Supprimer" }));
  await screen.findByText("Recalculer le plan ?");
  await waitFor(() => expect(screen.queryByText(/Indisponible/)).toBeNull());
  await settle();
  expect(urls("/api/cycle/events")).toHaveLength(2);
  expect(urls("/api/plan")).toHaveLength(2);
});

test("Week : imprévus illisibles, l'erreur est affichée et le plan reste", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url === "/api/cycle/events"
      ? new Response(JSON.stringify({ detail: "Imprévus illisibles" }), { status: 500 })
      : new Response(JSON.stringify(url.startsWith("/api/plan") ? plan : []), { status: 200 })));
  render(Week, { today: "2026-10-30" });
  expect(await screen.findByText("Imprévus illisibles")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Cette semaine" })).toBeVisible();
});

test("Week : une seule lecture /activities par affichage", async () => {
  mock();
  const view = render(Week, { today: "2026-10-30", version: 0 });
  await screen.findByRole("heading", { name: "Cette semaine" });
  await settle();
  expect(urls("/api/activities")).toEqual(["/api/activities?week=1"]);
  await view.rerender({ version: 1 });
  await settle();
  expect(urls("/api/plan")).toHaveLength(2);
  expect(urls("/api/activities")).toHaveLength(2);
  view.unmount();
  // retour sur la page : plan en cache puis relu, toujours une seule lecture
  render(Week, { today: "2026-10-30", version: 1 });
  await settle();
  expect(urls("/api/activities")).toHaveLength(3);
  expect(urls("/api/plan")).toHaveLength(3);
});

test("Week : changement rapide de semaine, la réponse tardive ne s'affiche pas", async () => {
  const late: ((r: Response) => void)[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url === "/api/plan") return Promise.resolve(ok(plan));
    if (url === "/api/activities?week=2") return new Promise<Response>((r) => late.push(r));
    if (url === "/api/activities?week=1") return Promise.resolve(ok([run(9, "2026-10-27", 1)]));
    return Promise.resolve(ok([]));
  }));
  render(Week, { today: "2026-10-30" });
  const card = await screen.findByRole("region", { name: "Dernière activité" });
  await within(card).findByText(/27\/10/);
  await fireEvent.click(screen.getByRole("button", { name: "Semaine suivante" }));
  await waitFor(() => expect(late).toHaveLength(1));
  await fireEvent.click(screen.getByRole("button", { name: "Revenir à cette semaine" }));
  late[0](ok([run(10, "2026-10-29", null)]));
  await settle();
  const again = screen.getByRole("region", { name: "Dernière activité" });
  expect(within(again).getByText(/27\/10/)).toBeVisible();
  expect(within(again).queryByText(/29\/10/)).toBeNull();
});

test("Week : séance rattachée pendant une relecture, l'ancienne réponse n'écrase pas l'affichage", async () => {
  let body = plan;
  let hold = false;
  const waiting: (() => void)[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "POST") return Promise.resolve(ok({ status: "ok" }));
    if (url !== "/api/plan") return Promise.resolve(ok([]));
    const answer = body; // état de la base au départ de la lecture
    if (!hold) return Promise.resolve(ok(answer));
    return new Promise<Response>((r) => waiting.push(() => r(ok(answer))));
  }));
  const view = render(Week, { today: "2026-10-30", version: 0 });
  expect(await screen.findByRole("region", { name: "Bilan de la semaine" })).toHaveTextContent("1/2");
  hold = true;
  await view.rerender({ version: 1 });
  await waitFor(() => expect(waiting).toHaveLength(1));
  const [w1, w2] = plan.weeks;
  body = { ...plan, weeks: [{ ...w1, sessions: w1.sessions.map((x) => ({ ...x, status: "done" })) }, w2] };
  hold = false;
  await api.match(9, 2);
  waiting[0]();
  await waitFor(() => expect(screen.getByRole("region", { name: "Bilan de la semaine" })).toHaveTextContent("2/2"));
});

test("Week : après une action, les activités sont relues avec le plan", async () => {
  mockInjury({ injury: true });
  render(Week, { today: "2026-11-03" });
  await screen.findByText("Arrêt depuis le 01/11");
  await waitFor(() => expect(urls("/api/activities")).toHaveLength(1));
  await fireEvent.click(screen.getByRole("button", { name: "Signaler la reprise" }));
  await fireEvent.click(screen.getByRole("button", { name: "Confirmer la reprise" }));
  await waitFor(() => expect(urls("/api/activities")).toHaveLength(2));
});

test("Week : relecture en échec, l'ancien plan reste affiché avec l'erreur", async () => {
  mock();
  const first = render(Week, { today: "2026-10-30" });
  await screen.findByRole("heading", { name: "Cette semaine" });
  first.unmount();
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "x", detail: "Base coupée" }), { status: 503 })));
  render(Week, { today: "2026-10-30" });
  expect((await screen.findAllByText("Base coupée")).length).toBeGreaterThan(0);
  expect(screen.getByRole("heading", { name: "Cette semaine" })).toBeVisible();
});
