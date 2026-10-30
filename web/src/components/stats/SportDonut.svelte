<script lang="ts">
  import EChart from "./EChart.svelte";
  import type { Family } from "../../lib/api";
  import { themeColors } from "../../lib/stats/echarts";
  import { fmtNumber } from "../../lib/stats/format";
  import { FAMILY_LABEL } from "../../lib/labels";
  import { tooltipTheme } from "../../lib/stats/color";

  let { share }: { share: { family: Family; hours: number }[] } = $props();

  const total = $derived(share.reduce((s, x) => s + x.hours, 0));
  const pct = (h: number) => (total > 0 ? Math.round((h / total) * 100) : 0);

  const option = $derived.by(() => {
    const c = themeColors();
    return {
      tooltip: {
        ...tooltipTheme(c),
        trigger: "item",
        formatter: (p: { name: string; value: number; percent: number; marker: string }) =>
          `${p.marker}${p.name}<br/><b>${fmtNumber(p.value, 1)} h</b> · ${Math.round(p.percent)} %`,
      },
      series: [
        {
          type: "pie",
          radius: ["58%", "88%"],
          center: ["50%", "50%"],
          avoidLabelOverlap: true,
          label: { show: false },
          labelLine: { show: false },
          itemStyle: { borderColor: "transparent", borderWidth: 2, borderRadius: 4 },
          emphasis: { scale: true, scaleSize: 4 },
          data: share.map((s) => ({ name: FAMILY_LABEL[s.family], value: s.hours, itemStyle: { color: c.families[s.family] } })),
        },
      ],
    };
  });
</script>

{#if share.length === 0}
  <p class="empty">Pas assez de données sur cette période</p>
{:else}
  <div class="donut">
    <EChart {option} height="200px" label="Répartition du temps d'activité par sport" />
    <div class="center" aria-hidden="true">
      <strong>{fmtNumber(total, 1)}</strong>
      <span>heures</span>
    </div>
  </div>
  <ul class="list">
    {#each share as s (s.family)}
      <li>
        <span class="dot" style:background="var(--fam-{s.family})"></span>
        <span class="name">{FAMILY_LABEL[s.family]}</span>
        <span class="hours">{fmtNumber(s.hours, 1)} h</span>
        <span class="pct">{pct(s.hours)} %</span>
        <span class="track" aria-hidden="true"><span style:width="{pct(s.hours)}%" style:background="var(--fam-{s.family})"></span></span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .donut { position: relative; }
  .center {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }
  .center strong { font-size: 1.5rem; line-height: 1.1; font-variant-numeric: tabular-nums; }
  .center span { color: var(--muted); font-size: 0.8rem; }
  .list { list-style: none; padding: 0; margin: 0.5rem 0 0; font-size: 0.9rem; }
  .list li {
    display: grid;
    grid-template-columns: 12px minmax(0, 1fr) auto 3rem;
    grid-template-areas: "dot name hours pct" ". track track track";
    align-items: center;
    column-gap: 0.5rem;
    row-gap: 0.2rem;
    padding: 0.3rem 0;
  }
  .dot { grid-area: dot; width: 10px; height: 10px; border-radius: 3px; }
  .name { grid-area: name; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hours { grid-area: hours; font-variant-numeric: tabular-nums; }
  .pct { grid-area: pct; text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
  .track { grid-area: track; height: 4px; border-radius: 2px; background: var(--border); overflow: hidden; }
  .track span { display: block; height: 100%; border-radius: 2px; }
</style>
