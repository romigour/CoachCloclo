import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Goal from "./Goal.svelte";

afterEach(() => {
  vi.unstubAllGlobals();
  location.hash = "";
});

const EMPTY = { cycle: null, goals: [], horizon: [], open_injury: null, weeks: [] };
const noPlan = () =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(EMPTY), { status: 200 })));

test("goal form bounds match the backend (2 to 7 sessions, positive distance)", () => {
  noPlan();
  render(Goal);
  const perWeek = within(screen.getByRole("group", { name: "Séances par semaine" }));
  expect(perWeek.getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["2", "3", "4", "5", "6", "7"]);
  const distance = screen.getByLabelText("Distance (km)") as HTMLInputElement;
  expect(Number(distance.min)).toBeGreaterThan(0);
});

test("distance presets fill the distance field", async () => {
  noPlan();
  render(Goal);
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

test("target time defaults to Claude estimate", () => {
  noPlan();
  render(Goal);
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

test("an accepted plan shows the goal in progress and opens the plan settings", async () => {
  const cycle = mkCycle({ plan_accepted: true, long_run_day: "dimanche" });
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") return new Response(JSON.stringify({ cycle, proposal_id: 9 }), { status: 200 });
    return new Response(JSON.stringify(mkPlan(mkGoal(), cycle)), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  const onchanged = vi.fn();
  render(Goal, { onchanged });
  expect(await screen.findByRole("heading", { name: "Objectif en cours" })).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: "Réglages du plan" }));
  const dialog = within(screen.getByRole("dialog", { name: "Réglages du plan" }));
  expect(dialog.getByLabelText("Jour de la sortie longue")).toHaveValue("dimanche");
  await fireEvent.click(dialog.getByRole("checkbox", { name: /Inclure du vélo/ }));
  await fireEvent.click(dialog.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(location.hash).toBe("#/proposal"));
  expect(onchanged).toHaveBeenCalled();
  const patch = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === "PATCH")!;
  expect(patch[0]).toBe("/api/cycle");
});
