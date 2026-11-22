<script lang="ts">
  import { untrack } from "svelte";
  import { api, ApiError, type Cycle, type PlanSettingsInput } from "../lib/api";
  import AvailabilityFields, { availabilityValid } from "./AvailabilityFields.svelte";
  import ErrorBanner from "./ErrorBanner.svelte";

  let {
    cycle,
    onclose,
    onsaved,
    onfailed,
  }: {
    cycle: Cycle;
    onclose?: () => void;
    /** `null` : nombre de séances changé, la suite du plan a été régénérée (pas de proposition). */
    onsaved?: (proposalId: number | null) => void;
    /** Régénération en échec : les réglages sont déjà enregistrés, la page affiche l'erreur et « Générer ». */
    onfailed?: (error: unknown) => void;
  } = $props();

  // instantané des valeurs de départ : le formulaire ne suit pas les changements de `cycle`
  const initialDays = untrack(() => [...cycle.available_days]);
  const initialLongRun = untrack(() => cycle.long_run_day ?? "");
  const initialBike = untrack(() => cycle.include_bike);
  const initialPerWeek = untrack(() => cycle.sessions_per_week);
  let days = $state([...initialDays]);
  let longRunDay = $state(initialLongRun);
  let includeBike = $state(initialBike);
  let perWeek = $state(initialPerWeek);
  let busy = $state(false);
  let error = $state<unknown>(null);

  const daysChanged = $derived(days.length !== initialDays.length || days.some((d) => !initialDays.includes(d)));
  const longRunChanged = $derived(longRunDay !== initialLongRun);
  const bikeChanged = $derived(includeBike !== initialBike);
  const perWeekChanged = $derived(perWeek !== initialPerWeek);
  const daysOk = $derived(availabilityValid(days, perWeek));
  const canSave = $derived(!busy && (daysChanged || longRunChanged || bikeChanged || perWeekChanged) && daysOk);

  async function submit() {
    busy = true;
    error = null;
    try {
      const body: PlanSettingsInput = {};
      if (daysChanged) body.available_days = days;
      if (longRunChanged) body.long_run_day = longRunDay; // "" = retirer le jour
      if (bikeChanged) body.include_bike = includeBike;
      if (perWeekChanged) body.sessions_per_week = perWeek;
      const r = await api.updatePlanSettings(body);
      onsaved?.(r.proposal_id);
    } catch (e) {
      const refused = e instanceof ApiError && e.status === 422; // rien n'a été enregistré
      if (perWeekChanged && !refused) onfailed?.(e);
      else error = e;
    } finally {
      busy = false;
    }
  }
</script>

<div class="modal-backdrop">
  <div class="modal wide card stack" role="dialog" aria-label="Réglages du plan">
    <h2>Réglages du plan</h2>
    <fieldset>
      <legend>Séances par semaine</legend>
      <div class="segmented">
        {#each [2, 3, 4, 5, 6, 7] as n (n)}
          <label>
            <input type="radio" name="settings-per-week" value={n} bind:group={perWeek} />
            <span>{n}</span>
          </label>
        {/each}
      </div>
      {#if perWeekChanged}
        <p class="hint">
          Changer le nombre de séances recalcule la suite du plan à partir de cette semaine ; tu devras le valider à
          nouveau.
        </p>
      {/if}
    </fieldset>
    <AvailabilityFields bind:days bind:longRunDay bind:includeBike {perWeek} />
    {#if busy}
      <p class="meta" role="status">
        {perWeekChanged ? "Claude recalcule ton plan…" : "Claude ajuste ton plan…"} (cela peut prendre une minute)
      </p>
    {/if}
    <ErrorBanner {error} />
    <div class="row end">
      <button class="primary" onclick={submit} disabled={!canSave}>Enregistrer</button>
      <button onclick={() => onclose?.()} disabled={busy}>Annuler</button>
    </div>
  </div>
</div>
