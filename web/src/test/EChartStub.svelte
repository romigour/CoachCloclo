<script lang="ts">
  // Remplaçant d'EChart.svelte dans les tests (jsdom n'a pas de rendu SVG exploitable).
  // Un événement DOM « echartclick » (detail = paramètres ECharts) simule un clic sur le graphique.
  type ClickParams = { name: string; dataIndex: number; seriesName?: string; data: unknown };
  let {
    option,
    label,
    onclick,
  }: {
    option: unknown;
    label: string;
    height?: string;
    onclick?: (params: ClickParams) => void;
  } = $props();

  let el = $state<HTMLDivElement>();
  $effect(() => {
    if (!el) return;
    const fire = (e: Event) => onclick?.((e as CustomEvent<ClickParams>).detail);
    el.addEventListener("echartclick", fire);
    return () => el?.removeEventListener("echartclick", fire);
  });
</script>

<div bind:this={el} role="img" aria-label={label} data-option={JSON.stringify(option)}></div>
