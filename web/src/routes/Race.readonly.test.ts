import { render, screen, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";

vi.mock("../lib/mode", () => ({ READONLY: true }));
vi.mock("../components/stats/EChart.svelte", () => import("../test/EChartStub.svelte"));

const fx = await vi.hoisted(async () => (await import("../lib/turso/__fixtures__/expected.json")).default.active as Record<string, any>);
const copy = vi.hoisted(() => ({ view: null as any }));
vi.mock("../lib/turso", () => ({ raceView: async () => copy.view }));

import Race from "./Race.svelte";
import type { Goal, RaceView } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const goal: Goal = fx.status.goals[0];
const trailGoal: Goal = fx.status.goals[1];

test("readonly hides settings and buttons, keeps the guide and the stale advice", async () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  copy.view = fx.race["1"] as RaceView;
  render(Race, { goals: [goal], goalId: goal.id });
  expect(await screen.findByRole("region", { name: "Pendant la course" })).toBeVisible();
  expect(screen.getByText(/Mis à jour le/)).toHaveTextContent("11");
  expect(screen.getByText("Objectif modifié depuis : redemande les conseils")).toBeVisible();
  expect(screen.getByText("Texte du conseil 1.")).toBeVisible();
  expect(screen.queryByRole("region", { name: "Réglages" })).toBeNull();
  for (const name of [/Modifier l'objectif/, /Actualiser/, /Enregistrer/, /Envoyer à la montre/, /conseils du coach/i]) {
    expect(screen.queryByRole("button", { name })).toBeNull();
  }
  expect(screen.queryByLabelText("Heure de départ")).toBeNull();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("readonly trail: no aid station editing", async () => {
  copy.view = fx.race["2"] as RaceView;
  render(Race, { goals: [trailGoal], goalId: trailGoal.id });
  await screen.findByRole("region", { name: "Pendant la course" });
  expect(screen.queryByRole("heading", { name: "Ravitaillements" })).toBeNull();
  expect(screen.queryByRole("button", { name: /ravito|Réimporter/i })).toBeNull();
});

test("shows the desktop hint when the snapshot is missing or unreadable", async () => {
  copy.view = null; // raceView renvoie null pour une copie absente ou illisible
  render(Race, { goals: [goal], goalId: goal.id });
  expect(await screen.findByText("Ouvre le Jour J sur l'ordinateur pour préparer ce guide.")).toBeVisible();
  expect(screen.queryByRole("region", { name: "Pendant la course" })).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});
