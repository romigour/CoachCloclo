import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.svelte";
import { load } from "./lib/cache";

const calls: { url: string; method: string }[] = [];
let syncDone: (() => void) | null = null;
let statusBody: Record<string, unknown> = {};
let statsCalls = 0;
let syncInstant = false;
let syncFails = false;
let syncResent = 0;
let syncChanged = true;
let garminBody = "ok"; // réponse de GET /api/garmin/state
let garminGate: Promise<unknown> | null = null; // retient cette réponse
let setupGate: Promise<unknown> | null = null; // retient celle de /api/setup/status
let phase: string | null = null;
let afterSync: (() => void) | null = null;
let setupBody: Record<string, unknown> | null = null; // null : 404, comme sous `coach start`

const idle = { status: "idle", imported: 0, error: null, total: 0, finished_at: null };

const cycle = {
  id: 1, status: "active", plan_start: "2026-11-09", end_date: "2027-02-07", sessions_per_week: 3,
  available_days: ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"], long_run_day: null,
  include_bike: false, plan_accepted: true, needs_generation: false,
};
const goal = {
  id: 1, type: "route", distance_km: 21, d_plus_m: 0, race_date: "2027-02-07", priority: "principal", status: "active",
  target_time_s: null, target_source: null, gpx_summary: null,
};
const noGoal = { cycle: null, goals: [], next_goal: null };

const plan = { cycle, goals: [goal], horizon: [], open_injury: null, weeks: [] };

beforeEach(() => {
  calls.length = 0;
  statsCalls = 0;
  syncInstant = false;
  syncFails = false;
  syncResent = 0;
  syncChanged = true;
  garminBody = "ok";
  garminGate = setupGate = null;
  phase = null;
  syncDone = null;
  afterSync = null;
  setupBody = null;
  localStorage.clear();
  statusBody = { llm_mode: "cli", pending_proposal_id: null, cycle, goals: [goal], next_goal: goal, has_activities: false, history: idle };
  location.hash = "";
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    let body: unknown = {};
    if (url === "/api/setup/status") {
      await setupGate;
      if (!setupBody) return new Response(JSON.stringify({ code: "not_found", detail: "Not Found" }), { status: 404 });
      body = setupBody;
    }
    else if (url === "/api/status") body = statusBody;
    else if (url === "/api/garmin/state") {
      await garminGate;
      if (garminBody === "échec") return new Response("{}", { status: 500 });
      body = { garmin: garminBody };
    }
    else if (url === "/api/sync/phase") body = { phase };
    else if (url === "/api/stats/activities") { statsCalls++; body = { activities: [] }; }
    else if (url === "/api/stats/records") body = { records: [] };
    else if (url === "/api/plan") body = plan;
    else if (url === "/api/cycle/events") body = [];
    else if (url === "/api/settings") body = { llm_mode: "cli", anthropic_model: null, anthropic_api_key_set: false };
    else if (url === "/api/garmin/login") body = { status: "ok" };
    else if (url === "/api/sync") {
      if (!syncInstant) await new Promise<void>((r) => (syncDone = r));
      if (syncFails) return new Response(JSON.stringify({ code: "garmin_unavailable", detail: "Garmin coupé" }), { status: 503 });
      afterSync?.();
      body = { new_activities: 0, matched: 0, missed: 0, proposal_id: null, resent: syncResent, hr_rest: 44, changed: syncChanged };
    }
    return new Response(JSON.stringify(body), { status: 200 });
  }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const syncs = () => calls.filter((c) => c.url === "/api/sync" && c.method === "POST").length;

test("auto-sync runs once per load and survives navigation", async () => {
  location.hash = "#/week";
  render(App);
  await waitFor(() => expect(syncs()).toBe(1));
  syncDone!();
  await screen.findByText(/Dernière synchro/);

  location.hash = "#/goal";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await screen.findByText("Objectifs", { selector: "h1" });
  location.hash = "#/week";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await screen.findByText("Ma semaine", { selector: "h1" });
  await new Promise((r) => setTimeout(r, 50));
  expect(syncs()).toBe(1);
});

test("default route is the week when the plan is accepted, even with activities", async () => {
  statusBody = { ...statusBody, has_activities: true };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
  syncDone?.();
});

test("default route is stats when activities exist without an accepted plan", async () => {
  statusBody = { ...statusBody, has_activities: true, cycle: { ...cycle, plan_accepted: false } };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/stats"));
  syncDone?.();
});

test("default route is the goal without plan nor activities", async () => {
  statusBody = { ...statusBody, ...noGoal };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/goal"));
  syncDone?.();
});

test("auto-sync runs without a goal, without any banner", async () => {
  statusBody = { ...statusBody, ...noGoal };
  render(App);
  await waitFor(() => expect(syncs()).toBe(1));
  expect(screen.queryByText("Synchronisation Garmin…")).toBeNull();
  syncDone!();
});

test("polls status while history runs, stops when done, and reloads the stats", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, has_activities: true, history: { status: "running", imported: 3, error: null, total: 0, finished_at: null } };
  location.hash = "#/stats";
  vi.useFakeTimers();
  const { unmount } = render(App);
  await vi.advanceTimersByTimeAsync(100);
  expect(screen.getByText("Import de l'historique en cours… (3 nouvelles)")).toBeTruthy();
  const baseline = statsCalls;
  const statusCalls = () => calls.filter((c) => c.url === "/api/status").length;
  const before = statusCalls();

  statusBody = { ...statusBody, history: { status: "done", imported: 9, error: null, total: 0, finished_at: null } };
  await vi.advanceTimersByTimeAsync(5000);
  expect(statusCalls()).toBe(before + 1);
  expect(statsCalls).toBe(baseline + 1); // import terminé : activités rechargées

  await vi.advanceTimersByTimeAsync(15000);
  expect(statusCalls()).toBe(before + 1); // sondage arrêté
  unmount();
});

test("status polling is cleaned up on unmount", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, history: { status: "running", imported: 0, error: null, total: 0, finished_at: null } };
  location.hash = "#/stats";
  vi.useFakeTimers();
  const { unmount } = render(App);
  await vi.advanceTimersByTimeAsync(100);
  unmount();
  const before = calls.filter((c) => c.url === "/api/status").length;
  await vi.advanceTimersByTimeAsync(20000);
  expect(calls.filter((c) => c.url === "/api/status").length).toBe(before);
});

async function loginToGarmin() {
  await screen.findByLabelText("E-mail Garmin");
  await fireEvent.input(screen.getByLabelText("E-mail Garmin"), { target: { value: "a@b.c" } });
  await fireEvent.input(screen.getByLabelText("Mot de passe"), { target: { value: "secret" } });
  await fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
}

test("first Garmin login syncs, then opens stats once activities exist", async () => {
  syncInstant = true;
  garminBody = "auth_required";
  statusBody = { ...statusBody, ...noGoal };
  location.hash = "#/setup";
  render(App);
  await screen.findByLabelText("E-mail Garmin");
  expect(syncs()).toBe(0);
  garminBody = "ok";
  afterSync = () => (statusBody = { ...statusBody, has_activities: true });
  await loginToGarmin();
  await waitFor(() => expect(syncs()).toBe(1));
  await waitFor(() => expect(location.hash).toBe("#/stats"));
});

test("first Garmin login without any activity after sync goes to the goal", async () => {
  syncInstant = true;
  garminBody = "auth_required";
  statusBody = { ...statusBody, ...noGoal };
  location.hash = "#/setup";
  render(App);
  await screen.findByLabelText("E-mail Garmin"); // formulaire affiché tant que Garmin n'est pas connecté
  garminBody = "ok";
  await loginToGarmin();
  await waitFor(() => expect(syncs()).toBe(1));
  await waitFor(() => expect(location.hash).toBe("#/goal"));
});

test("a failed sync after the first Garmin login stays on settings with its error", async () => {
  syncInstant = true;
  syncFails = true;
  garminBody = "auth_required";
  statusBody = { ...statusBody, ...noGoal };
  location.hash = "#/setup";
  await new Promise((r) => setTimeout(r, 0)); // laisse passer le hashchange initial (il efface l'erreur)
  render(App);
  await screen.findByLabelText("E-mail Garmin"); // formulaire affiché tant que Garmin n'est pas connecté
  garminBody = "ok";
  await loginToGarmin();
  await waitFor(() => expect(syncs()).toBe(1));
  await screen.findByText("Garmin est indisponible pour le moment, réessaie plus tard.");
  await new Promise((r) => setTimeout(r, 0)); // un éventuel hashchange effacerait l'erreur
  expect(screen.getByText("Garmin est indisponible pour le moment, réessaie plus tard.")).toBeTruthy();
  expect(location.hash).toBe("#/setup");
});

test("status polling keeps the error banner", async () => {
  syncInstant = true;
  syncFails = true;
  statusBody = { ...statusBody, has_activities: true, history: { status: "running", imported: 3, error: null, total: 0, finished_at: null } };
  location.hash = "#/stats";
  await new Promise((r) => setTimeout(r, 0)); // laisse passer le hashchange (il efface l'erreur)
  vi.useFakeTimers();
  const { unmount } = render(App);
  await vi.advanceTimersByTimeAsync(100);
  expect(screen.getByText("Garmin est indisponible pour le moment, réessaie plus tard.")).toBeTruthy();
  await vi.advanceTimersByTimeAsync(5000);
  expect(screen.getByText("Garmin est indisponible pour le moment, réessaie plus tard.")).toBeTruthy();
  unmount();
});

test("an import ending in error also reloads the stats", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, has_activities: true, history: { status: "running", imported: 3, error: null, total: 0, finished_at: null } };
  location.hash = "#/stats";
  vi.useFakeTimers();
  const { unmount } = render(App);
  await vi.advanceTimersByTimeAsync(100);
  const baseline = statsCalls;
  statusBody = { ...statusBody, history: { status: "error", imported: 5, error: "Garmin coupé", total: 0, finished_at: null } };
  await vi.advanceTimersByTimeAsync(5000);
  expect(statsCalls).toBe(baseline + 1);
  unmount();
});

const setupOk = { claude_cli: true, claude_auth: true, claude_step: "idle", claude_error: null, garmin: "ok", llm_mode: "cli" };

test("redirige vers l'écran d'accueil si la configuration est incomplète", async () => {
  setupBody = { ...setupOk, claude_cli: false, claude_auth: false };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/welcome"));
  expect(await screen.findByText("CoachCloclo utilise ton abonnement Claude")).toBeTruthy();
});

test("ne montre pas l'écran d'accueil sous coach start (404)", async () => {
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
});

test("pas de lien Connecte Claude sous coach start (404)", async () => {
  syncInstant = true;
  const real = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) =>
    url === "/api/sync"
      ? new Response(JSON.stringify({ code: "llm_unavailable", detail: "Claude n'est pas connecté" }), { status: 503 })
      : real(url, init)));
  location.hash = "#/week";
  render(App);
  await screen.findByText("Claude n'est pas connecté");
  expect(screen.queryByRole("link", { name: "Connecte Claude" })).toBeNull();
});

test("revient à l'étape Garmin quand la connexion Garmin a expiré", async () => {
  setupBody = { ...setupOk, garmin: "auth_required" };
  garminBody = "auth_required";
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/welcome"));
  expect(await screen.findByLabelText("E-mail Garmin")).toBeTruthy();
});

test("l'écran d'accueil s'affiche même si /api/status échoue", async () => {
  setupBody = { ...setupOk, claude_auth: false };
  const real = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) =>
    url === "/api/status" ? new Response("{}", { status: 500 }) : real(url, init)));
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/welcome"));
});

test("propose Connecte Claude quand la génération échoue faute de Claude", async () => {
  setupBody = { ...setupOk };
  syncInstant = true;
  const real = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) =>
    url === "/api/sync"
      ? new Response(JSON.stringify({ code: "llm_unavailable", detail: "Claude n'est pas connecté" }), { status: 503 })
      : real(url, init)));
  location.hash = "#/week";
  render(App);
  const link = await screen.findByRole("link", { name: "Connecte Claude" });
  expect(link.getAttribute("href")).toBe("#/welcome");
});

test("la page Jour J sans objectif actif renvoie vers l'objectif", async () => {
  statusBody = { ...statusBody, ...noGoal };
  location.hash = "#/race";
  render(App);
  const link = await screen.findByRole("link", { name: "Créer un objectif" });
  expect(link).toHaveAttribute("href", "#/goal");
  expect(screen.getByText(/Aucun objectif actif/)).toBeVisible();
});

test("le lien Jour J d'un objectif ouvre la page sur cet objectif", async () => {
  syncInstant = true;
  const other = { ...goal, id: 2, distance_km: 10, race_date: "2026-12-20", priority: "secondaire" };
  statusBody = { ...statusBody, goals: [other, goal], next_goal: other };
  location.hash = "#/race/1";
  render(App);
  const select = (await screen.findByLabelText("Objectif")) as HTMLSelectElement;
  expect(select.value).toBe("1");
  expect(screen.getByRole("link", { name: /Jour J/ })).toHaveAttribute("aria-current", "page");
  await waitFor(() => expect(calls.some((c) => c.url === "/api/goals/1/race-plan")).toBe(true));
});

test("cycle terminé avec un objectif à venir : l'accueil ouvre les Objectifs", async () => {
  statusBody = { ...statusBody, cycle: null, has_activities: true };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/goal"));
  syncDone?.();
});

test("cycle terminé : Ma semaine (et ses anciennes adresses) invite à préparer le cycle suivant", async () => {
  statusBody = { ...statusBody, cycle: null };
  for (const route of ["#/week", "#/today", "#/plan"]) {
    location.hash = route;
    const { unmount } = render(App);
    const link = await screen.findByRole("link", { name: "Préparer le cycle suivant" });
    expect(link).toHaveAttribute("href", "#/goal");
    syncDone?.();
    unmount();
  }
});

test("les anciennes adresses Aujourd'hui et Programme ouvrent Ma semaine, sans menu Propositions", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, pending_proposal_id: 3 };
  location.hash = "#/plan";
  render(App);
  await screen.findByText("Ma semaine", { selector: "h1" });
  const nav = screen.getByRole("navigation", { name: "Navigation principale" });
  expect(nav.querySelector('a[href="#/week"]')).toHaveAttribute("aria-current", "page");
  expect(nav.querySelector('a[href="#/proposal"]')).toBeNull();
  expect(nav.querySelector('a[href="#/today"], a[href="#/plan"]')).toBeNull();
  expect(screen.getByLabelText("1 proposition en attente")).toBeVisible();
});

test("unavailable storage shows a dedicated page, without auto-sync nor goal form, then retries", async () => {
  statusBody = {
    ...statusBody, ...noGoal,
    storage: { code: "cloud_unreachable", detail: "Base cloud injoignable : vérifie ta connexion" },
  };
  render(App);
  const page = await screen.findByText("Données indisponibles");
  expect(page.closest("section")!.textContent).toContain("Base cloud injoignable : vérifie ta connexion");
  expect((screen.getByRole("link", { name: "Ouvrir les Réglages" }) as HTMLAnchorElement).getAttribute("href")).toBe("#/setup");
  expect(location.hash).toBe("");
  expect(syncs()).toBe(0);

  statusBody = { ...statusBody, storage: null };
  await fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  await waitFor(() => expect(location.hash).toBe("#/goal"));
  expect(screen.queryByText("Données indisponibles")).toBeNull();
});

test("unavailable storage still lets the settings page open", async () => {
  statusBody = { ...statusBody, storage: { code: "schema_too_new", detail: "Mets à jour CoachCloclo sur ce PC" } };
  location.hash = "#/setup";
  render(App);
  await screen.findByText("Réglages", { selector: "h1" });
  expect(screen.queryByText("Données indisponibles")).toBeNull();
});

test("settings: connected Garmin keeps its login form folded until 'Changer de compte'", async () => {
  location.hash = "#/setup";
  render(App);
  await fireEvent.click(await screen.findByRole("button", { name: "Changer de compte" }));
  expect(screen.getByLabelText("E-mail Garmin")).toBeTruthy();
  await fireEvent.click(screen.getByRole("button", { name: "Annuler" }));
  expect(screen.queryByLabelText("E-mail Garmin")).toBeNull();
});

test("settings: Claude mode saves on change, except an API mode still missing its key", async () => {
  location.hash = "#/setup";
  render(App);
  const puts = () => calls.filter((c) => c.url === "/api/settings" && c.method === "PUT").length;
  await fireEvent.click(await screen.findByLabelText("Clé API Anthropic"));
  expect(await screen.findByLabelText(/^Clé API/, { selector: "input[type=password]" })).toBeTruthy();
  expect(puts()).toBe(0);
  await fireEvent.click(screen.getByLabelText("Claude Code (CLI)"));
  await waitFor(() => expect(puts()).toBe(1));
});

test("after a sync that resent workouts, a non-blocking message is shown and cleared by the next sync", async () => {
  syncInstant = true;
  syncResent = 2;
  location.hash = "#/week";
  render(App);
  expect(await screen.findByText("2 séances mises à jour sur ta montre (FC repos 44)")).toBeInTheDocument();
  syncResent = 0;
  await fireEvent.click(await screen.findByRole("button", { name: /Synchroniser/ }));
  await waitFor(() => expect(syncs()).toBe(2));
  await waitFor(() => expect(screen.queryByText(/mises à jour sur ta montre/)).toBeNull());
});

test("no message after a sync that resent nothing", async () => {
  syncInstant = true;
  location.hash = "#/week";
  render(App);
  await waitFor(() => expect(syncs()).toBe(1));
  await screen.findByText("Ma semaine", { selector: "h1" });
  expect(screen.queryByText(/mises? à jour sur ta montre/)).toBeNull();
});

test("passage en erreur de stockage : les anciennes données ne réapparaissent pas", async () => {
  syncInstant = true;
  location.hash = "#/week";
  render(App);
  await screen.findByText("Ma semaine", { selector: "h1" });
  await waitFor(() => expect(syncs()).toBe(1));
  const button = await screen.findByRole("button", { name: /Synchroniser/ });
  await load("records", async () => "ancienne base", () => {});
  statusBody = { ...statusBody, storage: { code: "cloud_unreachable", detail: "Base cloud injoignable" } };
  await fireEvent.click(button);
  await screen.findByText("Données indisponibles");
  const apply = vi.fn();
  await load("records", async () => "nouvelle base", apply);
  expect(apply.mock.calls).toEqual([["nouvelle base"]]);
});

test("bascule de stockage depuis les Réglages : zones et état relus (appli et Réglages)", async () => {
  syncInstant = true;
  const base = vi.mocked(fetch).getMockImplementation()!;
  let mode = "turso";
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    if (!String(url).startsWith("/api/storage")) return base(url, init);
    if (init?.method === "DELETE") mode = "local";
    return new Response(JSON.stringify({ mode, turso_url: "libsql://x", has_turso_token: true }), { status: 200 });
  });
  location.hash = "#/setup";
  render(App);
  const button = await screen.findByRole("button", { name: "Revenir au stockage local" });
  await waitFor(() => expect(syncs()).toBe(1));
  await screen.findByRole("button", { name: "Synchroniser" });
  const count = (u: string) => calls.filter((c) => c.url === u).length;
  const [zones, status] = [count("/api/zones"), count("/api/status")];
  await fireEvent.click(button);
  await waitFor(() => expect(count("/api/zones")).toBe(zones + 1));
  await waitFor(() => expect(count("/api/status")).toBe(status + 2));
});

test("bascule de stockage finie depuis une autre page : rien de l'ancienne base ne reste affiché", async () => {
  syncInstant = true;
  const base = vi.mocked(fetch).getMockImplementation()!;
  let finish = () => {};
  let plans = 0;
  let switched = false;
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const u = String(url);
    if (u === "/api/plan") {
      plans++;
      if (switched) return new Promise<Response>(() => {}); // nouvelle base : pas encore répondu
    }
    if (!u.startsWith("/api/storage")) return base(url, init);
    if (init?.method === "DELETE") await new Promise<void>((r) => (finish = r));
    return new Response(JSON.stringify({ mode: "turso", turso_url: "libsql://x", has_turso_token: true }), { status: 200 });
  });
  location.hash = "#/setup";
  render(App);
  const button = await screen.findByRole("button", { name: "Revenir au stockage local" });
  await waitFor(() => expect(syncs()).toBe(1));
  await fireEvent.click(button);
  location.hash = "#/week";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await screen.findByText(/Objectif/, { selector: ".goal-what .meta" }); // plan de l'ancienne base
  const before = plans;
  switched = true;
  finish();
  await waitFor(() => expect(plans).toBe(before + 1));
  expect(await screen.findByText("Chargement…")).toBeVisible();
  expect(document.querySelector(".goal-what")).toBeNull();
});

// --- bascule : rien de l'ancienne base ne reste utilisable ---

/** Bascule tenue ouverte depuis les Réglages ; `status` et les autres lectures sont pilotables. */
async function pendingSwitch(over: { status?: () => Promise<Response> | null; get?: (u: string) => unknown } = {}) {
  syncInstant = true;
  const base = vi.mocked(fetch).getMockImplementation()!;
  const ctl = { finish: () => {}, over };
  vi.mocked(fetch).mockImplementation(async (url, init) => {
    const u = String(url);
    const custom = u === "/api/status" ? ctl.over.status?.() : null;
    if (custom) return custom;
    const given = (init?.method ?? "GET") === "GET" ? ctl.over.get?.(u) : undefined;
    if (given !== undefined) return new Response(JSON.stringify(given), { status: 200 });
    if (u === "/api/storage/cloud") await new Promise<void>((r) => (ctl.finish = r));
    if (u.startsWith("/api/storage"))
      return new Response(JSON.stringify({ mode: "turso", turso_url: "libsql://x", has_turso_token: true }), { status: 200 });
    return base(url, init);
  });
  location.hash = "#/setup";
  render(App);
  const button = await screen.findByRole("button", { name: "Revenir au stockage local" });
  await waitFor(() => expect(syncs()).toBe(1));
  await screen.findByRole("button", { name: "Synchroniser" });
  await screen.findByRole("button", { name: /Réimporter/ });
  await fireEvent.click(button);
  return ctl;
}
const goto = (hash: string) => {
  location.hash = hash;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
};
const racePlans = () => calls.filter((c) => c.url.endsWith("/race-plan")).map((c) => c.url);
const reply = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
const pause = () => new Promise((r) => setTimeout(r, 30));

test("bascule : Jour J ne relit jamais un objectif de l'ancienne base", async () => {
  const ctl = await pendingSwitch();
  goto("#/race/1");
  await waitFor(() => expect(racePlans()).toEqual(["/api/goals/1/race-plan"]));
  await pause();
  let answer: (r: Response) => void = () => {};
  ctl.over.status = () => new Promise<Response>((r) => (answer = r));
  ctl.finish();
  await pause();
  expect(racePlans()).toHaveLength(1); // rien avant le nouvel état
  expect(screen.getByText("Chargement…")).toBeVisible();
  const other = { ...goal, id: 7 };
  answer(reply({ ...statusBody, goals: [other], next_goal: other }));
  // l'id de l'adresse (1) n'existe pas dans la nouvelle base
  await waitFor(() => expect(racePlans()).toEqual(["/api/goals/1/race-plan", "/api/goals/7/race-plan"]));
});

test("bascule puis /status en échec : l'ancien état est oublié", async () => {
  statusBody = { ...statusBody, pending_proposal_id: 3 };
  const ctl = await pendingSwitch();
  expect(screen.getByLabelText("1 proposition en attente")).toBeVisible();
  ctl.over.status = () => Promise.resolve(reply({ detail: "Coupé" }, 503));
  ctl.finish();
  expect((await screen.findAllByText("Coupé")).length).toBeGreaterThan(0);
  expect(screen.queryByLabelText("1 proposition en attente")).toBeNull();
});

test.each([200, 503])("bascule : une lecture d'état partie avant (%i) ne change plus rien", async (code) => {
  const ctl = await pendingSwitch();
  const late: ((r: Response) => void)[] = [];
  ctl.over.status = () => new Promise<Response>((r) => late.push(r));
  goto("#/week");
  await fireEvent.click(await screen.findByRole("button", { name: /Synchroniser/ })); // relit l'état à la fin
  await waitFor(() => expect(late).toHaveLength(1));
  ctl.over.status = undefined;
  ctl.finish();
  await pause();
  late[0](code === 200 ? reply({ ...statusBody, pending_proposal_id: 3 }) : reply({ detail: "Ancienne erreur" }, code));
  await pause();
  expect(screen.queryByLabelText("1 proposition en attente")).toBeNull();
  expect(screen.queryByText("Ancienne erreur")).toBeNull();
});

test.each([false, true])("bascule : zones de l'ancienne base oubliées (lecture tardive : %s)", async (late) => {
  const { currentZones } = await import("./lib/zones.svelte");
  let answer: (r: Response) => void = () => {};
  const ctl = await pendingSwitch({ get: (u) => (u === "/api/zones" ? { hr: "ancienne" } : undefined) });
  await waitFor(() => expect(currentZones()).toEqual({ hr: "ancienne" }));
  ctl.over.get = undefined;
  const before = vi.mocked(fetch).getMockImplementation()!;
  let reads = 0;
  vi.mocked(fetch).mockImplementation((url, init) => {
    if (url !== "/api/zones") return before(url, init);
    if (late && reads++ === 0) return new Promise<Response>((r) => (answer = r));
    return Promise.resolve(reply({}, 503));
  });
  if (late) {
    await fireEvent.click(await screen.findByRole("button", { name: /Synchroniser/ }));
    await waitFor(() => expect(reads).toBe(1));
  }
  ctl.finish();
  await pause();
  answer(reply({ hr: "ancienne" }));
  await pause();
  expect(currentZones()).toBeNull();
});

test("bascule : les Réglages relisent leurs données, FC repos et consommation comprises", async () => {
  const rest = (manual: number) => ({ value: manual, source: "manual", nights: null, manual, auto_value: null, auto_nights: null });
  let usage = 0;
  const ctl = await pendingSwitch({
    get: (u) => {
      if (u === "/api/llm-usage") usage++;
      return u === "/api/rest-hr" ? rest(41) : undefined;
    },
  });
  const input = screen.getByLabelText("FC repos") as HTMLInputElement;
  expect(input.value).toBe("41");
  await fireEvent.input(input, { target: { value: "43" } }); // brouillon de l'ancienne base
  expect(usage).toBe(1);
  ctl.over.get = (u) => {
    if (u === "/api/llm-usage") usage++;
    return u === "/api/rest-hr" ? rest(55) : undefined;
  };
  statusBody = { ...statusBody, history: { ...idle, total: 777 } };
  ctl.finish();
  await waitFor(() => expect((screen.getByLabelText("FC repos") as HTMLInputElement).value).toBe("55"));
  expect(screen.queryByText("41 bpm, saisie à la main")).toBeNull();
  expect(await screen.findByText(/777/)).toBeVisible();
  expect(usage).toBe(2);
});

test("bascule : une lecture des Réglages partie avant ne restaure pas l'ancienne base", async () => {
  const ctl = await pendingSwitch();
  const late: ((r: Response) => void)[] = [];
  ctl.over.status = () => new Promise<Response>((r) => late.push(r));
  await fireEvent.click(screen.getByRole("button", { name: /Réimporter/ })); // relit l'état
  await waitFor(() => expect(late.length).toBeGreaterThan(0));
  ctl.over.status = undefined;
  const old = { ...statusBody, history: { ...idle, total: 111 } };
  statusBody = { ...statusBody, history: { ...idle, total: 777 } };
  ctl.finish();
  expect(await screen.findByText(/777/)).toBeVisible();
  late.forEach((r) => r(reply(old)));
  await pause();
  expect(screen.getByText(/777/)).toBeVisible();
  expect(screen.queryByText(/111/)).toBeNull();
});

test("bascule ratée : l'erreur du stockage reste affichée dans les Réglages", async () => {
  const ctl = await pendingSwitch();
  const before = vi.mocked(fetch).getMockImplementation()!;
  ctl.finish();
  await pause();
  vi.mocked(fetch).mockImplementation(async (url, init) =>
    init?.method === "DELETE" ? reply({ code: "x", detail: "Bascule impossible" }, 503) : before(url, init));
  await fireEvent.click(screen.getByRole("button", { name: "Revenir au stockage local" }));
  expect(await screen.findByText("Bascule impossible")).toBeVisible();
  await pause();
  expect(screen.getByText("Bascule impossible")).toBeVisible();
});

// --- démarrage sans attendre Garmin, synchro discrète ---

const BANNER = "Analyse de ta séance par Claude…";
const plans = () => calls.filter((c) => c.url === "/api/plan").length;
const phases = () => calls.filter((c) => c.url === "/api/sync/phase").length;
const states = () => calls.filter((c) => c.url === "/api/garmin/state").length;
/** Réponse retenue jusqu'à `open()`. */
function gate() {
  let open = () => {};
  const closed = new Promise<void>((r) => (open = r));
  return { closed, open: () => open() };
}
const failSync = () => {
  syncFails = true;
  syncDone!();
};
/** Remplace certaines réponses ; `null` : réponse habituelle. */
function override(custom: (url: string) => Promise<Response> | Response | null) {
  const base = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (url, init) => custom(String(url)) ?? base(url, init));
}

test("affiche la semaine avant la réponse de Garmin", async () => {
  const [g, i] = [gate(), gate()];
  garminGate = g.closed;
  setupGate = i.closed;
  setupBody = { ...setupOk };
  render(App);
  await screen.findByText("Ma semaine", { selector: "h1" });
  expect(await screen.findByText("Vérification de Garmin…")).toBeVisible();
  expect(screen.queryByRole("button", { name: /Synchro/ })).toBeNull();
  expect(screen.queryByRole("link", { name: "Se connecter" })).toBeNull();
  await pause();
  expect(syncs()).toBe(0);
  g.open(); // l'installation (CLI Claude) n'a toujours pas répondu
  expect(await screen.findByText("Garmin connecté")).toBeVisible();
  await waitFor(() => expect(syncs()).toBe(1));
  expect(states()).toBe(1);
  i.open();
  await pause();
  expect(location.hash).toBe("#/week");
  syncDone!();
});

test("aucun bandeau pendant la phase garmin", async () => {
  phase = "garmin";
  location.hash = "#/week";
  vi.useFakeTimers();
  render(App);
  await vi.advanceTimersByTimeAsync(3000);
  expect(syncs()).toBe(1);
  expect(phases()).toBeGreaterThan(0);
  expect(screen.queryByText(BANNER)).toBeNull();
  expect(screen.queryByText("Synchronisation Garmin…")).toBeNull();
  expect(screen.getByRole("button", { name: "Synchronisation…" })).toBeDisabled();
  syncDone!();
});

test("bandeau Claude en phase claude seulement, retiré à la fin", async () => {
  phase = "garmin";
  location.hash = "#/week";
  vi.useFakeTimers();
  render(App);
  await vi.advanceTimersByTimeAsync(2000);
  expect(screen.queryByText(BANNER)).toBeNull();
  phase = "claude";
  await vi.advanceTimersByTimeAsync(1000);
  expect(screen.getByText(BANNER)).toBeVisible();
  syncDone!();
  await vi.advanceTimersByTimeAsync(50);
  expect(screen.queryByText(BANNER)).toBeNull();
});

test("une réponse de phase arrivée après la synchro ne réaffiche pas le bandeau", async () => {
  const late: ((r: Response) => void)[] = [];
  override((url) => (url === "/api/sync/phase" ? new Promise<Response>((r) => late.push(r)) : null));
  location.hash = "#/week";
  vi.useFakeTimers();
  render(App);
  await vi.advanceTimersByTimeAsync(3500);
  expect(late).toHaveLength(1); // pas de nouveau sondage tant que le précédent n'a pas répondu
  syncDone!();
  await vi.advanceTimersByTimeAsync(50);
  late[0](reply({ phase: "claude" }));
  await vi.advanceTimersByTimeAsync(50);
  expect(screen.queryByText(BANNER)).toBeNull();
});

test.each([false, true])("le sondage de phase s'arrête après la synchro, réussie ou non (échec : %s)", async (ko) => {
  phase = "claude";
  location.hash = "#/week";
  vi.useFakeTimers();
  render(App);
  await vi.advanceTimersByTimeAsync(2500);
  expect(phases()).toBeGreaterThan(0);
  expect(screen.getByText(BANNER)).toBeVisible();
  if (ko) failSync();
  else syncDone!();
  await vi.advanceTimersByTimeAsync(50);
  expect(screen.queryByText(BANNER)).toBeNull();
  const before = phases();
  await vi.advanceTimersByTimeAsync(5000);
  expect(phases()).toBe(before);
});

test.each([false, true])("synchro sans changement : /api/plan non relu (changement : %s)", async (changed) => {
  syncChanged = changed;
  location.hash = "#/week";
  render(App);
  await waitFor(() => expect(syncs()).toBe(1));
  const before = plans();
  const status = calls.filter((c) => c.url === "/api/status").length;
  syncDone!();
  await screen.findByText(/Dernière synchro/);
  await pause();
  expect(plans()).toBe(before + (changed ? 1 : 0));
  expect(calls.filter((c) => c.url === "/api/status").length).toBeGreaterThan(status);
});

test("synchro en échec : pages relues, l'erreur reste affichée", async () => {
  location.hash = "#/week";
  render(App);
  await waitFor(() => expect(syncs()).toBe(1));
  const before = plans();
  failSync();
  const message = "Garmin est indisponible pour le moment, réessaie plus tard.";
  await screen.findByText(message);
  await waitFor(() => expect(plans()).toBe(before + 1));
  await pause();
  expect(screen.getByText(message)).toBeVisible();
});

test("garmin auth_required sans route demandée : renvoi vers #/setup", async () => {
  const g = gate();
  garminGate = g.closed;
  garminBody = "auth_required";
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
  g.open();
  await waitFor(() => expect(location.hash).toBe("#/setup"));
  expect(await screen.findByLabelText("E-mail Garmin")).toBeVisible();
  expect(syncs()).toBe(0);
});

test("garmin auth_required après navigation : pas de renvoi", async () => {
  const g = gate();
  garminGate = g.closed;
  garminBody = "auth_required";
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
  goto("#/goal");
  g.open();
  expect(await screen.findByText("Connexion Garmin requise")).toBeVisible();
  await pause();
  expect(location.hash).toBe("#/goal");
});

test("garmin auth_required après un aller-retour : pas de renvoi", async () => {
  const g = gate();
  garminGate = g.closed;
  garminBody = "auth_required";
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
  await pause();
  for (const hash of ["#/goal", "#/week"]) {
    location.hash = hash; // l'événement vient du navigateur
    await pause();
  }
  g.open();
  expect(await screen.findByText("Connexion Garmin requise")).toBeVisible();
  await pause();
  expect(location.hash).toBe("#/week");
});

test("garmin auth_required bien après l'affichage, sans navigation : renvoi", async () => {
  const g = gate();
  garminGate = g.closed;
  garminBody = "auth_required";
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
  await pause(); // l'événement du changement fait par l'appli est passé
  g.open();
  await waitFor(() => expect(location.hash).toBe("#/setup"));
});

test("route demandée au lancement : pas de renvoi", async () => {
  garminBody = "auth_required";
  setupBody = { ...setupOk, garmin: "auth_required" };
  location.hash = "#/week";
  render(App);
  expect(await screen.findByText("Connexion Garmin requise")).toBeVisible();
  await pause();
  expect(location.hash).toBe("#/week");
});

test("installation incomplète avec un plan : accueil tout de suite, puis #/welcome", async () => {
  const i = gate();
  setupGate = i.closed;
  setupBody = { ...setupOk, claude_auth: false };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
  i.open();
  await waitFor(() => expect(location.hash).toBe("#/welcome"));
  syncDone?.();
});

test("premier lancement : attend l'installation puis #/welcome", async () => {
  const i = gate();
  setupGate = i.closed;
  setupBody = { ...setupOk, claude_auth: false };
  statusBody = { ...statusBody, ...noGoal };
  render(App);
  await screen.findByText("Garmin connecté");
  await pause();
  expect(location.hash).toBe("");
  i.open();
  await waitFor(() => expect(location.hash).toBe("#/welcome"));
  syncDone?.();
});

test("premier lancement : attend aussi Garmin", async () => {
  const g = gate();
  garminGate = g.closed;
  garminBody = "auth_required";
  statusBody = { ...statusBody, ...noGoal };
  render(App);
  await screen.findByText("Vérification de Garmin…");
  await pause();
  expect(location.hash).toBe("");
  g.open();
  await waitFor(() => expect(location.hash).toBe("#/setup"));
});

test("garminState en échec : unavailable, pages consultables", async () => {
  garminBody = "échec";
  render(App);
  expect(await screen.findByText("Garmin indisponible")).toBeVisible();
  expect(await screen.findByText("Ma semaine", { selector: "h1" })).toBeVisible();
  await pause();
  expect(location.hash).toBe("#/week");
  expect(screen.queryByRole("alert")).toBeNull();
  expect(syncs()).toBe(0);
});

test("Garmin indisponible au lancement : relu à l'ouverture des Réglages", async () => {
  garminBody = "unavailable";
  location.hash = "#/week";
  render(App);
  await screen.findByText("Garmin indisponible");
  garminBody = "ok";
  goto("#/setup");
  expect(await screen.findByText("Garmin connecté")).toBeVisible();
  expect(await screen.findByRole("button", { name: "Changer de compte" })).toBeVisible();
});

test("session Garmin refusée pendant la synchro : état relu", async () => {
  override((url) =>
    url === "/api/sync" ? reply({ code: "garmin_auth", detail: "Session expirée" }, 401) : null);
  const g = gate();
  garminGate = g.closed;
  location.hash = "#/setup";
  render(App);
  await screen.findByText("Vérification de Garmin…");
  await pause();
  g.open();
  await screen.findByText("Garmin connecté");
  garminBody = "auth_required";
  expect(await screen.findByText("Connexion Garmin requise")).toBeVisible();
  expect(await screen.findByLabelText("E-mail Garmin")).toBeVisible();
});

test.each([false, true])("la synchro attend la page, 5 s au plus (page bloquée : %s)", async (stuck) => {
  const g = gate();
  override((url) => (url === "/api/plan" ? g.closed.then(() => reply(plan)) : null));
  location.hash = "#/week";
  vi.useFakeTimers();
  render(App);
  await vi.advanceTimersByTimeAsync(4500);
  expect(syncs()).toBe(0);
  if (!stuck) g.open();
  await vi.advanceTimersByTimeAsync(stuck ? 1000 : 100);
  expect(syncs()).toBe(1);
  g.open();
  syncDone!();
});

test("clic sur Synchroniser avant la synchro de démarrage : une seule", async () => {
  syncInstant = true;
  const g = gate();
  override((url) => (url === "/api/plan" ? g.closed.then(() => reply(plan)) : null));
  location.hash = "#/week";
  render(App);
  await fireEvent.click(await screen.findByRole("button", { name: "Synchroniser" }));
  await screen.findByText(/Dernière synchro/);
  g.open();
  await pause();
  await pause();
  expect(syncs()).toBe(1);
});

test("application fermée avant la synchro de démarrage : elle ne part pas", async () => {
  const g = gate();
  garminGate = g.closed;
  location.hash = "#/week";
  const { unmount } = render(App);
  await screen.findByText("Vérification de Garmin…");
  unmount();
  g.open();
  await pause();
  await pause();
  expect(syncs()).toBe(0);
});

test("connexion Garmin réussie : état relu avant la synchro", async () => {
  syncInstant = true;
  garminBody = "auth_required";
  statusBody = { ...statusBody, has_activities: true };
  location.hash = "#/setup";
  render(App);
  await screen.findByLabelText("E-mail Garmin");
  const g = gate();
  garminGate = g.closed;
  garminBody = "ok";
  const before = states();
  await loginToGarmin();
  await waitFor(() => expect(states()).toBeGreaterThan(before));
  await pause();
  expect(syncs()).toBe(0);
  g.open();
  await waitFor(() => expect(syncs()).toBe(1));
  expect(location.hash).toBe("#/week");
});

test("PIN saisi : état Garmin relu puis synchro", async () => {
  let locked = true;
  override((url) => {
    if (url === "/api/auth/pin") locked = false;
    return locked ? reply({ code: "pin_required", detail: "PIN" }, 401) : null;
  });
  render(App);
  await fireEvent.input(await screen.findByLabelText("Code PIN"), { target: { value: "1234" } });
  await fireEvent.click(screen.getByRole("button", { name: "Entrer" }));
  await waitFor(() => expect(location.hash).toBe("#/week"));
  await waitFor(() => expect(syncs()).toBe(1));
  syncDone!();
});

test("bascule de stockage pendant le premier lancement : pas de renvoi sans état", async () => {
  const i = gate();
  setupGate = i.closed;
  setupBody = { ...setupOk };
  let hang = false;
  override((url) => {
    if (url === "/api/status" && hang) return new Promise<Response>(() => {}); // nouvel état jamais lu
    if (!url.startsWith("/api/storage")) return null;
    return reply({ mode: "turso", turso_url: "libsql://x", has_turso_token: true });
  });
  statusBody = { ...statusBody, ...noGoal };
  render(App);
  await screen.findByText("Garmin connecté");
  goto("#/setup");
  const button = await screen.findByRole("button", { name: "Revenir au stockage local" });
  hang = true;
  await fireEvent.click(button);
  await pause();
  i.open();
  await pause();
  expect(location.hash).toBe("#/setup");
  syncDone?.();
});

test("sous-page de statistiques : lien direct gardé, changement d'onglet sans relecture", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, has_activities: true };
  location.hash = "#/stats/load";
  render(App);
  const tab = await screen.findByRole("link", { name: "Charge" });
  expect(tab).toHaveAttribute("aria-current", "page");
  expect(location.hash).toBe("#/stats/load");
  expect(document.querySelector('.sidebar a[href="#/stats"]')).toHaveClass("active");
  await waitFor(() => expect(syncs()).toBe(1));
  await screen.findByText(/Dernière synchro/);

  const before = statsCalls;
  location.hash = "#/stats/progress";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await waitFor(() => expect(screen.getByRole("link", { name: "Progression" })).toHaveAttribute("aria-current", "page"));
  expect(screen.getByRole("link", { name: "Charge" })).not.toHaveAttribute("aria-current");
  expect(statsCalls).toBe(before);

  location.hash = "#/stats/inconnu";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await waitFor(() => expect(screen.getByRole("link", { name: "Aperçu" })).toHaveAttribute("aria-current", "page"));
});
