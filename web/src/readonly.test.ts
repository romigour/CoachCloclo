import { render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("./lib/mode", () => ({ READONLY: true }));
vi.mock("./components/stats/EChart.svelte", () => import("./test/EChartStub.svelte"));

// Les lectures de `api` passent par Turso en lecture seule : on sert les données de la fixture `active`.
const creds = vi.hoisted(() => ({ value: { url: "libsql://x", token: "t" } as { url: string; token: string } | null }));
// Variantes de données par test (null : la fixture telle quelle).
const over = vi.hoisted(() => ({ status: null as any, plan: null as any, stats: null as any }));
const fx = await vi.hoisted(async () => (await import("./lib/turso/__fixtures__/expected.json")).default.active as Record<string, any>);
vi.mock("./lib/turso", () => {
  const f = fx;
  return {
    loadCredentials: () => creds.value,
    status: async () => over.status ?? f.status,
    plan: async () => over.plan ?? f.plan,
    events: async () => f.events,
    activities: async (w: number) => f.activities[String(w)] ?? [],
    zones: async () => f.zones,
    statsActivities: async () => over.stats ?? f.stats_activities,
    statsRecords: async () => f.stats_records,
  };
});

import App from "./App.svelte";
import Today from "./routes/Today.svelte";
import Plan from "./routes/Plan.svelte";
import Stats from "./routes/Stats.svelte";
import Sidebar from "./components/Sidebar.svelte";
import InjuryBanner from "./components/InjuryBanner.svelte";
import Races from "./components/stats/Races.svelte";
import { raceRows } from "./lib/stats/races";
import { api, ApiError } from "./lib/api";
import ErrorBanner from "./components/ErrorBanner.svelte";
import fixtures from "./lib/turso/__fixtures__/expected.json";

const f = fixtures.active as Record<string, any>;
const TODAY = "2026-03-10";
const ACTIONS = /imprévu|générer|montre|changer de jour|retirer|réessayer|supprimer|importer|reprendre|compétition|modifier|synchro|reprise/i;

// Les boutons de jour (.day, .cal-session) portent le libellé de statut (« Erreur de synchro ») : ce sont des sélecteurs, pas des actions.
const actions = () => screen.queryAllByRole("button", { name: ACTIONS }).filter((b) => !b.classList.contains("day") && !b.classList.contains("cal-session"));

beforeEach(() => {
  // Les deux lectures simultanées de Stats contournent le mock du module turso (import dynamique concurrent) :
  // on branche donc ces deux lectures directement sur la fixture.
  vi.spyOn(api, "statsActivities").mockImplementation(async () => over.stats ?? f.stats_activities);
  vi.spyOn(api, "statsRecords").mockImplementation(async () => f.stats_records);
  creds.value = { url: "libsql://x", token: "t" };
  over.status = over.plan = over.stats = null;
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
  expect(await screen.findByText("Semi de test")).toBeInTheDocument();
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

test("Stats sans activité : pas de bouton d'import", async () => {
  over.stats = { activities: [] };
  render(Stats, { history: { status: "idle", imported: 0, error: null }, onimport: () => {} });
  expect(await screen.findByText("Aucune activité pour l'instant")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Importer mon historique/ })).toBeNull();
});

test("Races : courses affichées, sans ajout ni modification", () => {
  const acts = f.stats_activities.activities;
  const rows = raceRows(acts);
  render(Races, { acts, rows, progression: [], onchanged: () => {} });
  expect(screen.getByText("Semi de test")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Ajouter une compétition/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Modifier/ })).toBeNull();
});

test("Plan : imprévu visible sans « Supprimer », « Générer » absent même plan à recalculer", async () => {
  over.plan = { ...f.plan, cycle: { ...f.plan.cycle, plan_accepted: false, needs_generation: true } };
  render(Plan, { today: TODAY });
  expect(await screen.findByText(/Tendinite/)).toBeInTheDocument();
  expect(screen.getByLabelText("Plan à recalculer")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Supprimer/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Générer/ })).toBeNull();
});

test("InjuryBanner : bandeau visible, aucun bouton", () => {
  render(InjuryBanner, { injury: f.events.find((e: any) => e.kind === "injury"), today: TODAY });
  expect(screen.getByText(/Arrêt depuis le/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Réessayer|Signaler la reprise|Confirmer la reprise|Annuler/ })).toBeNull();
});

test("App : accueil today si plan accepté", async () => {
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/today"));
});

test("App : accueil stats si plan non accepté", async () => {
  over.status = { ...f.status, cycle: { ...f.status.cycle, plan_accepted: false } };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/stats"));
});

test("App : base indisponible, lien vers la connexion", async () => {
  over.status = { ...f.status, storage: { code: "unreachable", detail: "Base injoignable" } };
  location.hash = "#/today";
  render(App);
  const link = await screen.findByRole("link", { name: "Modifier la connexion" });
  expect(link.getAttribute("href")).toBe("#/connection");
});

test("ErrorBanner : lien et redirection vers la connexion", async () => {
  const { unmount } = render(ErrorBanner, { error: new ApiError("cloud_unreachable", "Base injoignable", 503) });
  expect(screen.getByRole("link", { name: "Modifier la connexion" }).getAttribute("href")).toBe("#/connection");
  unmount();
  render(ErrorBanner, { error: new ApiError("garmin_auth", "Garmin refusé", 401) });
  await waitFor(() => expect(location.hash).toBe("#/connection"));
});
