<script lang="ts">
  import { untrack } from "svelte";
  import { api, type Goal } from "../lib/api";
  import { addDays, todayIso } from "../lib/dates";
  import { fmtTargetTime, parseTargetTime } from "../lib/race";
  import { WEEKDAYS } from "../lib/dates";
  import AvailabilityFields, { availabilityValid } from "./AvailabilityFields.svelte";
  import ErrorBanner from "./ErrorBanner.svelte";

  let {
    goal,
    today = todayIso(),
    onclose,
    onsaved,
  }: { goal: Goal; today?: string; onclose?: () => void; onsaved?: (proposalId: number) => void } = $props();

  // instantané des valeurs de départ : le formulaire ne suit pas les changements de `goal`
  const initialTime = untrack(() => (goal.target_time_s != null ? fmtTargetTime(goal.target_time_s) : ""));
  let date = $state(untrack(() => goal.race_date));
  let time = $state(initialTime);
  const initialDays = untrack(() => goal.available_days ?? [...WEEKDAYS]);
  const initialLongRun = untrack(() => goal.long_run_day ?? "");
  let days = $state([...initialDays]);
  let longRunDay = $state(initialLongRun);
  const initialBike = untrack(() => goal.include_bike ?? false);
  let includeBike = $state(initialBike);
  let busy = $state(false);
  let error = $state<unknown>(null);

  // jamais de date passée : le backend la refuserait
  const minDate = $derived(addDays(today, 1));
  const timeChanged = $derived(time.trim() !== initialTime);
  const timeInvalid = $derived(timeChanged && !Number.isFinite(parseTargetTime(time)));
  const dateChanged = $derived(date !== goal.race_date);
  const daysChanged = $derived(days.length !== initialDays.length || days.some((d) => !initialDays.includes(d)));
  const longRunChanged = $derived(longRunDay !== initialLongRun);
  const bikeChanged = $derived(includeBike !== initialBike);
  const daysOk = $derived(availabilityValid(days, goal.sessions_per_week));
  const canSave = $derived(
    !busy && !!date && (dateChanged || timeChanged || daysChanged || longRunChanged || bikeChanged) && !timeInvalid && daysOk,
  );

  async function submit() {
    busy = true;
    error = null;
    try {
      const body: { race_date?: string; target_time?: string; available_days?: string[]; long_run_day?: string; include_bike?: boolean } = {};
      if (dateChanged) body.race_date = date;
      if (timeChanged) body.target_time = time.trim();
      if (daysChanged) body.available_days = days;
      if (longRunChanged) body.long_run_day = longRunDay; // "" = retirer le jour
      if (bikeChanged) body.include_bike = includeBike;
      const r = await api.updateGoal(goal.id, body);
      onsaved?.(r.proposal_id);
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }
</script>

<div class="modal-backdrop">
  <div class="modal card stack" role="dialog" aria-label="Modifier l'objectif">
    <h2>Modifier l'objectif</h2>
    <label>
      Date de la course
      <input type="date" min={minDate} bind:value={date} required />
    </label>
    <label>
      Temps visé (h:mm)
      <input type="text" inputmode="numeric" placeholder="1:50" bind:value={time} aria-invalid={timeInvalid} />
    </label>
    {#if timeInvalid}<span class="hint" role="alert">Temps visé invalide : format attendu h:mm, ex. 1:50</span>{/if}
    <AvailabilityFields bind:days bind:longRunDay bind:includeBike perWeek={goal.sessions_per_week} />
    <p class="meta">Pour changer la distance ou le type de course, crée un nouvel objectif.</p>
    {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
    <ErrorBanner {error} />
    <div class="row end">
      <button class="primary" onclick={submit} disabled={!canSave}>Enregistrer</button>
      <button onclick={() => onclose?.()} disabled={busy}>Annuler</button>
    </div>
  </div>
</div>
