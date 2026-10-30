import { render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.svelte";

const calls: { url: string; method: string }[] = [];
let syncDone: (() => void) | null = null;
let statusBody: Record<string, unknown> = {};
let statsCalls = 0;
let syncInstant = false;

const idle = { status: "idle", imported: 0, error: null };

const plan = {
  goal: { id: 1, type: "route", distance_km: 21, d_plus_m: 0, race_date: "2027-02-07", sessions_per_week: 3, plan_start: "2026-11-09", plan_accepted: true, gpx_summary: null },
  weeks: [],
};

beforeEach(() => {
  calls.length = 0;
  statsCalls = 0;
  syncInstant = false;
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
    else if (url === "/api/sync") {
      if (!syncInstant) await new Promise<void>((r) => (syncDone = r));
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
