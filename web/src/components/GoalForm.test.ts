import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { expect, test, vi } from "vitest";
import GoalForm from "./GoalForm.svelte";
import type { Cycle } from "../lib/api";

const cycle: Cycle = {
  id: 1, status: "active", plan_start: "2027-01-04", end_date: "2027-03-01", sessions_per_week: 4,
  available_days: ["lundi", "mercredi", "samedi", "dimanche"], long_run_day: null, include_bike: false,
  plan_accepted: true, needs_generation: false,
};

const priority = () => within(screen.getByRole("group", { name: "Priorité" }));

test("the first goal is Principal by default, with the plan settings", () => {
  render(GoalForm, { cycle: null, firstGoal: true, today: "2027-01-10" });
  expect(priority().getAllByRole("radio").map((r) => r.getAttribute("value"))).toEqual(["principal", "secondaire", "plaisir"]);
  expect(priority().getByRole("radio", { name: "Principal" })).toBeChecked();
  expect(screen.getByRole("group", { name: "Séances par semaine" })).toBeVisible();
  expect(screen.getByRole("checkbox", { name: /Inclure du vélo/ })).toBeVisible();
  expect(screen.getByRole("button", { name: "Générer le plan avec Claude" })).toBeVisible();
});

test("another goal is Secondaire by default and never shows the plan settings", () => {
  render(GoalForm, { cycle, firstGoal: false, today: "2027-01-10" });
  expect(priority().getByRole("radio", { name: "Secondaire" })).toBeChecked();
  expect(screen.queryByRole("group", { name: "Séances par semaine" })).toBeNull();
  expect(screen.queryByRole("group", { name: "Jours possibles" })).toBeNull();
  expect(screen.queryByLabelText("Jour de la sortie longue")).toBeNull();
  expect(screen.queryByRole("checkbox", { name: /Inclure du vélo/ })).toBeNull();
  expect(screen.getByRole("button", { name: "Ajouter l'objectif" })).toBeVisible();
});

test("with a cycle, submits only the goal fields and the chosen priority", async () => {
  const onsubmit = vi.fn();
  render(GoalForm, { cycle, firstGoal: false, today: "2027-01-10", onsubmit });
  await fireEvent.click(screen.getByRole("radio", { name: /Trail/ }));
  await fireEvent.input(screen.getByLabelText("Distance (km)"), { target: { value: "20" } });
  await fireEvent.input(screen.getByLabelText("Dénivelé positif (m)"), { target: { value: "800" } });
  await fireEvent.input(screen.getByLabelText("Date de la course"), { target: { value: "2027-02-14" } });
  await fireEvent.click(priority().getByRole("radio", { name: "Plaisir" }));
  await fireEvent.submit(screen.getByRole("button", { name: "Ajouter l'objectif" }).closest("form")!);
  expect(onsubmit).toHaveBeenCalledWith({
    type: "trail", distance_km: 20, d_plus_m: 800, race_date: "2027-02-14", target_time: undefined, gpx: null,
    priority: "plaisir",
  });
});

test("cancel is offered when adding to an existing list", async () => {
  const oncancel = vi.fn();
  render(GoalForm, { cycle, firstGoal: false, today: "2027-01-10", oncancel });
  await fireEvent.click(screen.getByRole("button", { name: "Annuler" }));
  expect(oncancel).toHaveBeenCalled();
});
