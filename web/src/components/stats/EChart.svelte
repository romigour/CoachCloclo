<script lang="ts">
  import { onMount } from "svelte";
  import type { EChartsCoreOption, ECharts } from "echarts/core";
  import { echarts } from "../../lib/stats/echarts";

  type ClickParams = { name: string; dataIndex: number; seriesName?: string; data: unknown };

  let {
    option,
    height = "280px",
    onclick,
    label,
  }: {
    option: EChartsCoreOption;
    height?: string;
    onclick?: (params: ClickParams) => void;
    label: string;
  } = $props();

  let el: HTMLDivElement;
  let chart: ECharts | null = null;

  // Init unique au montage ; le thème est porté par l'option (recalculée par le parent
  // via themeColors(), réactif), donc pas de ré-init.
  onMount(() => {
    // Police de l'app pour tous les textes du graphique (axes, légendes, infobulles).
    const font = getComputedStyle(document.documentElement).getPropertyValue("--font-text").trim();
    chart = echarts.init(el, font ? { textStyle: { fontFamily: font } } : undefined, { renderer: "svg" });
    chart.on("click", (p: unknown) => onclick?.(p as ClickParams));
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => chart?.resize()) : null;
    ro?.observe(el);
    return () => {
      ro?.disconnect();
      chart?.dispose();
      chart = null;
    };
  });

  $effect(() => {
    const o = option;
    chart?.setOption(o, true);
  });
</script>

<div bind:this={el} role="img" aria-label={label} style:height style:width="100%"></div>
