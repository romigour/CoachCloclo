<script lang="ts">
  import EChart from "./EChart.svelte";
  import type { Family } from "../../lib/api";
  import { addDays, type Period } from "../../lib/stats/filter";
  import type { Bucket } from "../../lib/stats/volume";
  import { themeColors } from "../../lib/stats/echarts";
  import { fmtDay, fmtMonth, fmtNumber, MONTHS_SHORT } from "../../lib/stats/format";
  import { FAMILY_LABEL } from "../../lib/labels";

  type Metric = "hours" | "km";

  let {
    data,
    metric,
    bucket,
    onmetric,
    onpick,
  }: {
    data: { labels: string[]; series: { family: Family; values: number[] }[]; movingAvg: (number | null)[] };
    metric: Metric;
    bucket: Bucket;
    onmetric: (metric: Metric) => void;
    onpick: (period: Period) => void;
  } = $props();

  const unit = $derived(metric === "hours" ? "h" : "km");
  const avgLabel = $derived(bucket === "week" ? "Moyenne 4 semaines" : "Moyenne 4 mois");
  const round1 = (v: number) => Math.round(v * 10) / 10;

  function axisLabel(label: string): string {
    if (bucket === "week") return fmtDay(label, false);
    const [y, m] = label.split("-").map(Number);
    return `${MONTHS_SHORT[m - 1]} ${String(y).slice(2)}`;
  }

  function title(label: string): string {
    return bucket === "week" ? `Semaine du ${fmtDay(label)}` : fmtMonth(label);
  }

  const option = $derived.by(() => {
    const c = themeColors();
    const fmt = (v: number) => `${fmtNumber(v, 1)} ${unit}`;
    return {
      grid: { top: 16, left: 4, right: 8, bottom: 4, containLabel: true },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (items: { dataIndex: number; seriesName: string; value: number | null; marker: string }[]) => {
          const i = items[0]?.dataIndex ?? 0;
          const total = data.series.reduce((s, x) => s + x.values[i], 0);
          const rows = items
            .filter((it) => it.value != null && it.value > 0)
            .map((it) => `${it.marker}${it.seriesName} : <b>${fmt(it.value as number)}</b>`);
          return [`<b>${title(data.labels[i])}</b>`, ...rows, `Total : <b>${fmt(total)}</b>`].join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        data: data.labels,
        axisLabel: { color: c.muted, formatter: axisLabel, hideOverlap: true },
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: { color: c.muted, formatter: (v: number) => `${fmtNumber(v)} ${unit}` },
        splitLine: { lineStyle: { color: c.border, type: "dashed" } },
      },
      series: [
        ...data.series.map((s) => ({
          type: "bar",
          stack: "volume",
          name: FAMILY_LABEL[s.family],
          data: s.values.map(round1),
          itemStyle: { color: c.families[s.family] },
          barMaxWidth: 28,
          emphasis: { focus: "series" },
        })),
        {
          type: "line",
          name: avgLabel,
          data: data.movingAvg.map((v) => (v === null ? null : round1(v))),
          smooth: true,
          showSymbol: false,
          lineStyle: { color: c.text, width: 2, type: "dashed" },
          itemStyle: { color: c.text },
          z: 5,
        },
      ],
    };
  });

  /** Clic sur une barre : la semaine (lundi-dimanche) ou le mois correspondant. */
  function click(p: { dataIndex: number }) {
    const label = data.labels[p.dataIndex];
    if (!label) return;
    if (bucket === "week") return onpick({ from: label, to: addDays(label, 6) });
    const [y, m] = label.split("-").map(Number);
    const next = m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, "0")}-01`;
    onpick({ from: `${label}-01`, to: addDays(next, -1) });
  }
</script>

<div class="head">
  <div class="metric" role="group" aria-label="Métrique">
    <button type="button" class:on={metric === "hours"} aria-pressed={metric === "hours"} onclick={() => onmetric("hours")}>Heures</button>
    <button type="button" class:on={metric === "km"} aria-pressed={metric === "km"} onclick={() => onmetric("km")}>Km</button>
  </div>
  <span class="meta">par {bucket === "week" ? "semaine" : "mois"}</span>
</div>

{#if data.series.length === 0}
  <p class="empty">Pas assez de données sur cette période</p>
{:else}
  <EChart {option} height="300px" onclick={click} label="Volume par {bucket === 'week' ? 'semaine' : 'mois'} et par sport, en {metric === 'hours' ? 'heures' : 'kilomètres'}" />
  <ul class="legend">
    {#each data.series as s (s.family)}
      <li><span class="dot" style:background="var(--fam-{s.family})"></span>{FAMILY_LABEL[s.family]}</li>
    {/each}
    <li><span class="dash"></span>{avgLabel}</li>
  </ul>
  <p class="hint">Un clic sur une barre limite la période à {bucket === "week" ? "cette semaine" : "ce mois"}.</p>
{/if}

<style>
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.4rem;
  }
  .metric {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 2px;
    gap: 2px;
  }
  .metric button {
    min-height: 34px;
    padding: 0.2rem 0.8rem;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: var(--muted);
    font-size: 0.85rem;
  }
  .metric button.on { background: var(--accent); color: var(--accent-text); font-weight: 600; }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem 0.9rem;
    list-style: none;
    padding: 0;
    margin: 0.4rem 0 0;
    font-size: 0.8rem;
    color: var(--muted);
  }
  .legend li { display: inline-flex; align-items: center; gap: 0.35rem; }
  .dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .dash { width: 14px; border-top: 2px dashed var(--text); display: inline-block; }
  .hint { color: var(--muted); font-size: 0.8rem; margin: 0.3rem 0 0; }
</style>
