<script lang="ts">
  import EChart from "../EChart.svelte";
  import Insight from "../Insight.svelte";
  import type { StatActivity } from "../../../lib/api";
  import { tooltipTheme } from "../../../lib/stats/color";
  import { themeColors } from "../../../lib/stats/echarts";
  import type { Period } from "../../../lib/stats/filter";
  import { fmtMinutes, fmtMonth, fmtMonthShort } from "../../../lib/stats/format";
  import { splitText } from "../../../lib/stats/insights";
  import { monthlySplit, split, type Split } from "../../../lib/stats/intensity";
  import { zoneDistribution, zoneShares } from "../../../lib/stats/running";

  /** Course et trail de la période. */
  let { acts, period }: { acts: StatActivity[]; period: Period } = $props();

  const LEVELS: { key: keyof Split; label: string; zones: string }[] = [
    { key: "easy", label: "Facile", zones: "Z1-2" },
    { key: "moderate", label: "Moyen", zones: "Z3" },
    { key: "hard", label: "Dur", zones: "Z4-5" },
  ];
  const EMPTY = "Pas assez de données sur cette période";

  const zones = $derived(zoneDistribution(acts));
  const shares = $derived(zones ? split(zones) : null);
  const months = $derived(monthlySplit(acts, period));
  const hasMonths = $derived(months.some((m) => m.split !== null));
  const colors = $derived.by(() => {
    const z = themeColors().zones;
    return { easy: z[1], moderate: z[2], hard: z[4] };
  });
  const pct = (v: number) => Math.round(v * 100);

  const zonesOption = $derived.by(() => {
    const c = themeColors();
    const z = zones ?? [];
    const parts = zoneShares(z).map(pct);
    return {
      grid: { top: 18, left: 4, right: 8, bottom: 4, containLabel: true },
      tooltip: {
        ...tooltipTheme(c),
        trigger: "item",
        formatter: (p: { dataIndex: number }) =>
          `<b>Zone ${p.dataIndex + 1}</b><br/>${fmtMinutes(Math.round(z[p.dataIndex] / 60))} · ${parts[p.dataIndex]} %`,
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
          // Rampe d'intensité de l'app (--z1 … --z5), la même que les profils de séance.
          data: parts.map((v, i) => ({ value: v, itemStyle: { color: c.zones[i], borderRadius: [3, 3, 0, 0] } })),
          barMaxWidth: 40,
          label: { show: true, position: "top", color: c.muted, formatter: (p: { value: number }) => `${p.value} %` },
        },
      ],
    };
  });

  const monthsOption = $derived.by(() => {
    const c = themeColors();
    return {
      grid: { top: 36, left: 4, right: 8, bottom: 4, containLabel: true },
      legend: { top: 0, left: 0, textStyle: { color: c.muted }, itemWidth: 12, itemHeight: 12, data: LEVELS.map((l) => l.label) },
      tooltip: {
        ...tooltipTheme(c),
        trigger: "axis",
        axisPointer: { type: "shadow" },
        formatter: (items: { dataIndex: number }[]) => {
          const m = months[items[0]?.dataIndex ?? 0];
          if (!m) return "";
          const s = m.split;
          const body = s ? LEVELS.map((l) => `${l.label} : <b>${pct(s[l.key])} %</b>`).join("<br/>") : "Pas assez de données";
          return `<b>${fmtMonth(m.month)}</b><br/>${body}`;
        },
      },
      xAxis: {
        type: "category",
        data: months.map((m) => m.month),
        axisLabel: { color: c.muted, formatter: fmtMonthShort, hideOverlap: true },
        axisLine: { lineStyle: { color: c.border } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        max: 100,
        axisLabel: { color: c.muted, formatter: (v: number) => `${v} %` },
        splitLine: { lineStyle: { color: c.border, type: "dashed" } },
      },
      series: LEVELS.map((l) => ({
        type: "bar",
        stack: "effort",
        name: l.label,
        data: months.map((m) => (m.split ? m.split[l.key] * 100 : null)),
        barMaxWidth: 32,
        itemStyle: { color: colors[l.key], borderColor: c.surface, borderWidth: 1 },
        markLine:
          l.key === "easy"
            ? {
                silent: true,
                symbol: "none",
                label: { show: false },
                lineStyle: { color: c.text, type: "dashed" },
                data: [{ yAxis: 80 }],
              }
            : undefined,
      })),
    };
  });
</script>

<section class="card stack" aria-labelledby="split-title">
  <div><h2 id="split-title">Facile, moyen, dur</h2><p class="meta">Est-ce que je cours à la bonne intensité ? Course et trail, zones de la montre (Garmin)</p></div>
  {#if shares}
    <div class="split" role="group" aria-label="Facile, moyen, dur">
      <div class="bar" aria-hidden="true">
        {#each LEVELS as l (l.key)}<span style:width="{shares[l.key] * 100}%" style:background={colors[l.key]}></span>{/each}
        <i class="mark"></i>
      </div>
      <ul class="levels">
        {#each LEVELS as l (l.key)}
          <li><span class="swatch" style:background={colors[l.key]}></span>{l.label} <span class="meta">({l.zones})</span> <strong>{pct(shares[l.key])} %</strong></li>
        {/each}
        <li class="meta">Trait : repère 80 % facile</li>
      </ul>
    </div>
    <Insight text={splitText(shares)} />
  {:else}
    <p class="empty">{EMPTY}</p>
  {/if}
</section>

<div class="grid">
  <section class="card stack" aria-labelledby="months-title">
    <div><h2 id="months-title">Évolution par mois</h2><p class="meta">Un mois sans assez de données reste vide. Pointillé : 80 % facile</p></div>
    {#if hasMonths}
      <EChart option={monthsOption} height="260px" label="Part facile, moyenne et dure de chaque mois" />
    {:else}
      <p class="empty">{EMPTY}</p>
    {/if}
  </section>

  <section class="card stack" aria-labelledby="zones-title">
    <div><h2 id="zones-title">Zones FC</h2><p class="meta">Temps cumulé par zone sur la période</p></div>
    {#if shares}
      <EChart option={zonesOption} height="260px" label="Répartition du temps par zone de fréquence cardiaque" />
    {:else}
      <p class="empty">{EMPTY}</p>
    {/if}
  </section>
</div>

<style>
  .grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
  @media (min-width: 900px) {
    .grid { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 20px; }
  }
  .grid > section { min-width: 0; }
  .bar { position: relative; display: flex; height: 22px; border-radius: 8px; overflow: hidden; background: var(--sunken); }
  .mark { position: absolute; left: 80%; top: 0; bottom: 0; width: 2px; background: var(--text); }
  .levels { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px 20px; font-size: 13.5px; }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; }
  strong { font-variant-numeric: tabular-nums; }
</style>
