<script lang="ts">
  import type { Goal } from "../lib/api";
  import { goalLabel } from "../lib/goals";
  import PriorityBadge from "./PriorityBadge.svelte";

  let { goal }: { goal: Goal } = $props();

  const label = $derived(goalLabel(goal));
</script>

<!-- jour de course d'un objectif du cycle, dans le calendrier du plan -->
<div class="race-day" role="note" aria-label="Course : {label}">
  <span class="kind">Course</span>
  <span class="t">{label}</span>
  {#if goal.type === "trail"}<span class="meta">{goal.d_plus_m} m D+</span>{/if}
  <PriorityBadge priority={goal.priority} />
</div>

<style>
  .race-day {
    display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 8px; border-radius: 8px;
    border: 2px solid var(--accent); background: var(--accent-soft); font-size: 13px;
  }
  .kind { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--accent-strong); }
  .t { font-weight: 600; }
</style>
