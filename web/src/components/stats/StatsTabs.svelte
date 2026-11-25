<script lang="ts">
  import { TABS, type StatsTab } from "../../lib/stats/tabs";

  let { tab }: { tab: StatsTab } = $props();

  let nav: HTMLElement;

  // Téléphone : l'onglet courant reste visible dans la barre défilante.
  $effect(() => {
    const link = nav.querySelector<HTMLElement>(`[data-tab="${tab}"]`);
    if (link) nav.scrollLeft = link.offsetLeft - nav.offsetLeft - 16;
  });
</script>

<nav class="tabs" aria-label="Sous-pages de statistiques" bind:this={nav}>
  {#each TABS as t (t.key)}
    <a href={t.hash} data-tab={t.key} class:on={t.key === tab} aria-current={t.key === tab ? "page" : undefined}>{t.label}</a>
  {/each}
</nav>

<style>
  .tabs {
    display: flex;
    gap: 4px;
    overflow-x: auto;
    border-bottom: 1px solid var(--border);
    scrollbar-width: thin;
  }
  a {
    flex: none;
    padding: 10px 14px;
    color: var(--text-2);
    font-weight: 500;
    text-decoration: none;
    border-bottom: 2px solid transparent;
  }
  a:hover { color: var(--text); }
  a.on { color: var(--text); font-weight: 700; border-bottom-color: var(--accent); }
</style>
