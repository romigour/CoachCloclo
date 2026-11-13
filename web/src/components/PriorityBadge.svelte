<script lang="ts">
  import type { Priority } from "../lib/api";
  import { PRIORITY_LABELS } from "../lib/labels";

  let { priority }: { priority: Priority } = $props();
</script>

<span class="pill priority {priority}">{PRIORITY_LABELS[priority]}</span>

<style>
  .priority.principal { color: var(--accent-text); background: var(--accent); }
  .priority.secondaire { color: var(--accent-strong); background: var(--accent-soft); }
  .priority.plaisir { color: var(--todo); background: var(--todo-soft); }
</style>
