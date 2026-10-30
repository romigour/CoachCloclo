<script lang="ts">
  // Remplaçant d'EChart.svelte dans les tests (jsdom n'a pas de rendu SVG exploitable).
  let {
    option,
    label,
  }: {
    option: unknown;
    label: string;
    height?: string;
    onclick?: (params: { name: string; dataIndex: number; seriesName?: string; data: unknown }) => void;
  } = $props();
</script>

<div role="img" aria-label={label} data-option={JSON.stringify(option)}></div>
