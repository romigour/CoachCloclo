<script lang="ts">
  import { untrack } from "svelte";
  import { api, type Cycle, type PlanSettingsInput } from "../lib/api";
  import AvailabilityFields, { availabilityValid } from "./AvailabilityFields.svelte";
  import ErrorBanner from "./ErrorBanner.svelte";

  let {
    cycle,
    onclose,
    onsaved,
  }: { cycle: Cycle; onclose?: () => void; onsaved?: (proposalId: number) => void } = $props();

  // instantané des valeurs de départ : le formulaire ne suit pas les changements de `cycle`
  const initialDays = untrack(() => [...cycle.available_days]);
  const initialLongRun = untrack(() => cycle.long_run_day ?? "");
  const initialBike = untrack(() => cycle.include_bike);
  const perWeek = untrack(() => cycle.sessions_per_week);
  let days = $state([...initialDays]);
  let longRunDay = $state(initialLongRun);
  let includeBike = $state(initialBike);
  let busy = $state(false);
  let error = $state<unknown>(null);

  const daysChanged = $derived(days.length !== initialDays.length || days.some((d) => !initialDays.includes(d)));
  const longRunChanged = $derived(longRunDay !== initialLongRun);
  const bikeChanged = $derived(includeBike !== initialBike);
  const daysOk = $derived(availabilityValid(days, perWeek));
  const canSave = $derived(!busy && (daysChanged || longRunChanged || bikeChanged) && daysOk);

  async function submit() {
    busy = true;
    error = null;
    try {
      const body: PlanSettingsInput = {};
      if (daysChanged) body.available_days = days;
      if (longRunChanged) body.long_run_day = longRunDay; // "" = retirer le jour
      if (bikeChanged) body.include_bike = includeBike;
      const r = await api.updatePlanSettings(body);
      onsaved?.(r.proposal_id);
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }
</script>

<div class="modal-backdrop">
  <div class="modal wide card stack" role="dialog" aria-label="Réglages du plan">
    <h2>Réglages du plan</h2>
    <AvailabilityFields bind:days bind:longRunDay bind:includeBike {perWeek} />
    {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
    <ErrorBanner {error} />
    <div class="row end">
      <button class="primary" onclick={submit} disabled={!canSave}>Enregistrer</button>
      <button onclick={() => onclose?.()} disabled={busy}>Annuler</button>
    </div>
  </div>
</div>
