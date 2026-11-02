import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import GoalEditDialog from "./GoalEditDialog.svelte";
import type { Goal } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const goal: Goal = {
  id: 3, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2027-03-01", sessions_per_week: 4,
  plan_start: "2027-01-01", plan_accepted: true, gpx_summary: null, target_time_s: 6720, target_source: "claude",
};

function mock(status = 200, body: unknown = { goal, proposal_id: 9 }) {
  const f = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", f);
  return f;
}
const patchBody = (f: ReturnType<typeof mock>) =>
  JSON.parse((f.mock.calls.find((c) => (c[1] as RequestInit).method === "PATCH")![1] as RequestInit).body as string);

const open = (props = {}) => render(GoalEditDialog, { goal, today: "2027-01-10", ...props });

test("prefills date and target time", () => {
  open();
  expect(screen.getByLabelText("Date de la course")).toHaveValue("2027-03-01");
  expect(screen.getByLabelText("Temps visé (h:mm)")).toHaveValue("1:52");
  expect(screen.getByLabelText("Date de la course")).toHaveAttribute("min", "2027-01-11");
});

test("sends only changed fields", async () => {
  const f = mock();
  const onsaved = vi.fn();
  open({ onsaved });
  await fireEvent.input(screen.getByLabelText("Temps visé (h:mm)"), { target: { value: "1:55" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(onsaved).toHaveBeenCalledWith(9));
  expect(patchBody(f)).toEqual({ target_time: "1:55" });
});

test("shows the new-goal hint", () => {
  open();
  expect(screen.getByText("Pour changer la distance ou le type de course, crée un nouvel objectif.")).toBeVisible();
});

test("keeps dialog open with error on failure", async () => {
  mock(422, { detail: "Aucune modification" });
  const onsaved = vi.fn();
  open({ onsaved });
  await fireEvent.input(screen.getByLabelText("Date de la course"), { target: { value: "2027-03-08" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(onsaved).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeVisible();
});

test("no change or invalid time disables save", async () => {
  open();
  const save = screen.getByRole("button", { name: "Enregistrer" });
  expect(save).toBeDisabled();
  await fireEvent.input(screen.getByLabelText("Temps visé (h:mm)"), { target: { value: "abc" } });
  expect(save).toBeDisabled();
  await fireEvent.input(screen.getByLabelText("Temps visé (h:mm)"), { target: { value: "1:55" } });
  expect(save).toBeEnabled();
});
