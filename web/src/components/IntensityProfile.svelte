<script lang="ts">
  import type { Step, StepGroup } from "../lib/api";
  import { profile } from "../lib/profile";

  let { steps, small = false }: { steps: (Step | StepGroup)[]; small?: boolean } = $props();

  const blocks = $derived(profile(steps));
  const LEVEL = ["", "récupération", "endurance", "tempo", "seuil", "VMA"];
  const label = $derived(
    "Profil d'intensité : " +
      blocks.map((b) => `${Math.round(b.seconds / 60) || "<1"} min ${LEVEL[b.level]}`).join(", "),
  );
</script>

{#if blocks.length}
  <div class="profile" class:sm={small} role="img" aria-label={label}>
    {#each blocks as b, i (i)}
      <span class="lv{b.level}" style:flex-grow={b.seconds}></span>
    {/each}
  </div>
{/if}
