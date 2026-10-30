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

test("Corriger lists the week's activities as buttons and re-matches in one click", async () => {
  const calls: { url: string; body?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body as string });
    return new Response("{}", { status: 200 });
  }));
  const onchanged = vi.fn();
  render(SessionCard, {
    session, weekMonday: "2026-11-09", onchanged,
    activities: [act(1, "2026-11-10", 7), act(2, "2026-11-12", null)],
  });
  expect(screen.getByText(/mar\. 10\/11 · 52 min · 10,2 km/)).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: "Corriger" }));
  await fireEvent.click(screen.getByRole("button", { name: "jeu. 12/11 · 52 min · 10,2 km" }));
  await waitFor(() => expect(onchanged).toHaveBeenCalled());
  expect(calls[0].url).toBe("/api/activities/2/match");
  expect(JSON.parse(calls[0].body!)).toEqual({ session_id: 7 });
});

test("Aucune unmatches the current activity", async () => {
  const calls: { url: string; body?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body as string });
    return new Response("{}", { status: 200 });
  }));
  render(SessionCard, { session, weekMonday: "2026-11-09", activities: [act(1, "2026-11-10", 7)] });
  await fireEvent.click(screen.getByRole("button", { name: "Corriger" }));
  await fireEvent.click(screen.getByRole("button", { name: "Aucune" }));
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].url).toBe("/api/activities/1/match");
  expect(JSON.parse(calls[0].body!)).toEqual({ session_id: null });
});

test("a missed session offers no export (the backend only exports todo sessions)", () => {
  render(SessionCard, { session: { ...session, status: "missed", scheduled_date: null }, weekMonday: "2026-11-09" });
  expect(screen.queryByRole("button", { name: "Envoyer sur la montre" })).toBeNull();
  render(SessionCard, { session: { ...session, id: 8, status: "todo", scheduled_date: null }, weekMonday: "2026-11-09" });
  expect(screen.getByRole("button", { name: "Envoyer sur la montre" })).toBeVisible();
});
