import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { StatActivity } from "../lib/api";

vi.mock("../components/stats/EChart.svelte", () => import("../test/EChartStub.svelte"));

import Stats from "./Stats.svelte";

function act(id: number, date: string, family: StatActivity["family"], duration_s: number, distance_m: number): StatActivity {
  return {
    id, garmin_id: 1000 + id, date, start: `${date}T08:00:00`, name: `Séance ${id}`, family,
    type_key: family === "bike" ? "cycling" : "running",
    duration_s, distance_m, d_plus_m: 50, avg_hr: 140, max_hr: 170, vo2max: null, hr_zones_s: null, race: null,
  };
}

const ACTS = [
  act(1, "2024-05-01", "run", 3600, 10000), // hors des 12 derniers mois
  act(2, "2026-06-15", "bike", 5400, 40000),
  act(3, "2026-10-01", "run", 3000, 9000),
];

let activities: StatActivity[] = ACTS;

beforeEach(() => {
  vi.setSystemTime(new Date(2026, 9, 30));
  activities = ACTS;
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    let body: unknown = {};
    if (url === "/api/stats/activities") body = { activities };
    else if (url === "/api/stats/records") body = { records: [], updated_at: null };
    return new Response(JSON.stringify(body), { status: 200 });
  }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const kpi = async (label: string) => within(await screen.findByRole("group", { name: label }));

test("shows KPIs for the default 12-month period", async () => {
  render(Stats, { history: null, onimport: () => {} });
  expect((await kpi("Séances")).getByText("2")).toBeInTheDocument();
});

test("changing sport filter recomputes", async () => {
  render(Stats, { history: null, onimport: () => {} });
  expect((await kpi("Km de course")).getByText("9")).toBeInTheDocument();
  await fireEvent.change(screen.getByLabelText("Sport"), { target: { value: "bike" } });
  expect((await kpi("Km de course")).getByText("0")).toBeInTheDocument();
  expect((await kpi("Séances")).getByText("1")).toBeInTheDocument();
});

test("empty period shows explicit empty state", async () => {
  activities = [];
  render(Stats, { history: null, onimport: () => {} });
  expect((await screen.findAllByText("Pas assez de données sur cette période")).length).toBeGreaterThan(0);
  expect(screen.queryAllByRole("img")).toHaveLength(0);
});

test("history running banner", async () => {
  render(Stats, { history: { status: "running", imported: 42, error: null }, onimport: () => {} });
  expect(await screen.findByText("Import de l'historique : 42 activités…")).toBeInTheDocument();
});

test("history error banner calls onimport", async () => {
  const onimport = vi.fn();
  render(Stats, { history: { status: "error", imported: 3, error: "Import interrompu" }, onimport });
  expect(await screen.findByText(/Import interrompu/)).toBeInTheDocument();
  await fireEvent.click(screen.getByRole("button", { name: "Reprendre" }));
  expect(onimport).toHaveBeenCalledTimes(1);
});

test("filters survive a throwing localStorage", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("denied");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("denied");
  });
  render(Stats, { history: null, onimport: () => {} });
  expect((await kpi("Séances")).getByText("2")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "12 derniers mois" })).toHaveAttribute("aria-pressed", "true");
});

test("filters are remembered in localStorage", async () => {
  localStorage.setItem("coach.stats.filters", JSON.stringify({ choice: { kind: "all" }, sport: "running", metric: "km" }));
  render(Stats, { history: null, onimport: () => {} });
  // Tout l'historique, course seule : 2 séances (2024 et 2026), pas de variation
  const seances = await kpi("Séances");
  expect(seances.getByText("2")).toBeInTheDocument();
  expect(seances.getByText("—")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Tout" })).toHaveAttribute("aria-pressed", "true");
  await fireEvent.click(screen.getByRole("button", { name: "Réinitialiser" }));
  expect(JSON.parse(localStorage.getItem("coach.stats.filters")!)).toEqual({ choice: { kind: "12m" }, sport: "all", metric: "hours" });
});

const chartClick = (label: RegExp, detail: { dataIndex: number; data?: unknown }) =>
  screen.getByRole("img", { name: label }).dispatchEvent(new CustomEvent("echartclick", { detail: { name: "", ...detail } }));

test("clicking a month bar, then a week bar, narrows the period", async () => {
  render(Stats, { history: null, onimport: () => {} });
  await kpi("Séances");
  // 12 derniers mois → barres mensuelles depuis 2025-10 ; index 8 = juin 2026
  chartClick(/^Volume par mois/, { dataIndex: 8 });
  expect(await screen.findByText(/Du 1 juin 2026 au 30 juin 2026/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Personnalisée" })).toHaveAttribute("aria-pressed", "true");
  expect((await kpi("Séances")).getByText("1")).toBeInTheDocument();
  // 30 jours → barres hebdomadaires depuis le lundi 1er juin ; index 2 = semaine du 15 juin
  chartClick(/^Volume par semaine/, { dataIndex: 2 });
  expect(await screen.findByText(/Du 15 juin 2026 au 21 juin 2026/)).toBeInTheDocument();
});

test("clicking a calendar day narrows the period to that day", async () => {
  render(Stats, { history: null, onimport: () => {} });
  await kpi("Séances");
  chartClick(/^Calendrier des séances/, { dataIndex: 0, data: ["2026-10-01", 50] });
  expect(await screen.findByText(/Le 1 oct\. 2026/)).toBeInTheDocument();
  expect((await kpi("Séances")).getByText("1")).toBeInTheDocument();
});

test("volume shows the empty state when the metric has no data", async () => {
  activities = [{ ...ACTS[2], family: "strength", distance_m: null }];
  render(Stats, { history: null, onimport: () => {} });
  await kpi("Séances");
  expect(screen.getByRole("img", { name: /^Volume par/ })).toBeInTheDocument();
  await fireEvent.click(screen.getByRole("button", { name: "Km" }));
  expect(screen.queryByRole("img", { name: /^Volume par/ })).toBeNull();
  expect(screen.getAllByText("Pas assez de données sur cette période")).toHaveLength(1);
});
