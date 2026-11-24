import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Program from "./Program.svelte";
import Week from "./Week.svelte";

afterEach(() => vi.unstubAllGlobals());

const s = (id: number, title: string, suggested_day: string, status: string) => ({
  id, order: id, type: "seuil", title, description: `Consigne ${id}`, target_kind: "pace", status, suggested_day,
  sport: "run", scheduled_date: null, chaining_note: null, sync_error: null,
  steps: [{ kind: "active", duration_s: 1800, zone: "seuil" }],
});
const cycle = {
  id: 1, status: "active", plan_start: "2026-10-26", end_date: "2026-11-08", sessions_per_week: 3, available_days: [],
  long_run_day: null, include_bike: false, plan_accepted: true, needs_generation: false, adjust_due: false,
};
const plan = {
  cycle, horizon: [], open_injury: null,
  goals: [{
    id: 1, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2026-11-08", priority: "principal", status: "active",
    gpx_summary: null, target_time_s: null, target_source: null,
  }],
  weeks: [
    { week_index: 1, week_monday: "2026-10-26", sessions: [s(1, "Footing", "lundi", "done")] },
    { week_index: 2, week_monday: "2026-11-02", sessions: [s(2, "Seuil long", "mardi", "todo")] },
  ],
};
const act = {
  id: 9, date: "2026-10-26", type_key: "running", duration_s: 2640, distance_m: 8300, d_plus_m: 0, avg_hr: 139,
  session_id: 1, match_source: "manual",
};
function mock(body: unknown = plan) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    new Response(JSON.stringify(url.startsWith("/api/plan") ? body : url.startsWith("/api/activities") ? [act] : []), { status: 200 })));
}

test("toutes les semaines, la course et le retour à Ma semaine", async () => {
  mock();
  render(Program, { today: "2026-10-28" });
  expect(await screen.findByRole("button", { name: /Footing/ })).toBeVisible();
  expect(screen.getByRole("button", { name: /Seuil long/ })).toBeVisible();
  expect(screen.getByRole("note", { name: /^Course/ })).toBeVisible();
  expect(screen.getByText(/1 \/ 2 séances faites/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Retour" })).toHaveAttribute("href", "#/week");
});

test("une séance ouvre son détail en consultation ; Échap le ferme et rend le focus", async () => {
  mock();
  render(Program, { today: "2026-10-28" });
  const button = await screen.findByRole("button", { name: /Footing/ });
  button.focus();
  await fireEvent.click(button);
  const dialog = screen.getByRole("dialog", { name: "Détail de la séance" });
  expect(within(dialog).getByText("Consigne 1")).toBeVisible();
  expect(within(dialog).getByText("Réalisée")).toBeVisible();
  expect(await within(dialog).findByText(/lun\. 26\/10/)).toBeVisible();
  expect(within(dialog).getAllByRole("button")).toHaveLength(1); // fermer, aucune action
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "Fermer le détail" })).toHaveFocus());
  await fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(button).toHaveFocus();
});

test("un brouillon n'est pas affiché", async () => {
  mock({ ...plan, cycle: { ...cycle, plan_accepted: false } });
  render(Program, { today: "2026-10-28" });
  expect(await screen.findByText(/Aucun programme à afficher/)).toBeVisible();
});

test("Ma semaine mène au programme complet", async () => {
  mock();
  render(Week, { today: "2026-10-28" });
  expect(await screen.findByRole("link", { name: "Programme complet" })).toHaveAttribute("href", "#/program");
});

test("retour sur le programme : affiché sans attendre ; une seule lecture d'activités par affichage", async () => {
  mock();
  const first = render(Program, { today: "2026-10-28", version: 0 });
  await fireEvent.click(await screen.findByRole("button", { name: /Footing/ }));
  const reads = () => vi.mocked(fetch).mock.calls.filter((c) => String(c[0]).startsWith("/api/activities")).length;
  await waitFor(() => expect(reads()).toBe(1));
  await new Promise((r) => setTimeout(r, 20));
  await first.rerender({ version: 1 }); // plan relu, fenêtre ouverte
  await new Promise((r) => setTimeout(r, 20));
  expect(reads()).toBe(2);
  first.unmount();
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  render(Program, { today: "2026-10-28" });
  await Promise.resolve();
  expect(screen.getByRole("button", { name: /Footing/ })).toBeVisible();
});
