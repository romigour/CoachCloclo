import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.svelte";

const calls: { url: string; method: string }[] = [];
let syncDone: (() => void) | null = null;
let statusBody: Record<string, unknown> = {};
let statsCalls = 0;
let syncInstant = false;
let syncFails = false;
let afterSync: (() => void) | null = null;

const idle = { status: "idle", imported: 0, error: null };

const plan = {
  goal: { id: 1, type: "route", distance_km: 21, d_plus_m: 0, race_date: "2027-02-07", sessions_per_week: 3, plan_start: "2026-11-09", plan_accepted: true, gpx_summary: null },
  weeks: [],
};

beforeEach(() => {
  calls.length = 0;
  statsCalls = 0;
  syncInstant = false;
  syncFails = false;
  afterSync = null;
  statusBody = { garmin: "ok", llm_mode: "cli", pending_proposal_id: null, goal: plan.goal, has_activities: false, history: idle };
  location.hash = "";
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    let body: unknown = {};
    if (url === "/api/status") body = statusBody;
    else if (url === "/api/stats/activities") { statsCalls++; body = { activities: [] }; }
    else if (url === "/api/stats/records") body = { records: [] };
    else if (url === "/api/plan") body = plan;
    else if (url === "/api/settings") body = { llm_mode: "cli", anthropic_model: null, anthropic_api_key_set: false };
    else if (url === "/api/garmin/login") body = { status: "ok" };
    else if (url === "/api/sync") {
      if (!syncInstant) await new Promise<void>((r) => (syncDone = r));
      if (syncFails) return new Response(JSON.stringify({ code: "garmin_unavailable", detail: "Garmin coupé" }), { status: 503 });
      afterSync?.();
      body = { new_activities: 0, matched: 0, missed: 0, proposal_id: null };
    }
    return new Response(JSON.stringify(body), { status: 200 });
  }));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const syncs = () => calls.filter((c) => c.url === "/api/sync" && c.method === "POST").length;

test("auto-sync runs once per load, shows the Claude message, and survives navigation", async () => {
  location.hash = "#/plan";
  render(App);
  expect(await screen.findAllByText("Analyse de ta séance par Claude…")).not.toHaveLength(0);
  await waitFor(() => expect(syncs()).toBe(1));
  syncDone!();
  await waitFor(() => expect(screen.queryByRole("status")).toBeNull());

  location.hash = "#/goal";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await screen.findByText("Objectif", { selector: "h1" });
  location.hash = "#/plan";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await screen.findByText("Plan", { selector: "h1" });
  await new Promise((r) => setTimeout(r, 50));
  expect(syncs()).toBe(1);
});

test("default route is stats when activities exist", async () => {
  statusBody = { ...statusBody, has_activities: true };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/stats"));
  syncDone?.();
});

test("default route stays plan without activities", async () => {
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/plan"));
  syncDone?.();
});

test("auto-sync runs without a goal and says Garmin", async () => {
  statusBody = { ...statusBody, goal: null };
  render(App);
  expect(await screen.findAllByText("Synchronisation Garmin…")).not.toHaveLength(0);
  await waitFor(() => expect(syncs()).toBe(1));
  syncDone!();
});

test("polls status while history runs, stops when done, and reloads the stats", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, has_activities: true, history: { status: "running", imported: 3, error: null } };
  location.hash = "#/stats";
  vi.useFakeTimers();
  const { unmount } = render(App);
  await vi.advanceTimersByTimeAsync(100);
  expect(screen.getByText("Import de l'historique : 3 activités…")).toBeTruthy();
  const baseline = statsCalls;
  const statusCalls = () => calls.filter((c) => c.url === "/api/status").length;
  const before = statusCalls();

  statusBody = { ...statusBody, history: { status: "done", imported: 9, error: null } };
  await vi.advanceTimersByTimeAsync(5000);
  expect(statusCalls()).toBe(before + 1);
  expect(statsCalls).toBe(baseline + 1); // import terminé : activités rechargées

  await vi.advanceTimersByTimeAsync(15000);
  expect(statusCalls()).toBe(before + 1); // sondage arrêté
  unmount();
});

test("status polling is cleaned up on unmount", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, history: { status: "running", imported: 0, error: null } };
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
  await screen.findByText("Connexion Garmin");
  await fireEvent.input(screen.getByLabelText("E-mail Garmin"), { target: { value: "a@b.c" } });
  await fireEvent.input(screen.getByLabelText("Mot de passe"), { target: { value: "secret" } });
  await fireEvent.click(screen.getByRole("button", { name: "Se connecter" }));
}

test("first Garmin login syncs, then opens stats once activities exist", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, garmin: "auth_required", goal: null };
  location.hash = "#/setup";
  render(App);
  await screen.findByText("Connexion Garmin");
  expect(syncs()).toBe(0);
  statusBody = { ...statusBody, garmin: "ok" };
  afterSync = () => (statusBody = { ...statusBody, has_activities: true });
  await loginToGarmin();
  await waitFor(() => expect(syncs()).toBe(1));
  await waitFor(() => expect(location.hash).toBe("#/stats"));
});

test("first Garmin login without any activity after sync goes to the goal", async () => {
  syncInstant = true;
  statusBody = { ...statusBody, garmin: "auth_required", goal: null };
  location.hash = "#/setup";
  render(App);
  statusBody = { ...statusBody, garmin: "ok" };
  await loginToGarmin();
  await waitFor(() => expect(syncs()).toBe(1));
  await waitFor(() => expect(location.hash).toBe("#/goal"));
});

test("a failed sync after the first Garmin login stays on settings with its error", async () => {
  syncInstant = true;
  syncFails = true;
  statusBody = { ...statusBody, garmin: "auth_required", goal: null };
  location.hash = "#/setup";
  await new Promise((r) => setTimeout(r, 0)); // laisse passer le hashchange initial (il efface l'erreur)
  render(App);
  statusBody = { ...statusBody, garmin: "ok" };
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
  statusBody = { ...statusBody, has_activities: true, history: { status: "running", imported: 3, error: null } };
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
  statusBody = { ...statusBody, has_activities: true, history: { status: "running", imported: 3, error: null } };
  location.hash = "#/stats";
  vi.useFakeTimers();
  const { unmount } = render(App);
  await vi.advanceTimersByTimeAsync(100);
  const baseline = statsCalls;
  statusBody = { ...statusBody, history: { status: "error", imported: 5, error: "Garmin coupé" } };
  await vi.advanceTimersByTimeAsync(5000);
  expect(statsCalls).toBe(baseline + 1);
  unmount();
});
