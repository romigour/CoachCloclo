import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import EventDialog from "./EventDialog.svelte";
import type { Cycle, Session, Week } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const cycle: Cycle = {
  id: 3, status: "active", plan_start: "2026-10-26", end_date: "2026-12-06", sessions_per_week: 3,
  available_days: ["lundi", "mercredi", "samedi"], long_run_day: null, include_bike: false, plan_accepted: true,
  needs_generation: false,
};
const session = (id: number, title: string): Session => ({
  id, order: id, type: "EF", title, description: "", target_kind: "pace", status: "todo", suggested_day: "mercredi",
  sport: "run", scheduled_date: null, chaining_note: null, sync_error: null, steps: [],
});
const sessions = [session(7, "Endurance 50 min"), session(8, "Seuil 3 × 10 min")];
const weeks: Week[] = [
  { week_index: 1, week_monday: "2026-10-26", sessions: [] },
  { week_index: 2, week_monday: "2026-11-02", sessions: [] },
  { week_index: 3, week_monday: "2026-11-09", sessions: [] },
];

function mock(responses: Record<string, unknown>) {
  const f = vi.fn(async (url: string) => {
    const body = responses[url];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", f);
  return f;
}
const callTo = (f: ReturnType<typeof mock>, path: string) => f.mock.calls.find((c) => c[0] === path)!;
const bodyOf = (f: ReturnType<typeof mock>, path: string) => JSON.parse((callTo(f, path)[1] as RequestInit).body as string);

const open = (props = {}) => render(EventDialog, { cycle, weeks, sessions, today: "2026-11-03", ...props });
const choose = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

test("first step offers the four kinds", () => {
  open();
  for (const n of ["Indisponible", "Blessure / maladie", "Semaine allégée", "Fatigue / séance ratée"])
    expect(screen.getByRole("button", { name: n })).toBeVisible();
});

test("unavailable asks for start and end", async () => {
  open();
  await choose("Indisponible");
  expect(screen.getByLabelText("Début")).toBeVisible();
  expect(screen.getByLabelText("Fin")).toBeVisible();
  expect(screen.queryByLabelText("Séance ratée (facultatif)")).toBeNull();
});

test("injury has an optional resume date", async () => {
  open();
  await choose("Blessure / maladie");
  expect(screen.getByLabelText("Reprise prévue (facultatif)")).toBeVisible();
  expect(screen.getByRole("button", { name: "Envoyer" })).toBeEnabled();
});

test("light week asks for the week, max sessions and the plan's days", async () => {
  open();
  await choose("Semaine allégée");
  expect(screen.getByLabelText("Semaine")).toBeVisible();
  expect(screen.getByLabelText("Nombre de séances maximum")).toBeVisible();
  expect(screen.getAllByRole("checkbox").map((c) => c.nextElementSibling?.textContent)).toEqual([
    "Lundi", "Mercredi", "Samedi",
  ]);
  // la semaine 1 est terminée
  expect(screen.queryByRole("option", { name: /^Semaine 1 / })).toBeNull();
});

test("fatigue offers the sessions and no dates", async () => {
  open();
  await choose("Fatigue / séance ratée");
  expect(screen.getByRole("option", { name: "Seuil 3 × 10 min" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Début")).toBeNull();
});

test("end before start blocks sending", async () => {
  const f = mock({});
  open();
  await choose("Indisponible");
  await fireEvent.input(screen.getByLabelText("Début"), { target: { value: "2026-11-10" } });
  await fireEvent.input(screen.getByLabelText("Fin"), { target: { value: "2026-11-05" } });
  expect(screen.getByRole("alert")).toHaveTextContent("La fin doit être après le début");
  expect(screen.getByRole("button", { name: "Envoyer" })).toBeDisabled();
  expect(f).not.toHaveBeenCalled();
});

test("light week sends the chosen monday and max_sessions", async () => {
  const f = mock({ "/api/cycle/events": { event_id: 1, proposal_id: 12, error: null } });
  const onproposal = vi.fn();
  open({ onproposal });
  await choose("Semaine allégée");
  await fireEvent.change(screen.getByLabelText("Semaine"), { target: { value: "2026-11-09" } });
  await fireEvent.input(screen.getByLabelText("Nombre de séances maximum"), { target: { value: "2" } });
  await fireEvent.click(screen.getByRole("checkbox", { name: "Mercredi" }));
  await fireEvent.click(screen.getByRole("button", { name: "Envoyer" }));
  await waitFor(() => expect(onproposal).toHaveBeenCalledWith(12));
  expect(bodyOf(f, "/api/cycle/events")).toEqual({
    kind: "light_week", start_date: "2026-11-09", end_date: "2026-11-15", max_sessions: 2, days: ["mercredi"],
  });
});

test("fatigue sends the session and the note", async () => {
  const f = mock({ "/api/cycle/events": { event_id: 1, proposal_id: 5, error: null } });
  open();
  await choose("Fatigue / séance ratée");
  await fireEvent.change(screen.getByLabelText("Séance ratée (facultatif)"), { target: { value: "8" } });
  await fireEvent.input(screen.getByLabelText("Précisions (facultatif)"), { target: { value: " jambes lourdes " } });
  await fireEvent.click(screen.getByRole("button", { name: "Envoyer" }));
  await waitFor(() => expect(f).toHaveBeenCalled());
  expect(bodyOf(f, "/api/cycle/events")).toEqual({ kind: "fatigue", session_id: 8, note: "jambes lourdes" });
});

test("a Claude error keeps the event and Réessayer asks for the adjustment", async () => {
  const f = mock({
    "/api/cycle/events": { event_id: 1, proposal_id: null, error: "Claude indisponible" },
    "/api/cycle/adjust": { proposal_id: 21 },
  });
  const onproposal = vi.fn();
  open({ onproposal });
  await choose("Fatigue / séance ratée");
  await fireEvent.click(screen.getByRole("button", { name: "Envoyer" }));
  expect(await screen.findByText("Claude indisponible")).toBeVisible();
  expect(onproposal).not.toHaveBeenCalled();
  await fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  await waitFor(() => expect(onproposal).toHaveBeenCalledWith(21));
  expect(f.mock.calls.filter((c) => c[0] === "/api/cycle/events")).toHaveLength(1);
  expect((callTo(f, "/api/cycle/adjust")[1] as RequestInit).method).toBe("POST");
});

test("injury sends the day before the planned resume as the last blocked day", async () => {
  const f = mock({ "/api/cycle/events": { event_id: 1, proposal_id: 5, error: null } });
  open();
  await choose("Blessure / maladie");
  await fireEvent.input(screen.getByLabelText("Reprise prévue (facultatif)"), { target: { value: "2026-11-10" } });
  await fireEvent.click(screen.getByRole("button", { name: "Envoyer" }));
  await waitFor(() => expect(f).toHaveBeenCalled());
  expect(bodyOf(f, "/api/cycle/events")).toEqual({ kind: "injury", start_date: "2026-11-03", end_date: "2026-11-09" });
});

test("injury resuming the day it starts keeps end_date at the start", async () => {
  const f = mock({ "/api/cycle/events": { event_id: 1, proposal_id: 5, error: null } });
  open();
  await choose("Blessure / maladie");
  await fireEvent.input(screen.getByLabelText("Reprise prévue (facultatif)"), { target: { value: "2026-11-03" } });
  await fireEvent.click(screen.getByRole("button", { name: "Envoyer" }));
  await waitFor(() => expect(f).toHaveBeenCalled());
  expect(bodyOf(f, "/api/cycle/events")).toEqual({ kind: "injury", start_date: "2026-11-03", end_date: "2026-11-03" });
});
