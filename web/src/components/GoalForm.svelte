<script lang="ts">
  import { untrack } from "svelte";
  import type { Cycle, GoalInput, Priority } from "../lib/api";
  import { addDays, todayIso, WEEKDAYS } from "../lib/dates";
  import { PRIORITY_LABELS } from "../lib/labels";
  import { parseTargetTime } from "../lib/race";
  import { daysUntil } from "../lib/week";
  import Icon from "./Icon.svelte";
  import AvailabilityFields, { availabilityValid } from "./AvailabilityFields.svelte";

  let {
    cycle,
    firstGoal,
    today = todayIso(),
    busy = false,
    onsubmit,
    oncancel,
  }: {
    /** Cycle actif : sans cycle, le formulaire porte aussi les réglages du plan (il crée le cycle). */
    cycle: Cycle | null;
    /** Premier objectif à venir : Principal par défaut, sinon Secondaire. */
    firstGoal: boolean;
    today?: string;
    busy?: boolean;
    onsubmit?: (input: GoalInput) => void;
    oncancel?: () => void;
  } = $props();

  const PRESETS = [
    { km: 10, label: "10 km" },
    { km: 21.1, label: "Semi · 21,1 km" },
    { km: 42.2, label: "Marathon · 42,2 km" },
  ];

  let type = $state<"route" | "trail">("route");
  let distance = $state(21.1);
  let dplus = $state(0);
  let raceDate = $state("");
  let priority = $state<Priority>(untrack(() => (firstGoal ? "principal" : "secondaire")));
  let perWeek = $state(4);
  let days = $state<string[]>([...WEEKDAYS]);
  let longRunDay = $state("");
  let includeBike = $state(false);
  let gpx = $state<File | null>(null);
  let targetMode = $state<"claude" | "user">("claude");
  let targetText = $state("");
  let targetError = $state("");

  const withSettings = $derived(cycle === null);
  const ownTime = $derived(targetMode === "user");
  const daysOk = $derived(!withSettings || availabilityValid(days, perWeek));
  // dans un cycle existant, la course doit seulement être après aujourd'hui
  const minDate = $derived(withSettings ? today : addDays(today, 1));
  const weeksLeft = $derived(raceDate && raceDate > today ? Math.ceil(daysUntil(today, raceDate) / 7) : null);

  function submit(e: Event) {
    e.preventDefault();
    targetError = "";
    if (ownTime && !Number.isFinite(parseTargetTime(targetText))) {
      targetError = "Temps visé invalide : format attendu h:mm, ex. 1:50";
      return;
    }
    const input: GoalInput = {
      type,
      distance_km: distance,
      d_plus_m: type === "trail" ? dplus : 0,
      race_date: raceDate,
      target_time: ownTime ? targetText.trim() : undefined,
      gpx,
      priority,
    };
    if (withSettings) {
      Object.assign(input, {
        sessions_per_week: perWeek,
        available_days: days,
        long_run_day: longRunDay || undefined,
        include_bike: includeBike,
      });
    }
    onsubmit?.(input);
  }

  function pickFile(e: Event) {
    gpx = (e.target as HTMLInputElement).files?.[0] ?? null;
  }
</script>

<form class="card lg stack" style:gap="26px" onsubmit={submit}>
  <h2>{firstGoal ? "Nouvel objectif" : "Ajouter un objectif"}</h2>

  <fieldset>
    <legend>Type de course</legend>
    <div class="choices">
      <label class="choice">
        <input type="radio" name="type" value="route" bind:group={type} />
        <span><strong>Route</strong>10 km, semi, marathon</span>
      </label>
      <label class="choice">
        <input type="radio" name="type" value="trail" bind:group={type} />
        <span><strong>Trail</strong>Avec dénivelé et tracé GPX</span>
      </label>
    </div>
  </fieldset>

  <div class="stack" style:gap="10px">
    {#if type === "route"}
      <div class="chips" role="group" aria-label="Distances courantes">
        {#each PRESETS as p (p.km)}
          <button type="button" aria-pressed={distance === p.km} onclick={() => (distance = p.km)}>{p.label}</button>
        {/each}
      </div>
    {/if}
    <div class="form-grid">
      <label>
        Distance (km)
        <input type="number" step="0.1" min="1" bind:value={distance} required />
      </label>
      {#if type === "trail"}
        <label>
          Dénivelé positif (m)
          <input type="number" min="0" step="10" bind:value={dplus} required />
        </label>
      {/if}
      <label>
        Date de la course
        <input type="date" min={minDate} bind:value={raceDate} required />
        {#if weeksLeft}<span class="hint">Dans {weeksLeft} semaines environ</span>{/if}
      </label>
    </div>
  </div>

  <fieldset>
    <legend>Priorité</legend>
    <div class="segmented">
      {#each Object.entries(PRIORITY_LABELS) as [value, label] (value)}
        <label>
          <input type="radio" name="priority" {value} bind:group={priority} />
          <span>{label}</span>
        </label>
      {/each}
    </div>
  </fieldset>

  {#if withSettings}
    <fieldset>
      <legend>Séances par semaine</legend>
      <div class="segmented">
        {#each [2, 3, 4, 5, 6, 7] as n (n)}
          <label>
            <input type="radio" name="per-week" value={n} bind:group={perWeek} />
            <span>{n}</span>
          </label>
        {/each}
      </div>
    </fieldset>

    <AvailabilityFields bind:days bind:longRunDay bind:includeBike {perWeek} />
  {/if}

  <fieldset>
    <legend>Temps visé</legend>
    <div class="choices">
      <label class="choice">
        <input type="radio" name="target" value="claude" bind:group={targetMode} />
        <span><strong>Laisser Claude estimer</strong></span>
      </label>
      <label class="choice">
        <input type="radio" name="target" value="user" bind:group={targetMode} />
        <span><strong>Je fixe mon temps</strong></span>
      </label>
    </div>
    {#if ownTime}
      <label>
        Temps visé (h:mm)
        <input type="text" inputmode="numeric" placeholder="1:50" bind:value={targetText} />
        {#if targetError}<span class="hint" role="alert">{targetError}</span>{/if}
      </label>
    {/if}
  </fieldset>

  <label class="drop">
    <Icon name="upload" size={22} />
    <span>
      <strong>Tracé GPX {gpx ? `· ${gpx.name}` : ""}</strong>
      Facultatif · clique pour choisir le fichier
    </span>
    <input type="file" accept=".gpx,application/gpx+xml" onchange={pickFile} />
  </label>

  <div class="actions row end">
    {#if oncancel}<button type="button" onclick={() => oncancel?.()} disabled={busy}>Annuler</button>{/if}
    <button class="primary" disabled={busy || !daysOk}>{withSettings ? "Générer le plan avec Claude" : "Ajouter l'objectif"}</button>
  </div>
</form>
