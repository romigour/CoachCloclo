<script lang="ts">
  /** Phrase d'interprétation d'un bloc ; rien si les données ne disent rien. */
  let { text }: { text: string | null } = $props();
</script>

{#if text}<p class="insight">{text}</p>{/if}

<style>
  .insight {
    margin: 0.4rem 0 0;
    padding: 8px 12px;
    border-left: 3px solid var(--accent);
    border-radius: 0 8px 8px 0;
    background: var(--sunken);
    font-size: 13.5px;
    font-weight: 500;
  }
</style>
