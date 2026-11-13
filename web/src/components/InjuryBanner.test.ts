import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import InjuryBanner from "./InjuryBanner.svelte";
import type { CoachEvent } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const injury: CoachEvent = {
  id: 4, kind: "injury", start_date: "2026-11-01", end_date: null, max_sessions: null, days: null,
  session_id: null, note: null,
};

function mock(result: unknown) {
  const f = vi.fn(async (url: string, _init?: RequestInit) => {
    const body = url.endsWith("/resume") ? result : { proposal_id: 12 };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", f);
  return f;
}

test("no banner without an open injury", () => {
  render(InjuryBanner, { injury: null });
  expect(screen.queryByText(/Arrêt depuis/)).toBeNull();
});

test("resuming sends the day's date by default", async () => {
  const f = mock({ event_id: 4, proposal_id: 8, error: null });
  const onproposal = vi.fn();
  const onresumed = vi.fn();
  render(InjuryBanner, { injury, today: "2026-11-03", onproposal, onresumed });
  expect(screen.getByText("Arrêt depuis le 01/11")).toBeVisible();
  await fireEvent.click(screen.getByRole("button", { name: "Signaler la reprise" }));
  expect(screen.getByLabelText("Date de reprise")).toHaveValue("2026-11-03");
  await fireEvent.click(screen.getByRole("button", { name: "Confirmer la reprise" }));
  await waitFor(() => expect(onproposal).toHaveBeenCalledWith(8));
  const call = f.mock.calls.find((c) => c[0] === "/api/events/4/resume")!;
  expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({ date: "2026-11-03" });
  expect(onresumed).toHaveBeenCalled();
});

test("a Claude failure offers a retry that requests an adjustment", async () => {
  const f = mock({ event_id: 4, proposal_id: null, error: "Claude indisponible" });
  const onproposal = vi.fn();
  render(InjuryBanner, { injury, today: "2026-11-03", onproposal });
  await fireEvent.click(screen.getByRole("button", { name: "Signaler la reprise" }));
  await fireEvent.click(screen.getByRole("button", { name: "Confirmer la reprise" }));
  await screen.findByText("Claude indisponible");
  await fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  await waitFor(() => expect(onproposal).toHaveBeenCalledWith(12));
  expect(f.mock.calls.some((c) => c[0] === "/api/cycle/adjust")).toBe(true);
});
