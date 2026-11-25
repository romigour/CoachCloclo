import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
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
    checkConnection: async () => {},
    saveCredentials: (c: { url: string; token: string }) => {
      creds.value = c;
    },
    clearCredentials: () => {
      creds.value = null;
    },
    normalizeHost: (u: string) => u.replace(/^libsql:\/\//, ""),
    statsActivities: async () => over.stats ?? f.stats_activities,
    statsRecords: async () => f.stats_records,
  };
});

import App from "./App.svelte";
import Week from "./routes/Week.svelte";
import Stats from "./routes/Stats.svelte";
import Sidebar from "./components/Sidebar.svelte";
import InjuryBanner from "./components/InjuryBanner.svelte";
import Races from "./components/stats/Races.svelte";
import { raceRows } from "./lib/stats/races";
import { api, ApiError } from "./lib/api";
import { load } from "./lib/cache";
import ErrorBanner from "./components/ErrorBanner.svelte";
import fixtures from "./lib/turso/__fixtures__/expected.json";

const f = fixtures.active as Record<string, any>;
const TODAY = "2026-03-10";
const ACTIONS = /imprévu|générer|montre|changer de jour|retirer|réessayer|supprimer|importer|reprendre|compétition|modifier|synchro|reprise/i;

// Les séances de la semaine (.wsession) portent le libellé de statut (« Erreur de synchro ») : ce sont des sélecteurs, pas des actions.
const actions = () => screen.queryAllByRole("button", { name: ACTIONS }).filter((b) => !b.classList.contains("wsession"));

beforeEach(() => {
  // Les lectures simultanées (Stats, Ma semaine) contournent le mock du module turso (import dynamique concurrent) :
  // on branche donc ces lectures directement sur la fixture.
  vi.spyOn(api, "plan").mockImplementation(async () => over.plan ?? f.plan);
  vi.spyOn(api, "events").mockImplementation(async () => f.events);
  vi.spyOn(api, "statsActivities").mockImplementation(async () => over.stats ?? f.stats_activities);
  vi.spyOn(api, "statsRecords").mockImplementation(async () => f.stats_records);
  creds.value = { url: "libsql://x", token: "t" };
  over.status = over.plan = over.stats = null;
  location.hash = "";
});

test("Ma semaine : imprévus visibles, aucune action, proposition renvoyée vers l'ordinateur", async () => {
  render(Week, { today: TODAY, status: f.status });
  expect(await screen.findByText("Une proposition d'ajustement t'attend sur l'ordinateur")).toBeInTheDocument();
  expect(await screen.findByText(/Tendinite/)).toBeInTheDocument();
  expect(actions()).toEqual([]);
  expect(document.querySelector('a[href="#/proposal"]')).toBeNull();
});

test("Stats : aucune action d'import ni de compétition", async () => {
  render(Stats, { history: { status: "error", imported: 3, error: "x", total: 0, finished_at: null }, onimport: () => {} });
  expect(await screen.findByText("Semi de test")).toBeInTheDocument();
  expect(actions()).toEqual([]);
});

test("Sidebar : liens de lecture seulement", () => {
  render(Sidebar, { route: "week", status: f.status });
  for (const h of ["week", "stats", "connection"]) expect(document.querySelector(`a[href="#/${h}"]`)).not.toBeNull();
  for (const h of ["goal", "setup", "race", "proposal", "today", "plan"]) expect(document.querySelector(`a[href="#/${h}"]`)).toBeNull();
  expect(actions()).toEqual([]);
});

test("App sans identifiants : renvoie vers la connexion", async () => {
  creds.value = null;
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/connection"));
});

test("Stats sans activité : pas de bouton d'import", async () => {
  over.stats = { activities: [] };
  render(Stats, { history: { status: "idle", imported: 0, error: null, total: 0, finished_at: null }, onimport: () => {} });
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

test("Ma semaine : imprévu visible sans « Supprimer », « Générer » absent même plan à recalculer", async () => {
  over.plan = { ...f.plan, cycle: { ...f.plan.cycle, plan_accepted: false, needs_generation: true } };
  render(Week, { today: TODAY });
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

test("App : accueil Ma semaine si plan accepté", async () => {
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
});

test("App : aucune lecture d'installation ni de Garmin", async () => {
  const setup = vi.spyOn(api, "setupStatus");
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/week"));
  expect(setup).not.toHaveBeenCalled();
  expect(fetchSpy.mock.calls.filter(([u]) => String(u).startsWith("/api/"))).toEqual([]);
  expect(document.querySelector(".garmin-box")).toBeNull();
  setup.mockRestore();
  fetchSpy.mockRestore();
});

test("App : accueil stats si plan non accepté", async () => {
  over.status = { ...f.status, cycle: { ...f.status.cycle, plan_accepted: false } };
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/stats"));
});

test("App : base indisponible, lien vers la connexion", async () => {
  over.status = { ...f.status, storage: { code: "unreachable", detail: "Base injoignable" } };
  location.hash = "#/week";
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

const DESKTOP_ONLY = ['a[href="#/goal"]', 'a[href="#/setup"]', 'a[href="#/race"]', 'a[href="#/proposal"]'];
const noDesktopLink = () => {
  for (const sel of DESKTOP_ONLY) expect(document.querySelector(sel)).toBeNull();
};

test.each([
  ["sans cycle", { cycle: null }],
  ["plan non validé", { cycle: { ...f.plan.cycle, plan_accepted: false } }],
])("Ma semaine, %s : aucun lien vers une page de bureau", async (_n, patch) => {
  over.plan = { ...f.plan, ...patch };
  render(Week, { today: TODAY, status: { ...f.status, ...patch } });
  expect((await screen.findAllByText(/À faire depuis l'ordinateur/)).length).toBeGreaterThan(0);
  noDesktopLink();
});

test("App : un hash de page de bureau est renvoyé vers une route autorisée", async () => {
  location.hash = "#/goal";
  render(App);
  await waitFor(() => expect(["#/week", "#/stats"]).toContain(location.hash));
  location.hash = "#/setup";
  await waitFor(() => expect(["#/week", "#/stats"]).toContain(location.hash));
});

test("App : première connexion, les zones sont relues après l'enregistrement", async () => {
  creds.value = null;
  render(App);
  await waitFor(() => expect(location.hash).toBe("#/connection"));
  // Comme pour Stats : l'import dynamique concurrent contourne le mock du module, on observe donc `api.zones`.
  const zones = vi.spyOn(api, "zones").mockImplementation(async () => f.zones);
  const before = zones.mock.calls.length;
  await fireEvent.input(await screen.findByLabelText("URL de la base"), { target: { value: "libsql://x.turso.io" } });
  await fireEvent.input(screen.getByLabelText("Jeton d'accès"), { target: { value: "tok" } });
  await fireEvent.click(screen.getByRole("button", { name: "Valider" }));
  await waitFor(() => expect(zones.mock.calls.length).toBeGreaterThan(before));
  await waitFor(() => expect(["#/week", "#/stats"]).toContain(location.hash));
});

test("Connexion effacée : retour à la connexion, Ma semaine y renvoie", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  location.hash = "#/connection";
  render(App);
  await fireEvent.click(await screen.findByRole("button", { name: "Effacer" }));
  await waitFor(() => expect(creds.value).toBeNull());
  expect(await screen.findByLabelText("URL de la base")).toBeInTheDocument();
  location.hash = "#/week";
  await waitFor(() => expect(location.hash).toBe("#/connection"));
  expect(screen.queryByRole("link", { name: "Modifier la connexion" })).toBeNull();
});

test("lecture seule : même comportement (plan affiché au retour, oublié avec la connexion)", async () => {
  const first = render(Week, { today: TODAY, status: f.status });
  await screen.findByRole("heading", { name: "Cette semaine" });
  first.unmount();
  const planSpy = vi.spyOn(api, "plan").mockClear().mockImplementation(() => new Promise<never>(() => {}));
  const second = render(Week, { today: TODAY, status: f.status });
  await Promise.resolve();
  expect(screen.getByRole("heading", { name: "Cette semaine" })).toBeInTheDocument();
  expect(planSpy).toHaveBeenCalledTimes(1); // relu quand même
  second.unmount();

  vi.spyOn(window, "confirm").mockReturnValue(true);
  location.hash = "#/connection";
  const app = render(App);
  await fireEvent.click(await screen.findByRole("button", { name: "Effacer" }));
  await waitFor(() => expect(creds.value).toBeNull());
  await screen.findByLabelText("URL de la base");
  app.unmount();
  render(Week, { today: TODAY, status: f.status });
  await Promise.resolve();
  expect(screen.getByText("Chargement…")).toBeInTheDocument();
});

test("lecture seule : nouvelle connexion, les données de l'ancienne base ne réapparaissent pas", async () => {
  creds.value = null;
  await load("stats", async () => ({ activities: [] }), () => {});
  render(App);
  await fireEvent.input(await screen.findByLabelText("URL de la base"), { target: { value: "libsql://y.turso.io" } });
  await fireEvent.input(screen.getByLabelText("Jeton d'accès"), { target: { value: "tok" } });
  await fireEvent.click(screen.getByRole("button", { name: "Valider" }));
  // seule Ma semaine s'ouvre et relit : « stats » doit avoir été oublié
  await waitFor(() => expect(location.hash).toBe("#/week"));
  const apply = vi.fn();
  await load("stats", async () => "nouvelle base", apply);
  expect(apply.mock.calls).toEqual([["nouvelle base"]]);
});

test("lecture seule : nouvelle connexion et état en échec, l'ancien état est oublié", async () => {
  location.hash = "#/connection";
  const status = vi.spyOn(api, "status").mockImplementation(async () => f.status);
  render(App);
  await fireEvent.click(await screen.findByRole("button", { name: "Modifier" }));
  status.mockImplementation(() => Promise.reject(new ApiError("x", "Coupé", 503)));
  await fireEvent.input(await screen.findByLabelText("URL de la base"), { target: { value: "libsql://y.turso.io" } });
  await fireEvent.input(screen.getByLabelText("Jeton d'accès"), { target: { value: "tok" } });
  await fireEvent.click(screen.getByRole("button", { name: "Valider" }));
  await waitFor(() => expect(location.hash).not.toBe("#/connection"));
  expect(location.hash).toBe("#/stats"); // l'ancien cycle accepté mènerait à #/week
  status.mockRestore();
});

test("lecture seule : connexion effacée, une lecture d'état en vol ne restaure pas l'ancien état", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  location.hash = "#/connection";
  let answer: (s: typeof f.status) => void = () => {};
  const status = vi.spyOn(api, "status").mockImplementation(() => new Promise((r) => (answer = r)));
  render(App);
  // la page attend la première lecture : elle répond, puis un sondage d'import reste en vol
  const running = { ...f.status, history: { ...f.status.history, status: "running" } };
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await waitFor(() => expect(status).toHaveBeenCalled());
  answer(running);
  const wipe = await screen.findByRole("button", { name: "Effacer" });
  await vi.advanceTimersByTimeAsync(5100);
  await fireEvent.click(wipe);
  await screen.findByLabelText("URL de la base");
  const asked = status.mock.calls.length;
  answer(running);
  await vi.advanceTimersByTimeAsync(6000); // un état restauré relancerait le sondage
  expect(status.mock.calls.length).toBe(asked);
  vi.useRealTimers();
  status.mockRestore();
});

test("App : lien direct vers une sous-page de statistiques", async () => {
  location.hash = "#/stats/load";
  render(App);
  expect(await screen.findByRole("link", { name: "Charge" })).toHaveAttribute("aria-current", "page");
  expect(location.hash).toBe("#/stats/load");
});
