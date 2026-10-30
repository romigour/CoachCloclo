<script lang="ts">
  import EChart from "./EChart.svelte";
  import type { StatActivity } from "../../lib/api";
  import {
    aerobicEfficiency,
    easyShare,
    longestRunByMonth,
    MIN_TREND_POINTS,
    trailSummary,
    trendLine,
    vo2maxSeries,
    zoneDistribution,
    zoneShares,
  } from "../../lib/stats/running";
  import { themeColors } from "../../lib/stats/echarts";
  import { fmtDay, fmtMinutes, fmtMonth, fmtMonthShort, fmtMonthTick, fmtNumber } from "../../lib/stats/format";
  import { tooltipTheme, withAlpha } from "../../lib/stats/color";

  /** Activités déjà filtrées (période + sport). */
  let { acts }: { acts: StatActivity[] } = $props();

  const efficiency = $derived(aerobicEfficiency(acts));
  const trend = $derived(trendLine(efficiency.points, efficiency.trend));
  const vo2 = $derived(vo2maxSeries(acts));
  const longest = $derived(longestRunByMonth(acts));
  const zones = $derived(zoneDistribution(acts));
  const easy = $derived(zones ? easyShare(zones) : null);
  const trail = $derived(trailSummary(acts));
  const empty = $derived(
    efficiency.points.length === 0 && vo2.length === 0 && longest.length === 0 && zones === null && trail === null,
  );

  /** Axes communs aux graphiques temporels. */
  function timeAxes(c: ReturnType<typeof themeColors>, yFormat: (v: number) => string) {
    return {
      grid: { top: 12, left: 4, right: 12, bottom: 4, containLabel: true },
      xAxis: {
        type: "time",
        axisLabel: { color: c.muted, formatter: fmtMonthTick, hideOverlap: true },
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: c.muted, formatter: yFormat },
        splitLine: { lineStyle: { color: c.border, type: "dashed" } },
      },
    };
  }

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
        formatter: (p: { dataIndex: number }) => {
          const pt = vo2[p.dataIndex];
          return pt ? `<b>${fmtDay(pt.date)}</b><br/>VO2max : <b>${fmtNumber(pt.value, 1)}</b>` : "";
        },
      },
      series: [
        {
          type: "line",
          name: "VO2max",
          data: vo2.map((p) => [p.date, p.value]),
          step: "end",
          showSymbol: vo2.length <= 40,
          symbolSize: 5,
          lineStyle: { color: c.accent, width: 2 },
          itemStyle: { color: c.accent },
          areaStyle: { color: withAlpha(c.accent, 0.12) },
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

  const zonesOption = $derived.by(() => {
    const c = themeColors();
    const z = zones ?? [];
    const shares = zoneShares(z).map((x) => Math.round(x * 100));
    // Rampe d'intensité de l'app (--z1 … --z5), la même que les profils de séance.
    const colors = c.zones;
    return {
      grid: { top: 18, left: 4, right: 8, bottom: 4, containLabel: true },
      tooltip: {
        ...tooltipTheme(c),
        trigger: "item",
        formatter: (p: { dataIndex: number }) =>
          `<b>Zone ${p.dataIndex + 1}</b><br/>${fmtMinutes(Math.round(z[p.dataIndex] / 60))} · ${shares[p.dataIndex]} %`,
      },
      xAxis: {
        type: "category",
        data: ["Z1", "Z2", "Z3", "Z4", "Z5"],
        axisLabel: { color: c.muted },
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
      },
      yAxis: { type: "value", show: false },
      series: [
        {
          type: "bar",
          name: "Temps en zone",
          data: shares.map((v, i) => ({ value: v, itemStyle: { color: colors[i], borderRadius: [3, 3, 0, 0] } })),
          barMaxWidth: 40,
          label: { show: true, position: "top", color: c.muted, formatter: (p: { value: number }) => `${p.value} %` },
        },
      ],
    };
  });
</script>

{#if empty}
  <p class="empty">Aucune sortie course ou trail sur cette période</p>
{:else}
  <div class="panels">
    <div class="panel">
      <h3>Efficacité aérobie</h3>
      <p class="sub">Vitesse / FC sur sorties route ≥ 20 min, peu de dénivelé</p>
      {#if efficiency.points.length === 0}
        <p class="empty">Pas assez de données sur cette période</p>
      {:else}
        {#if trend}
          <p class="figure-line">
            Tendance
            <strong class:up={trend.changePct > 0} class:down={trend.changePct < 0}>
              {trend.changePct >= 0 ? "▲ +" : "▼ −"}{fmtNumber(Math.abs(trend.changePct), 1)} %
            </strong>
            <span class="meta">sur {efficiency.points.length} sorties</span>
          </p>
        {:else}
          <p class="meta">Tendance à partir de {MIN_TREND_POINTS} sorties</p>
        {/if}
        <EChart option={efficiencyOption} height="220px" label="Efficacité aérobie par sortie, avec tendance" />
        <p class="hint">Plus c'est haut, plus tu cours vite pour un même cardio.</p>
      {/if}
    </div>

    <div class="panel">
      <h3>VO2max</h3>
      <p class="sub">Estimation Garmin</p>
      {#if vo2.length === 0}
        <p class="empty">Pas de VO2max sur cette période</p>
      {:else}
        <p class="figure-line">Dernière valeur <strong>{fmtNumber(vo2[vo2.length - 1].value, 1)}</strong></p>
        <EChart option={vo2Option} height="220px" label="VO2max estimée dans le temps" />
      {/if}
    </div>

    <div class="panel">
      <h3>Sortie la plus longue par mois</h3>
      <p class="sub">Route et trail</p>
      {#if longest.length === 0}
        <p class="empty">Pas assez de données sur cette période</p>
      {:else}
        <EChart option={longestOption} height="220px" label="Sortie la plus longue de chaque mois, en kilomètres" />
      {/if}
    </div>

    {#if zones}
      <div class="panel">
        <h3>Zones FC</h3>
        <p class="sub">Temps cumulé par zone sur la période</p>
        {#if easy !== null}
          <p class="figure-line">Facile : <strong>{Math.round(easy * 100)} %</strong> <span class="meta">(zones 1-2)</span></p>
        {/if}
        <EChart option={zonesOption} height="200px" label="Répartition du temps par zone de fréquence cardiaque" />
      </div>
    {/if}
  </div>

  {#if trail}
    <div class="trail" role="group" aria-label="Trail">
      <h3>Trail</h3>
      <div class="figures">
        <div><span class="label">D+ cumulé</span><span><strong>{fmtNumber(trail.dPlusM)}</strong> <span class="unit">m</span></span></div>
        <div><span class="label">D+ moyen</span><span><strong>{fmtNumber(trail.dPlusPerKm)}</strong> <span class="unit">m/km</span></span></div>
      </div>
    </div>
  {/if}
{/if}

<style>
  .panels {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1rem 1.5rem;
  }
  @media (min-width: 700px) {
    .panels { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  .panel { min-width: 0; }
  h3 { font-size: 15px; }
  .sub { margin: 0.1rem 0 0.3rem; color: var(--muted); font-size: 12px; }
  .figure-line { margin: 0.2rem 0; font-size: 13px; }
  .figure-line strong { font-variant-numeric: tabular-nums; }
  .up { color: var(--accent); }
  .down { color: var(--todo); }
  .hint { color: var(--muted); font-size: 12px; margin: 0.3rem 0 0; }
  .trail {
    margin-top: 1rem;
    padding-top: 0.8rem;
    border-top: 1px solid var(--border);
  }
  .figures { display: flex; flex-wrap: wrap; gap: 0.5rem 2rem; margin-top: 0.3rem; }
  .figures div { display: flex; flex-direction: column; }
  .figures .label { color: var(--muted); font-size: 12px; }
  .figures strong { font-family: var(--font-display); font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .figures .unit { color: var(--muted); font-size: 13px; }
</style>
