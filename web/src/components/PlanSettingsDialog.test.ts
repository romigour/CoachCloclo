import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import PlanSettingsDialog from "./PlanSettingsDialog.svelte";
import type { Cycle } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const cycle: Cycle = {
  id: 2, status: "active", plan_start: "2027-01-04", end_date: "2027-03-01", sessions_per_week: 4,
  available_days: ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"], long_run_day: "dimanche",
  include_bike: false, plan_accepted: true, needs_generation: false,
};

function mock(status = 200, body: unknown = { cycle, proposal_id: 9 }) {
  const f = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", f);
  return f;
}
const patchCall = (f: ReturnType<typeof mock>) =>
  f.mock.calls.find((c) => ((c as unknown as [string, RequestInit])[1]).method === "PATCH") as unknown as [string, RequestInit];

const open = (props = {}) => render(PlanSettingsDialog, { cycle, ...props });

test("enregistre les jours et le vélo puis appelle onsaved avec l'id de proposition", async () => {
  const f = mock();
  const onsaved = vi.fn();
  open({ onsaved });
  expect(screen.getByRole("dialog", { name: "Réglages du plan" })).toBeVisible();
  const save = screen.getByRole("button", { name: "Enregistrer" });
  expect(save).toBeDisabled(); // rien n'a changé
  await fireEvent.click(screen.getByRole("checkbox", { name: "Lundi" }));
  await fireEvent.click(screen.getByRole("checkbox", { name: /Inclure du vélo/ }));
  await fireEvent.click(save);
  await waitFor(() => expect(onsaved).toHaveBeenCalledWith(9));
  const [url, init] = patchCall(f);
  expect(url).toBe("/api/cycle");
  expect(JSON.parse(init.body as string)).toEqual({
    available_days: ["mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    include_bike: true,
  });
});

test("choisir Aucun envoie un jour de sortie longue vide", async () => {
  const f = mock();
  const onsaved = vi.fn();
  open({ onsaved });
  await fireEvent.change(screen.getByLabelText("Jour de la sortie longue"), { target: { value: "" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(onsaved).toHaveBeenCalled());
  expect(JSON.parse(patchCall(f)[1].body as string)).toEqual({ long_run_day: "" });
});

test("refuse moins de jours que de séances par semaine", async () => {
  open();
  for (const d of ["Lundi", "Mardi", "Mercredi", "Jeudi"]) await fireEvent.click(screen.getByRole("checkbox", { name: d }));
  expect(screen.getByText("Coche au moins 4 jours")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
});

test("garde le dialogue ouvert avec l'erreur en cas d'échec", async () => {
  mock(422, { detail: "Aucune modification" });
  const onsaved = vi.fn();
  open({ onsaved });
  await fireEvent.click(screen.getByRole("checkbox", { name: /Inclure du vélo/ }));
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByText("Aucune modification")).toBeVisible();
  expect(onsaved).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog")).toBeVisible();
});

test("Annuler ferme sans rien envoyer", async () => {
  const f = mock();
  const onclose = vi.fn();
  open({ onclose });
  await fireEvent.click(screen.getByRole("button", { name: "Annuler" }));
  expect(onclose).toHaveBeenCalled();
  expect(f).not.toHaveBeenCalled();
});
