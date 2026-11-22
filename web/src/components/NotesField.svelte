<script lang="ts">
  import { NOTES_MAX } from "../lib/goals";

  // Précisions d'un objectif, transmises à Claude : courtes, avec le compteur de caractères.
  let { value = $bindable("") }: { value?: string } = $props();
</script>

<div class="notes">
  <label>
    Précisions
    <textarea
      rows="3"
      maxlength={NOTES_MAX}
      placeholder="Trail enneigé, 400 marches à la fin, je vise un record"
      bind:value
    ></textarea>
  </label>
  <span class="meta count" aria-live="polite">{value.length} / {NOTES_MAX}</span>
</div>

<style>
  .notes { display: flex; flex-direction: column; gap: 4px; }
  .count { align-self: flex-end; }
</style>
