import { render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("./lib/mode", () => ({ READONLY: true }));

// Les lectures de `api` passent par Turso en lecture seule : on sert les données de la fixture `active`.
const creds = vi.hoisted(() => ({ value: { url: "libsql://x", token: "t" } as { url: string; token: string } | null }));
vi.mock("./lib/turso", async () => {
  const f = (await import("./lib/turso/__fixtures__/expected.json")).default.active as Record<string, any>;
  return {
    loadCredentials: () => creds.value,
    status: async () => f.status,
    plan: async () => f.plan,
    events: async () => f.events,
    activities: async (w: number) => f.activities[String(w)] ?? [],
    zones: async () => f.zones,
    statsActivities: async () => f.stats_activities,
    statsRecords: async () => f.stats_records,
  };
});

import App from "./App.svelte";
import Today from "./routes/Today.svelte";
import Plan from "./routes/Plan.svelte";
import Stats from "./routes/Stats.svelte";
import Sidebar from "./components/Sidebar.svelte";
import fixtures from "./lib/turso/__fixtures__/expected.json";

const f = fixtures.active as Record<string, any>;
const TODAY = "2026-03-10";
const ACTIONS = /imprévu|générer|montre|changer de jour|retirer|réessayer|supprimer|importer|reprendre|compétition|modifier|synchro|reprise/i;

// Les boutons de jour portent le libellé de statut (« Erreur de synchro ») : ce sont des sélecteurs, pas des actions.
const actions = () =>
  screen.queryAllByRole("button", { name: ACTIONS }).filter((b) => !b.classList.contains("day") && !b.closest("[class*=cal]"));

beforeEach(() => {
  creds.value = { url: "libsql://x", token: "t" };
  location.hash = "";
});

test("Today : aucune action, proposition renvoyée vers l'ordinateur", async () => {
  render(Today, { today: TODAY, status: f.status });
  expect(await screen.findByText("Une proposition d'ajustement t'attend sur l'ordinateur")).toBeInTheDocument();
  expect(actions()).toEqual([]);
  expect(document.querySelector('a[href="#/proposal"]')).toBeNull();
});

test("Plan : imprévus visibles, aucune action", async () => {
  render(Plan, { today: TODAY });
  expect(await screen.findByText(/Tendinite/)).toBeInTheDocument();
  expect(actions()).toEqual([]);
});

test("Stats : aucune action d'import ni de compétition", async () => {
  render(Stats, { history: { status: "error", imported: 3, error: "x" }, onimport: () => {} });
  await screen.findByText("Statistiques");
  await waitFor(() => expect(screen.queryByText(/Chargement des statistiques/)).toBeNull());
  expect(actions()).toEqual([]);
});

test("Sidebar : liens de lecture seulement", () => {
  render(Sidebar, { route: "today", status: f.status });
  for (const h of ["today", "plan", "stats", "connection"]) expect(document.querySelector(`a[href="#/${h}"]`)).not.toBeNull();
  for (const h of ["goal", "setup", "race", "proposal"]) expect(document.querySelector(`a[href="#/${h}"]`)).toBeNull();
  expect(actions()).toEqual([]);
});

test("App sans identifiants : renvoie vers la connexion", async () => {
  creds.value = null;
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/connection"));
});
