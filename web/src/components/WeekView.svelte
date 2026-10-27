<script lang="ts">
  import type { Week } from "../lib/api";
  import { formatDay } from "../lib/dates";
  import SessionCard from "./SessionCard.svelte";

  let {
    week,
    readonly = false,
    onchanged,
    onerror,
  }: { week: Week; readonly?: boolean; onchanged?: () => void; onerror?: (e: unknown) => void } = $props();
</script>

<section class="week">
  <h2>Semaine {week.week_index} <small>du {formatDay(week.week_monday)}</small></h2>
  {#each week.sessions as s (s.id)}
    <SessionCard session={s} weekMonday={week.week_monday} {readonly} {onchanged} {onerror} />
  {/each}
</section>
