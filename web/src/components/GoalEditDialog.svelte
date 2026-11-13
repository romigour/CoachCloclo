<script lang="ts">
  import { untrack } from "svelte";
  import { api, type Goal } from "../lib/api";
  import { addDays, todayIso } from "../lib/dates";
  import { fmtTargetTime, parseTargetTime } from "../lib/race";
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
  let busy = $state(false);
  let error = $state<unknown>(null);

  // jamais de date passée : le backend la refuserait
  const minDate = $derived(addDays(today, 1));
  const timeChanged = $derived(time.trim() !== initialTime);
  const timeInvalid = $derived(timeChanged && !Number.isFinite(parseTargetTime(time)));
  const dateChanged = $derived(date !== goal.race_date);
  const canSave = $derived(!busy && !!date && (dateChanged || timeChanged) && !timeInvalid);

  async function submit() {
    busy = true;
    error = null;
    try {
      const body: { race_date?: string; target_time?: string } = {};
      if (dateChanged) body.race_date = date;
      if (timeChanged) body.target_time = time.trim();
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
  <div class="modal wide card stack" role="dialog" aria-label="Modifier l'objectif">
    <h2>Modifier l'objectif</h2>
    <div class="pair">
      <label>
        Date de la course
        <input type="date" min={minDate} bind:value={date} required />
      </label>
      <label>
        Temps visé (h:mm)
        <input type="text" inputmode="numeric" placeholder="1:50" bind:value={time} aria-invalid={timeInvalid} />
      </label>
    </div>
    {#if timeInvalid}<span class="hint" role="alert">Temps visé invalide : format attendu h:mm, ex. 1:50</span>{/if}
    <p class="meta">Pour changer la distance ou le type de course, crée un nouvel objectif.</p>
    {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
    <ErrorBanner {error} />
    <div class="row end">
      <button class="primary" onclick={submit} disabled={!canSave}>Enregistrer</button>
      <button onclick={() => onclose?.()} disabled={busy}>Annuler</button>
    </div>
  </div>
</div>

<style>
  /* date et temps côte à côte quand la place le permet */
  .pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
</style>
