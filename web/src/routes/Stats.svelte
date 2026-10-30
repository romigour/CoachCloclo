<script lang="ts">
  import { onMount } from "svelte";
  import { api, type HistoryState, type PersonalRecord, type StatActivity } from "../lib/api";
  import {
    filterActivities,
    includesRunning,
    previousPeriod,
    resolvePeriod,
    sportOptions,
    type Period,
    type PeriodChoice,
    type SportFilter,
  } from "../lib/stats/filter";
  import { computeKpis } from "../lib/stats/kpis";
  import { dailyMinutes, weekStats } from "../lib/stats/consistency";
  import { bucketFor, sportShare, volumeSeries } from "../lib/stats/volume";
  import { raceProgression, raceRows } from "../lib/stats/races";
  import { fmtDay } from "../lib/stats/format";
  import Filters from "../components/stats/Filters.svelte";
  import KpiRow from "../components/stats/KpiRow.svelte";
  import ConsistencyCalendar from "../components/stats/ConsistencyCalendar.svelte";
  import VolumeChart from "../components/stats/VolumeChart.svelte";
  import SportDonut from "../components/stats/SportDonut.svelte";
  import RunningProgress from "../components/stats/RunningProgress.svelte";
  import Records from "../components/stats/Records.svelte";
  import Races from "../components/stats/Races.svelte";

  let { history, onimport, version = 0 }: { history: HistoryState | null; onimport: () => void; version?: number } =
    $props();

  type Metric = "hours" | "km";
  type Saved = { choice: PeriodChoice; sport: SportFilter; metric: Metric };

  const KEY = "coach.stats.filters";
  const DEFAULTS: Saved = { choice: { kind: "12m" }, sport: "all", metric: "hours" };
  const SPORTS = ["all", "running", "run", "trail", "bike", "swim", "strength", "walk", "other"];
  const ISO = /^\d{4}-\d{2}-\d{2}$/;

  /** Relit les filtres mémorisés ; toute valeur absente, invalide ou illisible retombe sur le défaut. */
  function load(): Saved {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) ?? "null") as Partial<Saved> | null;
      if (!raw || typeof raw !== "object") return DEFAULTS;
      const c = raw.choice as PeriodChoice | undefined;
      const choiceOk =
        c?.kind === "12m" ||
        c?.kind === "all" ||
        (c?.kind === "year" && Number.isInteger(c.year)) ||
        (c?.kind === "custom" && ISO.test(c.from) && ISO.test(c.to) && c.from <= c.to);
      return {
        choice: choiceOk ? c! : DEFAULTS.choice,
        sport: SPORTS.includes(raw.sport as string) ? (raw.sport as SportFilter) : DEFAULTS.sport,
        metric: raw.metric === "km" ? "km" : "hours",
      };
    } catch {
      return DEFAULTS;
    }
  }

  function save(s: Saved) {
    try {
      localStorage.setItem(KEY, JSON.stringify(s));
    } catch {
      // stockage indisponible (navigation privée, quota) : les filtres ne sont simplement pas mémorisés
    }
  }

  function localToday(): string {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  const saved = load();
  let choice = $state<PeriodChoice>(saved.choice);
  let sport = $state<SportFilter>(saved.sport);
  let metric = $state<Metric>(saved.metric);
  let activities = $state<StatActivity[] | null>(null);
  // Records absolus (non filtrés) : chargement indépendant, un échec affiche « Records indisponibles ».
  let records = $state<PersonalRecord[] | null>(null);
  let loadError = $state<string | null>(null);
  const today = localToday();

  $effect(() => save({ choice, sport, metric }));

  async function loadAll() {
    api.statsRecords().then(
      (r) => (records = r.records),
      () => (records = []),
    );
    try {
      activities = (await api.statsActivities()).activities;
    } catch (e) {
      loadError = e instanceof Error ? e.message : "Impossible de charger les activités";
    }
  }

  onMount(loadAll);

  // Synchro ou import terminé (la version change) : on recharge activités et records.
  let loadedVersion: number | null = null;
  $effect(() => {
    const v = version;
    if (loadedVersion === null || v === loadedVersion) {
      loadedVersion = v;
      return;
    }
    loadedVersion = v;
    loadError = null;
    loadAll();
  });

  const all = $derived(activities ?? []);
  const period = $derived(resolvePeriod(choice, today, all));
  const current = $derived(filterActivities(all, period, sport));
  // Pas de variation pour « Tout » : il n'y a pas de période précédente.
  const previous = $derived(choice.kind === "all" ? null : filterActivities(all, previousPeriod(period), sport));

  const kpis = $derived(computeKpis(current, previous));
  const days = $derived(dailyMinutes(current));
  const weeks = $derived(weekStats(current, period, today));
  const bucket = $derived(bucketFor(period));
  const volume = $derived(volumeSeries(current, period, metric));
  const share = $derived(sportShare(current));
  const options = $derived(sportOptions(all));
  const showRunning = $derived(includesRunning(sport));
  // Compétitions : filtrées par période seulement (une course route reste visible avec le filtre « Trail »).
  const periodActs = $derived(filterActivities(all, period, "all"));
  const races = $derived(raceRows(periodActs));
  const progression = $derived(raceProgression(periodActs));
  const years = $derived([...new Set(all.map((a) => Number(a.date.slice(0, 4))))].sort((a, b) => b - a));

  const periodText = $derived(
    period.from === period.to ? `Le ${fmtDay(period.from)}` : `Du ${fmtDay(period.from)} au ${fmtDay(period.to)}`,
  );

  function change(c: PeriodChoice, s: SportFilter) {
    choice = c;
    sport = s;
  }

  function pick(p: Period) {
    choice = { kind: "custom", from: p.from, to: p.to };
  }

  /** Compétition enregistrée ou dé-marquée : remplace la ligne sans recharger la liste. */
  function replaceActivity(row: StatActivity) {
    if (activities) activities = activities.map((a) => (a.id === row.id ? row : a));
  }

  function reset() {
    choice = DEFAULTS.choice;
    sport = DEFAULTS.sport;
    metric = DEFAULTS.metric;
  }
</script>

<div class="stats-page">
  <header class="page-head">
    <div>
      <p class="eyebrow">Historique Garmin</p>
      <h1>Statistiques</h1>
    </div>
  </header>

  {#if history?.status === "running"}
    <p class="banner info busy" role="status">Import de l'historique : {history.imported} activités…</p>
  {:else if history?.status === "error"}
    <div class="banner warning import-error" role="alert">
      <span>Import de l'historique interrompu : {history.error ?? "erreur inconnue"}</span>
      <button type="button" class="small" onclick={onimport}>Reprendre</button>
    </div>
  {/if}

  {#if loadError}
    <p class="banner error" role="alert">{loadError}</p>
  {:else if activities === null}
    <p class="busy">Chargement des statistiques…</p>
  {:else if activities.length === 0 && history?.status === "idle"}
    <section class="card lg stack first-import">
      <h2>Aucune activité pour l'instant</h2>
      <p class="meta">Importe ton historique Garmin pour voir tes statistiques.</p>
      <div class="row"><button type="button" class="primary" onclick={onimport}>Importer mon historique Garmin</button></div>
    </section>
  {:else}
    <Filters {choice} {sport} {options} {years} {period} onchange={change} onreset={reset} />
    <p class="meta">{periodText} · {current.length} séance{current.length > 1 ? "s" : ""}</p>

    <div class="grid">
      <section class="span" aria-labelledby="kpi-title">
        <h2 id="kpi-title" class="sr-only">Chiffres clés</h2>
        <KpiRow {kpis} />
      </section>

      <section class="card stack span" aria-labelledby="reg-title">
        <div><h2 id="reg-title">Régularité</h2><p class="meta">Suis-je constant ?</p></div>
        <ConsistencyCalendar {days} {period} stats={weeks} onpick={pick} />
      </section>

      <section class="card stack" aria-labelledby="vol-title">
        <div><h2 id="vol-title">Volume</h2><p class="meta">Comment évolue ma charge ?</p></div>
        <VolumeChart data={volume} {metric} {bucket} onmetric={(m) => (metric = m)} onpick={pick} />
      </section>

      <section class="card stack" aria-labelledby="share-title">
        <div><h2 id="share-title">Répartition</h2><p class="meta">En heures, par sport</p></div>
        <SportDonut {share} />
      </section>

      {#if showRunning}
        <section class="card stack span" aria-labelledby="run-title">
          <div><h2 id="run-title">Course à pied</h2><p class="meta">Est-ce que je progresse ?</p></div>
          <RunningProgress acts={current} />
        </section>
      {/if}

      {#if showRunning}
        <section class="card stack" aria-labelledby="races-title">
          <div><h2 id="races-title">Compétitions</h2><p class="meta">Mes courses officielles</p></div>
          <Races acts={all} rows={races} {progression} onchanged={replaceActivity} />
        </section>
      {/if}

      <section class="card stack" aria-labelledby="rec-title">
        <div><h2 id="rec-title">Records</h2><p class="meta">Mes meilleurs temps</p></div>
        <Records {records} />
      </section>
    </div>
  {/if}
</div>

<style>
  .stats-page { display: flex; flex-direction: column; gap: 16px; }
  .stats-page :global(.empty) {
    color: var(--muted);
    text-align: center;
    padding: 24px 8px;
  }
  .import-error {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .first-import { align-items: flex-start; }
  .grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 16px;
  }
  .grid > section { min-width: 0; }
  @media (min-width: 900px) {
    .grid { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 20px; }
    .span { grid-column: 1 / -1; }
  }
</style>
