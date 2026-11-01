import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import SessionCard from "./SessionCard.svelte";
import type { Activity, Comparison, Session, StepResult } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const session: Session = {
  id: 7, order: 1, type: "EF", title: "Sortie EF", description: "", target_kind: "pace",
  status: "done", suggested_day: "mardi", scheduled_date: "2026-11-10", chaining_note: null, steps: [], sync_error: null,
};
const act = (id: number, date: string, session_id: number | null): Activity => ({
  id, date, type_key: "running", duration_s: 3120, distance_m: 10200, d_plus_m: 0, avg_hr: 150, session_id, match_source: "auto",
});

/** Faux backend : `/activities/free` renvoie `free`, les autres appels `{}`. */
function stubApi(free: Activity[] = []) {
  const calls: { url: string; body?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body as string });
    const body = url.startsWith("/api/activities/free") ? JSON.stringify(free) : "{}";
    return new Response(body, { status: 200 });
  }));
  return calls;
}

test("Corriger lists the free runs of the last 14 days and re-matches in one click", async () => {
  const calls = stubApi([act(2, "2026-11-05", null)]);
  const onchanged = vi.fn();
  render(SessionCard, {
    session, weekMonday: "2026-11-09", onchanged,
    activities: [act(1, "2026-11-10", 7), act(3, "2026-11-12", 9)],
  });
  expect(screen.getByText(/mar\. 10\/11 · 52 min · 10,2 km/)).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: "Corriger" }));
  expect(calls[0].url).toBe("/api/activities/free?days=14");
  await fireEvent.click(await screen.findByRole("button", { name: "jeu. 05/11 · 52 min · 10,2 km" }));
  expect(screen.queryByRole("button", { name: /jeu\. 12\/11/ })).toBeNull(); // liée à une autre séance
  await waitFor(() => expect(onchanged).toHaveBeenCalled());
  expect(calls[1].url).toBe("/api/activities/2/match");
  expect(JSON.parse(calls[1].body!)).toEqual({ session_id: 7 });
});

test("Aucune unmatches the current activity", async () => {
  const calls = stubApi();
  render(SessionCard, { session, weekMonday: "2026-11-09", activities: [act(1, "2026-11-10", 7)] });
  await fireEvent.click(screen.getByRole("button", { name: "Corriger" }));
  await fireEvent.click(await screen.findByRole("button", { name: "Aucune" }));
  await waitFor(() => expect(calls).toHaveLength(2));
  expect(calls[1].url).toBe("/api/activities/1/match");
  expect(JSON.parse(calls[1].body!)).toEqual({ session_id: null });
});

test("an unmatched session can be linked by hand to a free run", async () => {
  const calls = stubApi([act(2, "2026-11-05", null)]);
  render(SessionCard, { session: { ...session, status: "todo", scheduled_date: null }, weekMonday: "2026-11-09" });
  expect(screen.queryByRole("button", { name: "Corriger" })).toBeNull();
  await fireEvent.click(screen.getByRole("button", { name: "Rattacher une activité" }));
  await fireEvent.click(await screen.findByRole("button", { name: "jeu. 05/11 · 52 min · 10,2 km" }));
  await waitFor(() => expect(calls).toHaveLength(2));
  expect(JSON.parse(calls[1].body!)).toEqual({ session_id: 7 });
  expect(screen.queryByRole("button", { name: "Aucune" })).toBeNull();
});

test("an empty list says no free run is available", async () => {
  stubApi();
  render(SessionCard, { session: { ...session, status: "missed", scheduled_date: null }, weekMonday: "2026-11-09" });
  await fireEvent.click(screen.getByRole("button", { name: "Rattacher une activité" }));
  expect(await screen.findByText("Aucune course libre ces 14 derniers jours")).toBeVisible();
});

test("a missed session offers no export (the backend only exports todo sessions)", () => {
  render(SessionCard, { session: { ...session, status: "missed", scheduled_date: null }, weekMonday: "2026-11-09" });
  expect(screen.queryByRole("button", { name: "Envoyer sur la montre" })).toBeNull();
  render(SessionCard, { session: { ...session, id: 8, status: "todo", scheduled_date: null }, weekMonday: "2026-11-09" });
  expect(screen.getByRole("button", { name: "Envoyer sur la montre" })).toBeVisible();
});

const cmpStep = (over: Partial<StepResult>): StepResult => ({
  group: 1, iteration: null, position: 1, kind: "active", planned_duration_s: null, planned_distance_m: 400,
  zone: "VMA", target_low: 220, target_high: 235, done: true, duration_s: 95, distance_m: 412,
  avg_pace_s_km: 228, avg_hr: 172, verdict: "in", ...over,
});
const followed: Comparison = {
  available: true, followed_workout: true, target_kind: "pace", laps: [],
  steps: [
    cmpStep({ group: 1, iteration: 1, position: 1 }),
    cmpStep({ group: 1, iteration: 2, position: 2, verdict: "slow", avg_pace_s_km: 241 }),
    cmpStep({ group: 1, iteration: 3, position: 3, done: false, distance_m: null, avg_pace_s_km: null, avg_hr: null, verdict: null }),
  ],
};

/** Faux backend pour `/sessions/7/comparison`. */
function stubComparison(comparison: Comparison) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    return new Response(JSON.stringify(comparison), { status: 200 });
  }));
  return calls;
}
const withActivity = { session, weekMonday: "2026-11-09", activities: [act(1, "2026-11-10", 7)] };
const open = () => fireEvent.click(screen.getByText("Prévu / réalisé"));

test("Prévu / réalisé loads on first expand and shows verdicts", async () => {
  const calls = stubComparison(followed);
  render(SessionCard, withActivity);
  expect(calls).toHaveLength(0);
  await open();
  expect(await screen.findByText("1/3 fractions dans la cible")).toBeVisible();
  expect(screen.getByText("dans la cible")).toBeVisible();
  expect(screen.getByText("trop lent")).toBeVisible();
  expect(screen.getByText("non réalisée")).toBeVisible();
  expect(screen.getByText("412 m · 3:48/km · 172 bpm", { exact: false })).toBeVisible();
  await open(); // referme
  await open(); // rouvre : pas de seconde requête
  expect(calls).toEqual(["/api/sessions/7/comparison"]);
});

test("degraded comparison lists raw laps", async () => {
  stubComparison({
    available: true, followed_workout: false, target_kind: "pace", steps: [],
    laps: [{ index: 1, duration_s: 300, distance_m: 1000, avg_hr: 150, max_hr: 160, avg_pace_s_km: 300, step_order: null }],
  });
  render(SessionCard, withActivity);
  await open();
  expect(await screen.findByText("Séance non suivie sur la montre : tours bruts")).toBeVisible();
  expect(screen.getByText("1 · 1000 m · 5:00 · 5:00/km · 150 bpm", { exact: false })).toBeVisible();
});

test("no laps yet shows the next-sync hint", async () => {
  stubComparison({ available: false, reason: "no_laps" });
  render(SessionCard, withActivity);
  await open();
  expect(await screen.findByText("Détail par étape disponible après la prochaine synchro")).toBeVisible();
});

test("zero laps shows the empty message", async () => {
  stubComparison({ available: true, followed_workout: false, target_kind: "pace", steps: [], laps: [] });
  render(SessionCard, withActivity);
  await open();
  expect(await screen.findByText("Aucun tour enregistré")).toBeVisible();
});

test("block hidden when not done or readonly", () => {
  render(SessionCard, { ...withActivity, readonly: true });
  expect(screen.queryByText("Prévu / réalisé")).toBeNull();
  render(SessionCard, { ...withActivity, session: { ...session, id: 8, status: "exported" } });
  expect(screen.queryByText("Prévu / réalisé")).toBeNull();
  render(SessionCard, { session, weekMonday: "2026-11-09" }); // aucune activité rattachée
  expect(screen.queryByText("Prévu / réalisé")).toBeNull();
});
