<script lang="ts" module>
  /** Assez de jours cochés pour caser toutes les séances de la semaine. */
  export function availabilityValid(days: string[], perWeek: number): boolean {
    return days.length >= perWeek;
  }
</script>

<script lang="ts">
  import { WEEKDAYS } from "../lib/dates";

  let {
    days = $bindable(),
    longRunDay = $bindable(),
    perWeek,
  }: { days: string[]; longRunDay: string; perWeek: number } = $props();

  const cap = (d: string) => d.charAt(0).toUpperCase() + d.slice(1);

  function toggle(day: string, checked: boolean) {
    // reste dans l'ordre de la semaine, quel que soit l'ordre des clics
    days = WEEKDAYS.filter((d) => (d === day ? checked : days.includes(d)));
    if (!checked && longRunDay === day) longRunDay = "";
  }
</script>

<fieldset>
  <legend>Jours possibles</legend>
  <div class="chips" role="group" aria-label="Jours possibles">
    {#each WEEKDAYS as d (d)}
      <label class="day">
        <input type="checkbox" checked={days.includes(d)} onchange={(e) => toggle(d, e.currentTarget.checked)} />
        <span>{cap(d)}</span>
      </label>
    {/each}
  </div>
  {#if !availabilityValid(days, perWeek)}
    <span class="hint" role="alert">Coche au moins {perWeek} jours</span>
  {/if}
</fieldset>

<label>
  Jour de la sortie longue
  <select bind:value={longRunDay}>
    <option value="">Aucun</option>
    {#each WEEKDAYS.filter((d) => days.includes(d)) as d (d)}
      <option value={d}>{cap(d)}</option>
    {/each}
  </select>
</label>

<style>
  .day { flex-direction: row; align-items: center; gap: 6px; }
</style>
