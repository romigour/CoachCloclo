import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import EventList from "./EventList.svelte";
import type { CoachEvent } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const ev = (id: number, over: Partial<CoachEvent>): CoachEvent => ({
  id, kind: "unavailable", start_date: "2026-11-05", end_date: "2026-11-08", max_sessions: null, days: null,
  session_id: null, note: null, ...over,
});

function mock(list: CoachEvent[]) {
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method === "DELETE") return json({ status: "deleted" });
    if (url.endsWith("/adjust")) return json({ proposal_id: 9 });
    return json(list);
  });
  vi.stubGlobal("fetch", f);
  return f;
}

test("past events are hidden, current and open-ended ones shown", async () => {
  const f = mock([
    ev(1, { start_date: "2026-10-18", end_date: "2026-10-20" }),
    ev(2, { kind: "injury", start_date: "2026-11-01", end_date: null }),
    ev(3, {}),
  ]);
  render(EventList, { today: "2026-11-03" });
  await screen.findByText(/Blessure \/ maladie · depuis le 01\/11/);
  expect(f.mock.calls[0][0]).toBe("/api/cycle/events");
  expect(screen.getByText(/Indisponible · du 05\/11 au 08\/11/)).toBeVisible();
  expect(screen.queryByText(/18\/10/)).toBeNull();
});

test("deleting asks whether to recompute, and yes requests an adjustment", async () => {
  const f = mock([ev(3, {})]);
  const onproposal = vi.fn();
  const onchanged = vi.fn();
  render(EventList, { today: "2026-11-03", onproposal, onchanged });
  await fireEvent.click(await screen.findByRole("button", { name: "Supprimer" }));
  expect(await screen.findByText("Recalculer le plan ?")).toBeVisible();
  expect(f.mock.calls.some((c) => c[0] === "/api/events/3" && (c[1] as RequestInit).method === "DELETE")).toBe(true);
  await waitFor(() => expect(onchanged).toHaveBeenCalled());
  await fireEvent.click(screen.getByRole("button", { name: "Oui" }));
  await waitFor(() => expect(onproposal).toHaveBeenCalledWith(9));
  expect(f.mock.calls.some((c) => c[0] === "/api/cycle/adjust")).toBe(true);
});
