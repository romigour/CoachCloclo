import { render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.svelte";

const calls: { url: string; method: string }[] = [];
let syncDone: (() => void) | null = null;

const plan = {
  goal: { id: 1, type: "route", distance_km: 21, d_plus_m: 0, race_date: "2027-02-07", sessions_per_week: 3, plan_start: "2026-11-09", plan_accepted: true, gpx_summary: null },
  weeks: [],
};

beforeEach(() => {
  calls.length = 0;
  location.hash = "#/plan";
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method });
    let body: unknown = {};
    if (url === "/api/status") body = { garmin: "ok", llm_mode: "cli", pending_proposal_id: null, goal: plan.goal };
    else if (url === "/api/plan") body = plan;
    else if (url === "/api/sync") {
      await new Promise<void>((r) => (syncDone = r));
      body = { new_activities: 0, matched: 0, missed: 0, proposal_id: null };
    }
    return new Response(JSON.stringify(body), { status: 200 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

const syncs = () => calls.filter((c) => c.url === "/api/sync" && c.method === "POST").length;

test("auto-sync runs once per load, shows the Claude message, and survives navigation", async () => {
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
  await screen.findByText("Programme", { selector: "h1" });
  await new Promise((r) => setTimeout(r, 50));
  expect(syncs()).toBe(1);
});
