import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Goal from "./Goal.svelte";

afterEach(() => {
  vi.unstubAllGlobals();
  location.hash = "";
});

/** Le formulaire du premier objectif s'affiche une fois les objectifs lus. */
const formReady = () => screen.findByLabelText("Distance (km)");

const EMPTY = { cycle: null, goals: [], horizon: [], open_injury: null, weeks: [] };
const noPlan = () =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(EMPTY), { status: 200 })));

test("goal form bounds match the backend (2 to 7 sessions, positive distance)", async () => {
  noPlan();
  render(Goal);
  await formReady();
  const perWeek = within(screen.getByRole("group", { name: "Séances par semaine" }));
  expect(perWeek.getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["2", "3", "4", "5", "6", "7"]);
  const distance = screen.getByLabelText("Distance (km)") as HTMLInputElement;
  expect(Number(distance.min)).toBeGreaterThan(0);
});

test("distance presets fill the distance field", async () => {
  noPlan();
  render(Goal);
  await formReady();
  await fireEvent.click(screen.getByRole("button", { name: "Marathon · 42,2 km" }));
  expect((screen.getByLabelText("Distance (km)") as HTMLInputElement).value).toBe("42.2");
  expect(screen.getByRole("button", { name: "Marathon · 42,2 km" })).toHaveAttribute("aria-pressed", "true");
});

const mkGoal = (extra = {}) => ({
  id: 1, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2027-03-01", priority: "principal", status: "active",
  gpx_summary: null, target_time_s: null, target_source: null, ...extra,
});
const mkCycle = (extra = {}) => ({
  id: 1, status: "active", plan_start: "2027-01-04", end_date: "2027-03-01", sessions_per_week: 4,
  available_days: ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"], long_run_day: null,
  include_bike: false, plan_accepted: false, needs_generation: false, ...extra,
});
const WEEKS = [{ week_index: 1, week_monday: "2027-01-04", sessions: [] }];
const mkPlan = (goal = mkGoal(), cycle = mkCycle()) => ({ cycle, goals: [goal], horizon: [], open_injury: null, weeks: WEEKS });

function fillBase() {
  fireEvent.input(screen.getByLabelText("Date de la course"), { target: { value: "2027-03-01" } });
}

test("target time defaults to Claude estimate", async () => {
  noPlan();
  render(Goal);
  await formReady();
  expect(screen.getByRole("radio", { name: "Laisser Claude estimer" })).toBeChecked();
  expect(screen.queryByLabelText("Temps visé (h:mm)")).toBeNull();
});

test("choosing my own time shows the field and sends it", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.endsWith("/goals")) return new Response(JSON.stringify(mkGoal({ target_time_s: 6600, target_source: "user" })), { status: 200 });
    if (url.endsWith("/generate")) return new Response(JSON.stringify({ summary: "ok", weeks: 8 }), { status: 200 });
    return new Response(JSON.stringify(EMPTY), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(Goal);
  await formReady();
  await fireEvent.click(screen.getByRole("radio", { name: "Je fixe mon temps" }));
  await fireEvent.input(screen.getByLabelText("Temps visé (h:mm)"), { target: { value: "1:50" } });
  fillBase();
  await fireEvent.submit(screen.getByRole("button", { name: "Générer le plan avec Claude" }).closest("form")!);
  await vi.waitFor(() => {
    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/goals") && (i as RequestInit)?.method === "POST");
    expect(post).toBeTruthy();
    expect(((post![1] as RequestInit).body as FormData).get("target_time")).toBe("1:50");
  });
});

test("invalid own time blocks submit", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(EMPTY), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  render(Goal);
  await formReady();
  await fireEvent.click(screen.getByRole("radio", { name: "Je fixe mon temps" }));
  await fireEvent.input(screen.getByLabelText("Temps visé (h:mm)"), { target: { value: "1h50" } });
  fillBase();
  await fireEvent.submit(screen.getByRole("button", { name: "Générer le plan avec Claude" }).closest("form")!);
  expect(await screen.findByText(/Temps visé invalide/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([, i]) => (i as RequestInit | undefined)?.method === "POST")).toBe(false);
});

test("draft shows Claude estimate", async () => {
  const goal = mkGoal({ target_time_s: 6720, target_source: "claude" });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(mkPlan(goal)), { status: 200 })));
  render(Goal);
  expect(await screen.findByText(/Temps estimé par Claude : 1 h 52/)).toBeInTheDocument();
});

test("draft shows the Claude estimate right after generation, without remount", async () => {
  const claudeGoal = mkGoal({ target_time_s: 6720, target_source: "claude" });
  let generated = false;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.endsWith("/goals")) return new Response(JSON.stringify(mkGoal()), { status: 200 });
    if (url.endsWith("/generate")) {
      generated = true;
      return new Response(JSON.stringify({ summary: "ok", weeks: 8 }), { status: 200 });
    }
    const body = generated ? mkPlan(claudeGoal) : EMPTY;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(Goal);
  await formReady();
  fillBase();
  await fireEvent.submit(screen.getByRole("button", { name: "Générer le plan avec Claude" }).closest("form")!);
  expect(await screen.findByText(/Temps estimé par Claude : 1 h 52/)).toBeInTheDocument();
});

test("creation sends the chosen available days and long run day", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.endsWith("/goals")) return new Response(JSON.stringify(mkGoal()), { status: 200 });
    if (url.endsWith("/generate")) return new Response(JSON.stringify({ summary: "ok", weeks: 8 }), { status: 200 });
    return new Response(JSON.stringify(EMPTY), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(Goal);
  await formReady();
  for (const d of ["Lundi", "Mercredi", "Vendredi", "Samedi"]) await fireEvent.click(screen.getByRole("checkbox", { name: d }));
  await fireEvent.change(screen.getByLabelText("Jour de la sortie longue"), { target: { value: "dimanche" } });
  fillBase();
  await fireEvent.submit(screen.getByRole("button", { name: "Générer le plan avec Claude" }).closest("form")!);
  await vi.waitFor(() => {
    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/goals") && (i as RequestInit)?.method === "POST");
    expect(post).toBeTruthy();
    const body = (post![1] as RequestInit).body as FormData;
    expect(body.get("available_days")).toBe("mardi,jeudi,dimanche");
    expect(body.get("long_run_day")).toBe("dimanche");
  });
});

test("creation sends include_bike when the option is ticked", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.endsWith("/goals")) return new Response(JSON.stringify(mkGoal()), { status: 200 });
    if (url.endsWith("/generate")) return new Response(JSON.stringify({ summary: "ok", weeks: 8 }), { status: 200 });
    return new Response(JSON.stringify(EMPTY), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(Goal);
  await formReady();
  await fireEvent.click(screen.getByRole("checkbox", { name: /Inclure du vélo/ }));
  fillBase();
  await fireEvent.submit(screen.getByRole("button", { name: "Générer le plan avec Claude" }).closest("form")!);
  await vi.waitFor(() => {
    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/goals") && (i as RequestInit)?.method === "POST");
    expect(post).toBeTruthy();
    expect(((post![1] as RequestInit).body as FormData).get("include_bike")).toBe("true");
  });
});

test("creation is disabled with fewer days than sessions per week", async () => {
  noPlan();
  render(Goal);
  await formReady();
  await fireEvent.click(screen.getByRole("radio", { name: "3" }));
  for (const d of ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]) await fireEvent.click(screen.getByRole("checkbox", { name: d }));
  expect(screen.getByText("Coche au moins 3 jours")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Générer le plan avec Claude" })).toBeDisabled();
});

test("generating and accepting the draft go through the cycle", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.endsWith("/goals")) return new Response(JSON.stringify(mkGoal()), { status: 200 });
    if (init?.method === "POST") return new Response(JSON.stringify({ summary: "ok", weeks: 8, status: "ok" }), { status: 200 });
    return new Response(JSON.stringify(mkPlan()), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const onchanged = vi.fn();
  render(Goal, { onchanged });
  await fireEvent.click(await screen.findByRole("button", { name: "Régénérer" }));
  await fireEvent.click(await screen.findByRole("button", { name: "Valider le plan" }));
  await waitFor(() => expect(location.hash).toBe("#/today"));
  const posts = fetchMock.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === "POST").map(([u]) => u);
  expect(posts).toEqual(["/api/cycle/generate", "/api/cycle/accept"]);
  expect(onchanged).toHaveBeenCalled();
});

test("the plan settings button depends on the cycle and opens its dialog", async () => {
  const cycle = mkCycle({ plan_accepted: true, long_run_day: "dimanche" });
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") return new Response(JSON.stringify({ cycle, proposal_id: 9 }), { status: 200 });
    return new Response(JSON.stringify(mkPlan(mkGoal(), cycle)), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const onchanged = vi.fn();
  render(Goal, { onchanged });
  await fireEvent.click(await screen.findByRole("button", { name: "Réglages du plan" }));
  const dialog = within(screen.getByRole("dialog", { name: "Réglages du plan" }));
  expect(dialog.getByLabelText("Jour de la sortie longue")).toHaveValue("dimanche");
  await fireEvent.click(dialog.getByRole("checkbox", { name: /Inclure du vélo/ }));
  await fireEvent.click(dialog.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(location.hash).toBe("#/proposal"));
  expect(onchanged).toHaveBeenCalled();
  const patch = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === "PATCH")!;
  expect(patch[0]).toBe("/api/cycle");
});

// --- plusieurs objectifs -------------------------------------------------------------------

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
const principal = mkGoal({ id: 1, race_date: "2027-03-01" });
const secondaire = mkGoal({ id: 2, distance_km: 10, race_date: "2027-02-07", priority: "secondaire", target_time_s: 2700, target_source: "user" });
const plaisir = mkGoal({ id: 3, type: "trail", distance_km: 20, d_plus_m: 800, race_date: "2027-04-18", priority: "plaisir" });
const accepted = mkCycle({ plan_accepted: true });

type Write = (url: string, init: RequestInit) => Response;
/** API d'un cycle validé : `goals` du statut (à venir) ; les écritures passent par `onwrite`. */
function server(opts: { goals?: unknown[]; cycle?: () => unknown; onwrite?: Write } = {}) {
  const goals = opts.goals ?? [principal, secondaire];
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method !== "GET" && opts.onwrite) return opts.onwrite(url, init!);
    const cycle = opts.cycle?.() ?? accepted;
    if (url === "/api/status") return json({ cycle, goals, next_goal: goals[0] ?? null });
    if (url === "/api/plan") return json({ cycle, goals, horizon: [], open_injury: null, weeks: WEEKS });
    return json({ summary: "ok", weeks: 8 });
  });
  vi.stubGlobal("fetch", f);
  return f;
}
const writes = (f: ReturnType<typeof server>) =>
  f.mock.calls
    .filter(([, i]) => (i as RequestInit | undefined)?.method && (i as RequestInit).method !== "GET")
    .map(([u, i]) => `${(i as RequestInit).method} ${u}`);
const items = async () => within(await screen.findByRole("list", { name: "Objectifs à venir" })).findAllByRole("listitem");
const submitForm = (name: string) => fireEvent.submit(screen.getByRole("button", { name }).closest("form")!);

test("affiche les objectifs triés avec leur priorité", async () => {
  server({ goals: [plaisir, principal, secondaire] });
  render(Goal);
  const li = await items();
  expect(li).toHaveLength(3);
  expect(li[0]).toHaveTextContent("Course sur route de 10 km");
  expect(li[0]).toHaveTextContent("Secondaire");
  expect(li[0]).toHaveTextContent("7 février 2027");
  expect(li[0]).toHaveTextContent("Temps visé : 45 min");
  expect(li[1]).toHaveTextContent("Course sur route de 21,1 km");
  expect(li[1]).toHaveTextContent("Principal");
  expect(li[2]).toHaveTextContent("Trail de 20 km");
  expect(li[2]).toHaveTextContent("800 m D+");
  expect(li[2]).toHaveTextContent("Plaisir");
  expect(within(li[2]).getByRole("link", { name: "Jour J" })).toHaveAttribute("href", "#/race/3");
  expect(within(li[2]).getByRole("button", { name: "Modifier" })).toBeVisible();
  expect(within(li[2]).getByRole("button", { name: "Retirer" })).toBeVisible();
  // pas de formulaire tant qu'on ne demande pas d'ajout
  expect(screen.queryByLabelText("Distance (km)")).toBeNull();
});

test("ajoute un objectif sans réglages du plan quand un cycle existe", async () => {
  const f = server({ onwrite: () => json({ goal: plaisir, proposal_id: null, needs_generation: false }) });
  const onchanged = vi.fn();
  render(Goal, { onchanged });
  await fireEvent.click(await screen.findByRole("button", { name: "Ajouter un objectif" }));
  expect(screen.queryByRole("group", { name: "Séances par semaine" })).toBeNull();
  expect(within(screen.getByRole("group", { name: "Priorité" })).getByRole("radio", { name: "Secondaire" })).toBeChecked();
  fillBase();
  await submitForm("Ajouter l'objectif");
  await waitFor(() => expect(writes(f)).toEqual(["POST /api/goals"]));
  const body = (f.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === "POST")![1] as RequestInit).body as FormData;
  expect(body.get("priority")).toBe("secondaire");
  expect(body.has("sessions_per_week")).toBe(false);
  expect(body.has("available_days")).toBe(false);
  await waitFor(() => expect(onchanged).toHaveBeenCalled());
  await waitFor(() => expect(screen.queryByLabelText("Distance (km)")).toBeNull());
  expect(location.hash).toBe("");
});

test("affiche le message d'écart renvoyé par le serveur", async () => {
  const msg = "Course sur route de 10 km du 07/02/2027 (Secondaire) est à 6 jours : passe l'un des deux en Plaisir ou déplace-le";
  server({ onwrite: () => json({ code: "invalid", detail: msg }, 422) });
  render(Goal);
  await fireEvent.click(await screen.findByRole("button", { name: "Ajouter un objectif" }));
  fireEvent.input(screen.getByLabelText("Date de la course"), { target: { value: "2027-02-13" } });
  await submitForm("Ajouter l'objectif");
  expect(await screen.findByText(msg)).toBeVisible();
  // le formulaire reste ouvert pour corriger
  expect(screen.getByDisplayValue("2027-02-13")).toBeVisible();
});

test("ouvre la proposition après un ajout qui l'a créée", async () => {
  server({ onwrite: () => json({ goal: plaisir, proposal_id: 12, needs_generation: false }) });
  const onchanged = vi.fn();
  render(Goal, { onchanged });
  await fireEvent.click(await screen.findByRole("button", { name: "Ajouter un objectif" }));
  fillBase();
  await submitForm("Ajouter l'objectif");
  await waitFor(() => expect(location.hash).toBe("#/proposal"));
  expect(onchanged).toHaveBeenCalled();
});

test("affiche le bandeau Générer quand needs_generation", async () => {
  // cycle validé, puis à régénérer après l'ajout, puis brouillon après la génération
  let cycle = accepted;
  const f = server({
    cycle: () => cycle,
    onwrite: (url) => {
      cycle = mkCycle({ plan_accepted: false, needs_generation: url === "/api/goals" });
      return url === "/api/goals"
        ? json({ goal: plaisir, proposal_id: null, needs_generation: true })
        : json({ summary: "Plan refait", weeks: 8 });
    },
  });
  render(Goal);
  await fireEvent.click(await screen.findByRole("button", { name: "Ajouter un objectif" }));
  fillBase();
  await submitForm("Ajouter l'objectif");
  const banner = await screen.findByRole("region", { name: "Plan à recalculer" });
  expect(banner).toHaveTextContent("Le plan doit être recalculé");
  await fireEvent.click(within(banner).getByRole("button", { name: "Générer" }));
  await waitFor(() => expect(writes(f)).toEqual(["POST /api/goals", "POST /api/cycle/generate"]));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Plan à recalculer" })).toBeNull());
  expect(await screen.findByText("Plan refait")).toBeVisible();
});

test("retire un objectif après confirmation", async () => {
  const confirm = vi.fn(() => true);
  vi.stubGlobal("confirm", confirm);
  const f = server({ onwrite: () => json({ proposal_id: 5, needs_generation: false }) });
  render(Goal);
  await fireEvent.click(within((await items())[0]).getByRole("button", { name: "Retirer" }));
  expect(confirm).toHaveBeenCalledWith("Retirer Course sur route de 10 km du 7 février 2027 ?");
  await waitFor(() => expect(writes(f)).toEqual(["DELETE /api/goals/2"]));
  await waitFor(() => expect(location.hash).toBe("#/proposal"));
});

test("ne retire rien sans confirmation", async () => {
  vi.stubGlobal("confirm", vi.fn(() => false));
  const f = server({ onwrite: () => json({ proposal_id: null, needs_generation: false }) });
  render(Goal);
  await fireEvent.click(within((await items())[0]).getByRole("button", { name: "Retirer" }));
  expect(writes(f)).toEqual([]);
});

test("modifier un objectif ouvre son dialogue avec la priorité", async () => {
  server();
  render(Goal);
  await fireEvent.click(within((await items())[1]).getByRole("button", { name: "Modifier" }));
  const dialog = within(screen.getByRole("dialog", { name: "Modifier l'objectif" }));
  expect(dialog.getByLabelText("Date de la course")).toHaveValue("2027-03-01");
  expect(dialog.getByRole("radio", { name: "Principal" })).toBeChecked();
});

test("les objectifs courus sont repliés en bas", async () => {
  const past = mkGoal({ id: 9, race_date: "2026-10-04", status: "done", distance_km: 10 });
  server({ goals: [past, principal] });
  render(Goal);
  expect(await items()).toHaveLength(1);
  const done = screen.getByText("Objectifs courus").closest("details")!;
  expect(done).not.toHaveAttribute("open");
  expect(done).toHaveTextContent("Course sur route de 10 km");
});
