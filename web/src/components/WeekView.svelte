<script lang="ts">
  import { api, type Activity, type Week } from "../lib/api";
  import { formatDay } from "../lib/dates";
  import SessionCard from "./SessionCard.svelte";

  let {
    week,
    readonly = false,
    onchanged,
    onerror,
  }: { week: Week; readonly?: boolean; onchanged?: () => void; onerror?: (e: unknown) => void } = $props();

  let activities = $state<Activity[]>([]);

  // recharge les activités de la semaine à chaque rechargement du plan
  $effect(() => {
    if (readonly) return;
    const idx = week.week_index;
    api
      .activities(idx)
      .then((a) => (activities = a))
      .catch(() => (activities = []));
  });
</script>

<section class="week">
  <h2>Semaine {week.week_index} <small>du {formatDay(week.week_monday)}</small></h2>
  {#each week.sessions as s (s.id)}
    <SessionCard session={s} weekMonday={week.week_monday} {readonly} {activities} {onchanged} {onerror} />
  {/each}
</section>
