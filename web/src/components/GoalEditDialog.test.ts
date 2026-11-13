import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import GoalEditDialog from "./GoalEditDialog.svelte";
import type { Goal } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const goal: Goal = {
  id: 3, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2027-03-01", priority: "principal", status: "active",
  gpx_summary: null, target_time_s: 6720, target_source: "claude",
};

const RESULT = { goal, proposal_id: 9, needs_generation: false };
function mock(status = 200, body: unknown = RESULT) {
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
  await waitFor(() => expect(onsaved).toHaveBeenCalledWith(RESULT));
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

test("only date and target time: plan settings live in their own dialog", () => {
  open();
  expect(screen.queryByRole("group", { name: "Jours possibles" })).toBeNull();
  expect(screen.queryByLabelText("Jour de la sortie longue")).toBeNull();
  expect(screen.queryByRole("checkbox", { name: /Inclure du vélo/ })).toBeNull();
});

test("sends the new race date to the goal endpoint", async () => {
  const f = mock();
  const onsaved = vi.fn();
  open({ onsaved });
  await fireEvent.input(screen.getByLabelText("Date de la course"), { target: { value: "2027-03-08" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(onsaved).toHaveBeenCalledWith(RESULT));
  const calls = f.mock.calls as unknown as [string, RequestInit][];
  expect(calls.find(([, i]) => i.method === "PATCH")![0]).toBe("/api/goals/3");
  expect(patchBody(f)).toEqual({ race_date: "2027-03-08" });
});

test("the priority is prefilled and sent only when changed", async () => {
  const f = mock();
  const onsaved = vi.fn();
  open({ onsaved });
  const group = screen.getByRole("group", { name: "Priorité" });
  expect(within(group).getByRole("radio", { name: "Principal" })).toBeChecked();
  await fireEvent.click(within(group).getByRole("radio", { name: "Plaisir" }));
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(onsaved).toHaveBeenCalledWith(RESULT));
  expect(patchBody(f)).toEqual({ priority: "plaisir" });
});

test("shows the gap message returned by the server", async () => {
  const msg = "Course sur route de 10 km du 14/03/2027 (Secondaire) est à 13 jours : passe l'un des deux en Plaisir ou déplace-le";
  mock(422, { code: "invalid", detail: msg });
  open();
  await fireEvent.click(within(screen.getByRole("group", { name: "Priorité" })).getByRole("radio", { name: "Secondaire" }));
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(msg);
});
