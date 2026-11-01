<script lang="ts">
  import EChart from "../stats/EChart.svelte";
  import type { AidStation, RaceSegment } from "../../lib/api";
  import { themeColors } from "../../lib/stats/echarts";
  import { tooltipTheme } from "../../lib/stats/color";
  import { fmtNumber } from "../../lib/stats/format";

  let {
    profile,
    segments,
    stations,
  }: { profile: [number, number][] | null; segments: RaceSegment[]; stations: AidStation[] } = $props();

  const option = $derived.by(() => {
    const c = themeColors();
    // montée = teinte forte, descente = teinte claire, plat = sans fond
    const fill: Record<RaceSegment["kind"], string> = { montée: c.zones[3], plat: "transparent", descente: c.zones[1] };
    return {
      grid: { top: 16, left: 4, right: 8, bottom: 4, containLabel: true },
      tooltip: {
        ...tooltipTheme(c),
        trigger: "axis",
        formatter: (items: { value: [number, number] }[]) => {
          const [km, ele] = items[0]?.value ?? [0, 0];
          return `${fmtNumber(km, 1)} km<br/>${fmtNumber(ele)} m`;
        },
      },
      xAxis: {
        type: "value",
        min: 0,
        axisLabel: { color: c.muted, formatter: (v: number) => `${fmtNumber(v)} km` },
        axisLine: { lineStyle: { color: c.border } },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: c.muted, formatter: (v: number) => `${fmtNumber(v)} m` },
        splitLine: { lineStyle: { color: c.border, type: "dashed" } },
      },
      series: [
        {
          type: "line",
          data: profile,
          showSymbol: false,
          lineStyle: { color: c.text, width: 1.5 },
          itemStyle: { color: c.text },
          markArea: {
            silent: true,
            data: segments.map((s) => [
              { xAxis: s.start_km, itemStyle: { color: fill[s.kind], opacity: 0.35 } },
              { xAxis: s.end_km },
            ]),
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: c.muted, type: "dashed" },
            label: { color: c.text, formatter: "{b}" },
            data: stations.map((s) => ({ name: s.name, xAxis: s.km })),
          },
        },
      ],
    };
  });
</script>

{#if profile}
  <EChart {option} height="240px" label="Profil d'altitude du parcours, avec les segments et les ravitaillements" />
  <ul class="legend">
    <li><span class="swatch" style:background="var(--z4)"></span>Montée</li>
    <li><span class="swatch" style:background="var(--z2)"></span>Descente</li>
    <li><span class="swatch plat"></span>Plat</li>
  </ul>
{/if}

<style>
  .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; list-style: none; padding: 0; margin: 0; font-size: 12px; color: var(--text-2); }
  .legend li { display: inline-flex; align-items: center; gap: 6px; }
  .swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .swatch.plat { border: 1px solid var(--border); }
</style>
