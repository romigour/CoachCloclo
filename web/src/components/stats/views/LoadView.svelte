<script lang="ts">
  import EChart from "../EChart.svelte";
  import Insight from "../Insight.svelte";
  import SportDonut from "../SportDonut.svelte";
  import VolumeChart from "../VolumeChart.svelte";
  import type { StatActivity, Zones } from "../../../lib/api";
  import { timeAxes } from "../../../lib/stats/charts";
  import { tooltipTheme, withAlpha } from "../../../lib/stats/color";
  import { themeColors } from "../../../lib/stats/echarts";
  import { filterActivities, type Period, type SportFilter } from "../../../lib/stats/filter";
  import { fmtDay, fmtNumber } from "../../../lib/stats/format";
  import { acwrText, fitnessText, rampText, shareText, volumeText } from "../../../lib/stats/insights";
  import { computeKpis } from "../../../lib/stats/kpis";
  import {
    acwr,
    CTL_DAYS,
    fitnessSeries,
    hrCoverage,
    hrRange,
    MISSING_HR_ALERT,
    visibleFitness,
    weeklyRamp,
  } from "../../../lib/stats/load";
  import { bucketFor, sportShare, volumeSeries } from "../../../lib/stats/volume";

  type Metric = "hours" | "km";

  let {
    all,
    sport,
    current,
    previous,
    period,
    today,
    zones,
    metric,
    onmetric,
    onpick,
  }: {
    all: StatActivity[];
    sport: SportFilter;
    /** Activités de la période et du sport choisis. */
    current: StatActivity[];
    previous: StatActivity[] | null;
    period: Period;
    today: string;
    zones: Zones | null;
    metric: Metric;
    onmetric: (m: Metric) => void;
    onpick: (p: Period) => void;
  } = $props();

  const bucket = $derived(bucketFor(period));
  const volume = $derived(volumeSeries(current, period, metric));
  const share = $derived(sportShare(current));
  const hours = $derived(computeKpis(current, previous).find((k) => k.key === "hours")?.delta ?? null);
  const ramp = $derived(weeklyRamp(filterActivities(all, { from: "0000-01-01", to: today }, sport), today));

  // Forme : tous sports et tout l'historique ; la période ne limite que la courbe.
  const hr = $derived(hrRange(zones));
  const series = $derived(hr ? fitnessSeries(all, hr, today) : []);
  const now = $derived(series.slice(CTL_DAYS).at(-1));
  const shown = $derived(visibleFitness(series, period));
  const ratio = $derived(hr ? acwr(all, hr, today) : null);
  const coverage = $derived(hrCoverage(all, today));

  const coverageText = $derived.by(() => {
    if (coverage.missing === 0) return null;
    const s = coverage.missing > 1 ? "s" : "";
    const under = coverage.missingShare > MISSING_HR_ALERT ? " : ta charge est sous-estimée" : "";
    return `${coverage.missing} séance${s} sans FC sur les 42 derniers jours${under}.`;
  });

  const fitnessOption = $derived.by(() => {
    const c = themeColors();
    const lines = [
      { name: "Forme", key: "ctl", color: c.accent, type: "solid", width: 2.5 },
      { name: "Fatigue", key: "atl", color: c.zones[3], type: "dashed", width: 2 },
      { name: "Fraîcheur", key: "tsb", color: c.text, type: "dotted", width: 2 },
    ] as const;
    return {
      ...timeAxes(c, (v) => fmtNumber(v)),
      grid: { top: 36, left: 4, right: 12, bottom: 4, containLabel: true },
      legend: { top: 0, left: 0, textStyle: { color: c.muted }, itemWidth: 28, icon: undefined, data: lines.map((l) => l.name) },
      tooltip: {
        ...tooltipTheme(c),
        trigger: "axis",
        formatter: (items: { dataIndex: number }[]) => {
          const p = shown[items[0]?.dataIndex ?? 0];
          if (!p) return "";
          return `<b>${fmtDay(p.date)}</b><br/>${lines.map((l) => `${l.name} : <b>${fmtNumber(p[l.key])}</b>`).join("<br/>")}`;
        },
      },
      series: lines.map((l) => ({
        type: "line",
        name: l.name,
        data: shown.map((p) => [p.date, Math.round(p[l.key] * 10) / 10]),
        showSymbol: false,
        lineStyle: { color: l.color, width: l.width, type: l.type },
        itemStyle: { color: l.color },
        areaStyle: l.key === "ctl" ? { color: withAlpha(l.color, 0.1) } : undefined,
      })),
    };
  });
</script>

<div class="grid">
  <section class="card stack" aria-labelledby="vol-title">
    <div><h2 id="vol-title">Volume</h2><p class="meta">Comment évolue mon volume ?</p></div>
    <VolumeChart data={volume} {metric} {bucket} {onmetric} {onpick} />
    <Insight text={volumeText(hours)} />
    <Insight text={rampText(ramp)} />
  </section>

  <section class="card stack" aria-labelledby="share-title">
    <div><h2 id="share-title">Répartition</h2><p class="meta">En heures, par sport</p></div>
    <SportDonut {share} />
    <Insight text={shareText(share)} />
  </section>
</div>

<section class="card stack" aria-labelledby="fit-title">
  <div>
    <h2 id="fit-title">Forme, fatigue, fraîcheur</h2>
    <p class="meta">Tous sports. Le sport filtre le volume, pas la forme. Charge (TRIMP) estimée avec tes FC repos et max actuelles.</p>
  </div>
  {#if !hr}
    <p class="empty">Synchronise Garmin pour calculer ta charge</p>
  {:else}
    {#if now}
      <div class="figures">
        <div role="group" aria-label="Forme"><span class="label">Forme (42 j)</span><strong>{fmtNumber(now.ctl)}</strong></div>
        <div role="group" aria-label="Fatigue"><span class="label">Fatigue (7 j)</span><strong>{fmtNumber(now.atl)}</strong></div>
        <div role="group" aria-label="Fraîcheur"><span class="label">Fraîcheur</span><strong>{fmtNumber(now.tsb)}</strong></div>
      </div>
      {#if shown.length > 0}
        <EChart option={fitnessOption} height="280px" label="Forme, fatigue et fraîcheur jour par jour" />
      {:else}
        <p class="empty">Pas assez de données sur cette période</p>
      {/if}
      <Insight text={fitnessText(now)} />
    {:else}
      <p class="empty">Pas assez d'historique : il faut plus de {CTL_DAYS} jours</p>
    {/if}
    {#if coverageText}<p class="meta" class:warn={coverage.missingShare > MISSING_HR_ALERT}>{coverageText}</p>{/if}
  {/if}
</section>

{#if hr}
  <section class="card stack" aria-labelledby="acwr-title">
    <div><h2 id="acwr-title">Charge récente / habituelle</h2><p class="meta">ACWR : charge des 7 derniers jours comparée aux 28 derniers, aujourd'hui</p></div>
    {#if ratio !== null}
      <div class="figures">
        <div role="group" aria-label="ACWR"><span class="label">ACWR</span><strong>{fmtNumber(ratio, 2)}</strong></div>
      </div>
      <Insight text={acwrText(ratio)} />
    {:else}
      <p class="empty">Pas assez d'historique pour ce repère</p>
    {/if}
  </section>
{/if}

<style>
  .grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
  @media (min-width: 900px) {
    .grid { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 20px; }
  }
  .grid > section { min-width: 0; }
  .figures { display: flex; flex-wrap: wrap; gap: 0.6rem 2.5rem; }
  .figures div { display: flex; flex-direction: column; }
  .label { color: var(--muted); font-size: 12px; }
  .figures strong { font-family: var(--font-display); font-size: 24px; font-weight: 800; font-variant-numeric: tabular-nums; }
  .warn { color: var(--todo); font-weight: 600; }
</style>
