<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { api, type HistoryState, type PersonalRecord, type StatActivity } from "../lib/api";
  import { load as cached } from "../lib/cache";
  import {
    filterActivities,
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
  import { efficiencyText, fitnessText, lastResultText, splitText } from "../lib/stats/insights";
  import { split } from "../lib/stats/intensity";
  import { CTL_DAYS as FITNESS_WARMUP, fitnessSeries, hrRange } from "../lib/stats/load";
  import { aerobicEfficiency, trendLine, zoneDistribution } from "../lib/stats/running";
  import { currentZones } from "../lib/zones.svelte";
  import { fmtDay } from "../lib/stats/format";
  import type { StatsTab } from "../lib/stats/tabs";
  import StatsTabs from "../components/stats/StatsTabs.svelte";
  import Filters from "../components/stats/Filters.svelte";
  import VolumeChart from "../components/stats/VolumeChart.svelte";
  import SportDonut from "../components/stats/SportDonut.svelte";
  import Intensity from "../components/stats/views/Intensity.svelte";
  import Overview from "../components/stats/views/Overview.svelte";
  import Progress from "../components/stats/views/Progress.svelte";
  import RacesView from "../components/stats/views/RacesView.svelte";
  import { READONLY } from "../lib/mode";
  import { importBanner } from "../lib/history";

  let {
    history,
    onimport,
    version = 0,
    tab = "overview",
  }: { history: HistoryState | null; onimport: () => void; version?: number; tab?: StatsTab } = $props();

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
    cached("records", () => api.statsRecords(), (r) => (records = r.records)).catch(() => (records ??= []));
    // Liste déjà affichée (compétition modifiée depuis, peut-être) : la valeur en cache ne la remplace pas.
    let initial = true;
    const shown = activities !== null;
    const reading = cached("stats", () => api.statsActivities(), (r) => {
      if (!initial || !shown) activities = r.activities;
    });
    initial = false;
    try {
      await reading;
      loadError = null;
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
    untrack(loadAll);
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
  // Sous-pages de course : route et trail, quel que soit le sport mémorisé.
  const runs = $derived(filterActivities(all, period, "running"));
  const showSport = $derived(tab === "overview" || tab === "load");
  const count = $derived((showSport ? current : runs).length);

  /** Constats de l'Aperçu : un par sous-page, omis sans données suffisantes. */
  const notes = $derived.by(() => {
    if (tab !== "overview") return [];
    const efficiency = aerobicEfficiency(runs);
    const hr = hrRange(currentZones());
    const zones = zoneDistribution(runs);
    const list: { tab: StatsTab; text: string | null }[] = [
      { tab: "progress", text: efficiencyText(trendLine(efficiency.points, efficiency.trend)?.changePct ?? null) },
      { tab: "load", text: hr ? fitnessText(fitnessSeries(all, hr, today).slice(FITNESS_WARMUP).at(-1)) : null },
      { tab: "intensity", text: splitText(zones ? split(zones) : null) },
      { tab: "races", text: lastResultText(runs, records ?? [], period) },
    ];
    return list.filter((n): n is { tab: StatsTab; text: string } => n.text !== null);
  });
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
    if (showSport) sport = DEFAULTS.sport; // un filtre masqué n'est pas touché
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

  <StatsTabs {tab} />

  {#if history?.status === "running"}
    <p class="banner info busy" role="status">{importBanner(history.imported)}</p>
  {:else if history?.status === "error"}
    <div class="banner warning import-error" role="alert">
      <span>Import de l'historique interrompu : {history.error ?? "erreur inconnue"}</span>
      {#if !READONLY}<button type="button" class="small" onclick={onimport}>Reprendre</button>{/if}
    </div>
  {/if}

  {#if loadError}
    <p class="banner error" role="alert">{loadError}</p>
  {/if}
  {#if activities === null}
    {#if !loadError}<p class="busy">Chargement des statistiques…</p>{/if}
  {:else if activities.length === 0 && history?.status === "idle"}
    <section class="card lg stack first-import">
      <h2>Aucune activité pour l'instant</h2>
      {#if READONLY}
        <p class="meta">Importe ton historique Garmin depuis l'ordinateur pour voir tes statistiques.</p>
      {:else}
        <p class="meta">Importe ton historique Garmin pour voir tes statistiques.</p>
        <div class="row"><button type="button" class="primary" onclick={onimport}>Importer mon historique Garmin</button></div>
      {/if}
    </section>
  {:else}
    <Filters {choice} {sport} {options} {years} {period} {showSport} onchange={change} onreset={reset} />
    <p class="meta">{periodText} · {count} séance{count > 1 ? "s" : ""}</p>

    {#if tab === "progress"}
      <Progress {all} acts={runs} {records} {today} />
    {:else if tab === "intensity"}
      <Intensity acts={runs} {period} />
    {:else if tab === "races"}
      <RacesView {all} acts={runs} {period} {records} onchanged={replaceActivity} />
    {:else if tab === "load"}
      <div class="grid">
        <section class="card stack" aria-labelledby="vol-title">
          <div><h2 id="vol-title">Volume</h2><p class="meta">Comment évolue ma charge ?</p></div>
          <VolumeChart data={volume} {metric} {bucket} onmetric={(m) => (metric = m)} onpick={pick} />
        </section>

        <section class="card stack" aria-labelledby="share-title">
          <div><h2 id="share-title">Répartition</h2><p class="meta">En heures, par sport</p></div>
          <SportDonut {share} />
        </section>
      </div>
    {:else}
      <Overview {kpis} {days} {period} {weeks} {notes} onpick={pick} />
    {/if}
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
  }
</style>
