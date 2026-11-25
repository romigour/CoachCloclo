<script lang="ts">
  import Insight from "../Insight.svelte";
  import Races from "../Races.svelte";
  import Records from "../Records.svelte";
  import type { PersonalRecord, StatActivity } from "../../../lib/api";
  import type { Period } from "../../../lib/stats/filter";
  import { lastResultText } from "../../../lib/stats/insights";
  import { raceProgression, raceRows } from "../../../lib/stats/races";

  let {
    all,
    acts,
    period,
    records,
    onchanged,
  }: {
    all: StatActivity[];
    /** Course et trail de la période. */
    acts: StatActivity[];
    period: Period;
    records: PersonalRecord[] | null;
    onchanged: (row: StatActivity) => void;
  } = $props();
</script>

<Insight text={lastResultText(acts, records ?? [], period)} />

<div class="grid">
  <section class="card stack" aria-labelledby="races-title">
    <div><h2 id="races-title">Compétitions</h2><p class="meta">Mes courses officielles</p></div>
    <Races acts={all} rows={raceRows(acts)} progression={raceProgression(acts)} {onchanged} />
  </section>

  <section class="card stack" aria-labelledby="rec-title">
    <div><h2 id="rec-title">Records</h2><p class="meta">Mes meilleurs temps</p></div>
    <Records {records} />
  </section>
</div>

<style>
  .grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
  @media (min-width: 900px) {
    .grid { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 20px; }
  }
  .grid > section { min-width: 0; }
</style>
