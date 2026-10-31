import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import SessionCard from "./SessionCard.svelte";
import type { Activity, Session } from "../lib/api";

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
