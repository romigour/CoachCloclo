<script lang="ts">
  import { onMount } from "svelte";
  import type { EChartsCoreOption, ECharts } from "echarts/core";
  import { echarts } from "../../lib/stats/echarts";

  let {
    option,
    height = "280px",
    onclick,
    label,
  }: {
    option: EChartsCoreOption;
    height?: string;
    onclick?: (params: { name: string; dataIndex: number; seriesName?: string; data: unknown }) => void;
    label: string;
  } = $props();

  let el: HTMLDivElement;
  let chart: ECharts | null = null;
  // Les options sont reposées avec les couleurs du thème courant : le parent les recalcule
  // via themeColors(), donc on ré-init aussi quand le schéma de couleurs change.
  let scheme = $state(0);

  function init() {
    chart?.dispose();
    chart = echarts.init(el, undefined, { renderer: "svg" });
    chart.on("click", (p: any) => onclick?.(p));
    chart.setOption(option, true);
  }

  onMount(() => {
    init();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => chart?.resize()) : null;
    ro?.observe(el);
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onScheme = () => {
      scheme++;
    };
    mq?.addEventListener?.("change", onScheme);
    return () => {
      ro?.disconnect();
      mq?.removeEventListener?.("change", onScheme);
      chart?.dispose();
      chart = null;
    };
  });

  $effect(() => {
    void scheme;
    if (!chart) return;
    if (scheme > 0) init();
  });

  $effect(() => {
    const o = option;
    chart?.setOption(o, true);
  });
</script>

<div bind:this={el} role="img" aria-label={label} style:height style:width="100%"></div>
