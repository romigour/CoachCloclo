<script lang="ts">
  import EChart from "../EChart.svelte";
  import Insight from "../Insight.svelte";
  import type { PersonalRecord, StatActivity } from "../../../lib/api";
  import { CATEGORY_LABEL } from "../../../lib/labels";
  import { timeAxes } from "../../../lib/stats/charts";
  import { tooltipTheme, withAlpha } from "../../../lib/stats/color";
  import { themeColors } from "../../../lib/stats/echarts";
  import { fmtClock, fmtDay, fmtMonth, fmtMonthShort, fmtNumber, fmtPace } from "../../../lib/stats/format";
  import { efficiencyText, hrAtPaceText, longestText, predictionText, trailText, vo2Text } from "../../../lib/stats/insights";
  import { predictions, references } from "../../../lib/stats/predict";
  import {
    aerobicEfficiency,
    hrAtPace,
    longestRunByMonth,
    MIN_TREND_POINTS,
    rollingMean,
    trailSummary,
    trendLine,
    vo2maxSeries,
  } from "../../../lib/stats/running";

  let {
    all,
    acts,
    records,
    today,
  }: {
    all: StatActivity[];
    /** Course et trail de la période. */
    acts: StatActivity[];
    records: PersonalRecord[] | null;
    today: string;
  } = $props();

  const EMPTY = "Pas assez de données sur cette période";

  const efficiency = $derived(aerobicEfficiency(acts));
  const trend = $derived(trendLine(efficiency.points, efficiency.trend));
  const paceHr = $derived(hrAtPace(acts));
  const vo2 = $derived(vo2maxSeries(acts));
  const vo2Mean = $derived(rollingMean(vo2));
  const longest = $derived(longestRunByMonth(acts));
  const trail = $derived(trailSummary(acts));
  const predicted = $derived(predictions(references(all, records ?? [], today)));

  const efficiencyOption = $derived.by(() => {
    const c = themeColors();
    const pts = efficiency.points;
    return {
      ...timeAxes(c, (v) => fmtNumber(v, 2)),
      tooltip: {
        ...tooltipTheme(c),
        trigger: "item",
        formatter: (p: { dataIndex: number; seriesType: string }) => {
          const pt = pts[p.dataIndex];
          if (p.seriesType !== "scatter" || !pt) return "";
          return `<b>${fmtDay(pt.date)}</b><br/>Efficacité : <b>${fmtNumber(pt.value, 2)}</b> (m/min)/bpm`;
        },
      },
      series: [
        {
          type: "scatter",
          name: "Efficacité aérobie",
          data: pts.map((p) => [p.date, Math.round(p.value * 1000) / 1000]),
          symbolSize: 8,
          itemStyle: { color: withAlpha(c.families.run, 0.75) },
          markLine: trend
            ? {
                silent: true,
                symbol: "none",
                label: { show: false },
                lineStyle: { color: c.text, width: 2, type: "dashed" },
                data: [[{ coord: [trend.start.date, trend.start.value] }, { coord: [trend.end.date, trend.end.value] }]],
              }
            : undefined,
        },
      ],
    };
  });

  const vo2Option = $derived.by(() => {
    const c = themeColors();
    return {
      // Demi-points affichés tels quels : arrondis, ils doublaient les graduations (52, 53, 53…).
      ...timeAxes(c, (v) => fmtNumber(v, Number.isInteger(v) ? 0 : 1)),
      tooltip: {
        ...tooltipTheme(c),
        trigger: "item",
        formatter: (p: { dataIndex: number; seriesName: string }) => {
          const mean = p.seriesName === "Moyenne mobile";
          const pt = (mean ? vo2Mean : vo2)[p.dataIndex];
          return pt ? `<b>${fmtDay(pt.date)}</b><br/>${mean ? "Moyenne sur 5 valeurs" : "VO2max"} : <b>${fmtNumber(pt.value, 1)}</b>` : "";
        },
      },
      series: [
        {
          type: "scatter",
          name: "VO2max",
          data: vo2.map((p) => [p.date, p.value]),
          symbolSize: 6,
          itemStyle: { color: withAlpha(c.accent, 0.55) },
        },
        {
          type: "line",
          name: "Moyenne mobile",
          data: vo2Mean.map((p) => [p.date, Math.round(p.value * 10) / 10]),
          showSymbol: false,
          lineStyle: { color: c.accent, width: 2 },
          itemStyle: { color: c.accent },
        },
      ],
    };
  });

  const longestOption = $derived.by(() => {
    const c = themeColors();
    return {
      grid: { top: 12, left: 4, right: 8, bottom: 4, containLabel: true },
      tooltip: {
        ...tooltipTheme(c),
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (items: { dataIndex: number }[]) => {
          const m = longest[items[0]?.dataIndex ?? 0];
          return m ? `<b>${fmtMonth(m.month)}</b><br/>Plus longue : <b>${fmtNumber(m.km, 1)} km</b>` : "";
        },
      },
      xAxis: {
        type: "category",
        data: longest.map((m) => m.month),
        axisLabel: { color: c.muted, formatter: fmtMonthShort, hideOverlap: true },
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: c.muted, formatter: (v: number) => `${fmtNumber(v)} km` },
        splitLine: { lineStyle: { color: c.border, type: "dashed" } },
      },
      series: [
        {
          type: "bar",
          name: "Sortie la plus longue",
          data: longest.map((m) => Math.round(m.km * 10) / 10),
          barMaxWidth: 24,
          itemStyle: { color: c.families.run, borderRadius: [3, 3, 0, 0] },
        },
      ],
    };
  });
</script>

<div class="grid">
  <section class="card stack" aria-labelledby="eff-title">
    <div><h2 id="eff-title">Efficacité aérobie</h2><p class="meta">Vitesse / FC sur sorties route ≥ 20 min, peu de dénivelé</p></div>
    {#if efficiency.points.length === 0}
      <p class="empty">{EMPTY}</p>
    {:else}
      <EChart option={efficiencyOption} height="220px" label="Efficacité aérobie par sortie, avec tendance" />
      {#if trend}
        <Insight text={efficiencyText(trend.changePct)} />
      {:else}
        <p class="meta">Tendance à partir de {MIN_TREND_POINTS} sorties</p>
      {/if}
    {/if}
  </section>

  <section class="card stack" aria-labelledby="vo2-title">
    <div><h2 id="vo2-title">VO2max</h2><p class="meta">Estimation Garmin, points ; moyenne sur 5 valeurs, ligne</p></div>
    {#if vo2.length === 0}
      <p class="empty">Pas de VO2max sur cette période</p>
    {:else}
      <EChart option={vo2Option} height="220px" label="VO2max estimée dans le temps" />
      <Insight text={vo2Text(vo2.map((p) => p.value))} />
    {/if}
  </section>

  <section class="card stack" aria-labelledby="pace-title">
    <div><h2 id="pace-title">FC à allure donnée</h2><p class="meta">Premier et dernier tiers des sorties à ±10 s/km de ton allure médiane</p></div>
    {#if paceHr}
      <div class="figures">
        <div><span class="label">Allure</span><strong>{fmtPace(paceHr.paceSKm)}</strong></div>
        <div><span class="label">Début</span><strong>{paceHr.from} bpm</strong></div>
        <div><span class="label">Fin</span><strong>{paceHr.to} bpm</strong></div>
        <div><span class="label">Sorties</span><strong>{paceHr.count}</strong></div>
      </div>
      <Insight text={hrAtPaceText(paceHr)} />
    {:else}
      <p class="empty">Pas assez de sorties à cette allure</p>
    {/if}
  </section>

  <section class="card stack" aria-labelledby="pred-title">
    <div><h2 id="pred-title">Prédicteur de temps</h2><p class="meta">Formule de Riegel, courses et records de moins d'un an, quelle que soit la période</p></div>
    {#if predicted.length > 0}
      <div role="group" aria-label="Prédicteur de temps"><ul class="predictions">
        {#each predicted as p (p.category)}
          <li>
            <span>{CATEGORY_LABEL[p.category]}</span>
            <strong>{fmtClock(p.timeS)}</strong>
            <span class="meta">d'après {CATEGORY_LABEL[p.from.category]} en {fmtClock(p.from.timeS)}, {fmtDay(p.from.date)}</span>
          </li>
        {/each}
      </ul></div>
      <Insight text={predictionText(predicted)} />
    {:else if records === null}
      <p class="empty">Chargement des records…</p>
    {:else}
      <p class="empty">Aucune course ou record de moins d'un an</p>
    {/if}
  </section>

  <section class="card stack" aria-labelledby="long-title">
    <div><h2 id="long-title">Sortie la plus longue par mois</h2><p class="meta">Route et trail</p></div>
    {#if longest.length === 0}
      <p class="empty">{EMPTY}</p>
    {:else}
      <EChart option={longestOption} height="220px" label="Sortie la plus longue de chaque mois, en kilomètres" />
      <Insight text={longestText(longest)} />
    {/if}
  </section>

  {#if trail}
    <section class="card stack" aria-labelledby="trail-title">
      <h2 id="trail-title">Trail</h2>
      <div class="figures">
        <div><span class="label">D+ cumulé</span><strong>{fmtNumber(trail.dPlusM)} m</strong></div>
        <div><span class="label">D+ moyen</span><strong>{fmtNumber(trail.dPlusPerKm)} m/km</strong></div>
      </div>
      <Insight text={trailText(trail)} />
    </section>
  {/if}
</div>

<style>
  .grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
  @media (min-width: 900px) {
    .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
  }
  .grid > section { min-width: 0; align-self: start; }
  .figures { display: flex; flex-wrap: wrap; gap: 0.6rem 2rem; }
  .figures div { display: flex; flex-direction: column; }
  .label { color: var(--muted); font-size: 12px; }
  .figures strong { font-family: var(--font-display); font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .predictions { list-style: none; margin: 0; padding: 0; }
  .predictions li {
    display: grid;
    grid-template-columns: 80px auto minmax(0, 1fr);
    align-items: baseline;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 1px solid var(--divider);
  }
  .predictions li:last-child { border-bottom: 0; }
  .predictions strong { font-variant-numeric: tabular-nums; }
</style>
