<script lang="ts">
  import EChart from "./EChart.svelte";
  import type { Period } from "../../lib/stats/filter";
  import type { WeekStats } from "../../lib/stats/consistency";
  import { themeColors } from "../../lib/stats/echarts";
  import { fmtDay, fmtMinutes, MONTHS_SHORT } from "../../lib/stats/format";
  import { withAlpha } from "../../lib/stats/color";

  let {
    days,
    period,
    stats,
    onpick,
  }: {
    days: [string, number][];
    period: Period;
    stats: WeekStats;
    onpick: (period: Period) => void;
  } = $props();

  // Largeur mesurée à la main (pas de bind:clientWidth : ResizeObserver peut manquer, ex. jsdom).
  let wrap = $state<HTMLDivElement>();
  let width = $state(0);
  $effect(() => {
    if (!wrap) return;
    width = wrap.clientWidth;
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => (width = wrap?.clientWidth ?? 0));
    ro.observe(wrap);
    return () => ro.disconnect();
  });

  const years = $derived.by(() => {
    const out: number[] = [];
    for (let y = Number(period.from.slice(0, 4)); y <= Number(period.to.slice(0, 4)); y++) out.push(y);
    return out;
  });

  // Cases carrées : la largeur disponible fixe la taille des cases (53 semaines par an).
  const left = $derived(years.length > 1 ? 52 : 28);
  const cell = $derived(width > 0 ? Math.max(6, Math.min(18, Math.floor((width - left - 8) / 54))) : 12);
  const rowH = $derived(cell * 7 + 26);
  const height = $derived(`${years.length * rowH + 52}px`);

  const option = $derived.by(() => {
    const c = themeColors();
    const pieces = [
      { min: 1, max: 29, label: "< 30 min", color: withAlpha(c.accent, 0.3) },
      { min: 30, max: 59, label: "30 à 59 min", color: withAlpha(c.accent, 0.55) },
      { min: 60, max: 89, label: "1 h à 1 h 30", color: withAlpha(c.accent, 0.8) },
      { min: 90, label: "≥ 1 h 30", color: c.accent },
    ];
    return {
      tooltip: {
        formatter: (p: { data: [string, number] }) => `${fmtDay(p.data[0])}<br/><b>${fmtMinutes(p.data[1])}</b> d'activité`,
      },
      visualMap: {
        type: "piecewise",
        pieces,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemWidth: 12,
        itemHeight: 12,
        itemGap: 8,
        textStyle: { color: c.muted, fontSize: 11 },
      },
      calendar: years.map((y, i) => ({
        top: 22 + i * rowH,
        left,
        right: 8,
        cellSize: [cell, cell],
        range: String(y),
        splitLine: { lineStyle: { color: c.muted, width: 1, opacity: 0.5 } },
        itemStyle: { color: "transparent", borderColor: withAlpha(c.border, 0.8), borderWidth: 1 },
        yearLabel: { show: years.length > 1, position: "left", margin: 26, color: c.text, fontSize: 12 },
        monthLabel: { nameMap: MONTHS_SHORT, color: c.muted, fontSize: 10, margin: 4 },
        dayLabel: { firstDay: 1, nameMap: ["D", "L", "M", "M", "J", "V", "S"], color: c.muted, fontSize: 9, margin: 4 },
      })),
      series: years.map((y, i) => ({
        type: "heatmap",
        coordinateSystem: "calendar",
        calendarIndex: i,
        data: days.filter(([d]) => d.startsWith(`${y}-`)),
      })),
    };
  });

  function click(p: { data: unknown }) {
    const [date] = p.data as [string, number];
    onpick({ from: date, to: date });
  }

  const unit = (n: number) => (n > 1 ? "semaines" : "semaine");
  const ratio = $derived(stats.totalWeeks > 0 ? stats.activeWeeks / stats.totalWeeks : 0);
</script>

{#if days.length === 0}
  <p class="empty">Pas assez de données sur cette période</p>
{:else}
  <div class="weeks">
    <div class="tile">
      <span class="label">Semaines actives</span>
      <span><strong>{stats.activeWeeks}</strong> <span class="meta">/ {stats.totalWeeks}</span></span>
      <span class="bar" aria-hidden="true"><span style:width="{Math.round(ratio * 100)}%"></span></span>
    </div>
    <div class="tile">
      <span class="label">Série actuelle</span>
      <span><strong>{stats.currentStreak}</strong> <span class="meta">{unit(stats.currentStreak)}</span></span>
    </div>
    <div class="tile">
      <span class="label">Record de série</span>
      <span><strong>{stats.bestStreak}</strong> <span class="meta">{unit(stats.bestStreak)}</span></span>
    </div>
  </div>
  <div class="cal" bind:this={wrap}>
    <EChart {option} {height} onclick={click} label="Calendrier des séances : durée d'activité par jour" />
  </div>
  <p class="hint">Un clic sur un jour limite la période à ce jour.</p>
{/if}

<style>
  .weeks {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.5rem;
    margin-bottom: 0.6rem;
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    padding: 0.5rem 0.6rem;
    border-radius: 10px;
    background: var(--bg);
    min-width: 0;
  }
  .label { color: var(--muted); font-size: 0.8rem; }
  strong { font-size: 1.4rem; font-variant-numeric: tabular-nums; }
  .bar {
    display: block;
    height: 5px;
    border-radius: 3px;
    background: var(--border);
    overflow: hidden;
    margin-top: 0.2rem;
  }
  .bar span { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
  .cal { width: 100%; min-width: 0; }
  .hint { color: var(--muted); font-size: 0.8rem; margin: 0.2rem 0 0; }
</style>
