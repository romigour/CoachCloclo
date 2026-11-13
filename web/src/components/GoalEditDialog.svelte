<script lang="ts">
  import { untrack } from "svelte";
  import { api, type Goal, type GoalChange, type GoalUpdate, type Priority } from "../lib/api";
  import { PRIORITY_LABELS } from "../lib/labels";
  import { addDays, todayIso } from "../lib/dates";
  import { fmtTargetTime, parseTargetTime } from "../lib/race";
  import ErrorBanner from "./ErrorBanner.svelte";

  let {
    goal,
    today = todayIso(),
    onclose,
    onsaved,
  }: { goal: Goal; today?: string; onclose?: () => void; onsaved?: (change: GoalChange) => void } = $props();

  // instantané des valeurs de départ : le formulaire ne suit pas les changements de `goal`
  const initialTime = untrack(() => (goal.target_time_s != null ? fmtTargetTime(goal.target_time_s) : ""));
  let date = $state(untrack(() => goal.race_date));
  let time = $state(initialTime);
  let priority = $state<Priority>(untrack(() => goal.priority));
  let busy = $state(false);
  let error = $state<unknown>(null);

  // jamais de date passée : le backend la refuserait
  const minDate = $derived(addDays(today, 1));
  const timeChanged = $derived(time.trim() !== initialTime);
  const timeInvalid = $derived(timeChanged && !Number.isFinite(parseTargetTime(time)));
  const dateChanged = $derived(date !== goal.race_date);
  const priorityChanged = $derived(priority !== goal.priority);
  const canSave = $derived(!busy && !!date && (dateChanged || timeChanged || priorityChanged) && !timeInvalid);

  async function submit() {
    busy = true;
    error = null;
    try {
      const body: GoalUpdate = {};
      if (dateChanged) body.race_date = date;
      if (timeChanged) body.target_time = time.trim();
      if (priorityChanged) body.priority = priority;
      const change = await api.updateGoal(goal.id, body);
      onsaved?.(change);
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
    <fieldset>
      <legend>Priorité</legend>
      <div class="segmented">
        {#each Object.entries(PRIORITY_LABELS) as [value, label] (value)}
          <label>
            <input type="radio" name="edit-priority" {value} bind:group={priority} />
            <span>{label}</span>
          </label>
        {/each}
      </div>
    </fieldset>
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
