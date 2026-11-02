<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Goal, type Plan } from "../lib/api";
  import { formatDate, todayIso } from "../lib/dates";
  import { goalTimeLabel, parseTargetTime } from "../lib/race";
  import { daysUntil } from "../lib/week";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import Calendar from "../components/Calendar.svelte";
  import SessionCard from "../components/SessionCard.svelte";
  import Icon from "../components/Icon.svelte";

  let { onchanged, today = todayIso() }: { onchanged?: () => void; today?: string } = $props();

  const PRESETS = [
    { km: 10, label: "10 km" },
    { km: 21.1, label: "Semi · 21,1 km" },
    { km: 42.2, label: "Marathon · 42,2 km" },
  ];

  let type = $state<"route" | "trail">("route");
  let distance = $state(21.1);
  let dplus = $state(0);
  let raceDate = $state("");
  let perWeek = $state(4);
  let gpx = $state<File | null>(null);
  let targetMode = $state<"claude" | "user">("claude");
  const ownTime = $derived(targetMode === "user");
  let targetText = $state("");
  let targetError = $state("");

  let goal = $state<Goal | null>(null);
  let active = $state<Goal | null>(null);
  let plan = $state<Plan | null>(null);
  let summary = $state("");
  let busy = $state("");
  let error = $state<unknown>(null);
  let selected = $state<number | null>(null);

  const weeksLeft = $derived(raceDate && raceDate > today ? Math.ceil(daysUntil(today, raceDate) / 7) : null);
  const selection = $derived.by(() => {
    for (const w of plan?.weeks ?? []) {
      const s = w.sessions.find((x) => x.id === selected);
      if (s) return { session: s, week: w };
    }
    return null;
  });

  // reprend un brouillon existant (objectif actif non validé)
  onMount(async () => {
    try {
      const p = await api.plan();
      if (p.goal && !p.goal.plan_accepted && p.weeks.length) {
        goal = p.goal;
        plan = p;
      } else if (p.goal?.plan_accepted) {
        active = p.goal;
      }
    } catch (e) {
      error = e;
    }
  });

  async function generate(g: Goal) {
    busy = "Claude construit ton plan… (cela peut prendre une minute)";
    const r = await api.generate(g.id);
    summary = r.summary;
    plan = await api.plan();
  }

  async function submit(e: Event) {
    e.preventDefault();
    error = null;
    targetError = "";
    if (ownTime && !Number.isFinite(parseTargetTime(targetText))) {
      targetError = "Temps visé invalide : format attendu h:mm, ex. 1:50";
      return;
    }
    busy = "Création de l'objectif…";
    try {
      goal = await api.createGoal({
        type,
        distance_km: distance,
        d_plus_m: type === "trail" ? dplus : 0,
        race_date: raceDate,
        sessions_per_week: perWeek,
        target_time: ownTime ? targetText.trim() : undefined,
        gpx,
      });
      await generate(goal);
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  async function regenerate() {
    if (!goal) return;
    error = null;
    try {
      await generate(goal);
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  async function accept() {
    if (!goal) return;
    error = null;
    busy = "Validation…";
    try {
      await api.accept(goal.id);
      onchanged?.();
      location.hash = "#/today";
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  function pickFile(e: Event) {
    gpx = (e.target as HTMLInputElement).files?.[0] ?? null;
  }

  const goalLabel = (g: Goal) =>
    `${g.distance_km.toLocaleString("fr-FR")} km ${g.type === "trail" ? `trail · ${g.d_plus_m} m D+` : "route"}`;
</script>

<header class="page-head">
  <div>
    <p class="eyebrow">Claude construit ton plan à partir de tes données Garmin</p>
    <h1>{plan && goal ? "Brouillon du plan" : "Objectif"}</h1>
  </div>
</header>

<ErrorBanner {error} />

{#if busy}
  <p class="card busy" role="status">{busy}</p>
{/if}

{#if plan && goal}
  <section class="card stack">
    <p class="meta">{goalLabel(goal)} · course le {formatDate(goal.race_date)} · {plan.weeks.length} semaines</p>
    {#if goalTimeLabel(goal)}<p class="meta">{goalTimeLabel(goal)}</p>{/if}
    {#if summary}<p>{summary}</p>{/if}
    <div class="row">
      <button class="primary" onclick={accept} disabled={!!busy}>Valider le plan</button>
      <button onclick={regenerate} disabled={!!busy}>Régénérer</button>
    </div>
  </section>
  <div class="cols">
    <div class="col-main" style:flex-grow="3">
      <Calendar weeks={plan.weeks} {today} {selected} readonly onselect={(id) => (selected = id)} />
    </div>
    {#if selection}
      <aside class="col-side card" aria-label="Séance sélectionnée">
        <div class="row spread">
          <span class="meta">Semaine {selection.week.week_index}</span>
          <button class="icon" aria-label="Fermer le détail" onclick={() => (selected = null)}><Icon name="close" size={16} /></button>
        </div>
        <SessionCard session={selection.session} weekMonday={selection.week.week_monday} readonly />
      </aside>
    {/if}
  </div>
{:else}
  <div class="cols">
    <form class="col-main card lg stack" style:gap="26px" onsubmit={submit}>
      <h2>Nouvel objectif</h2>

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
            <input type="date" min={today} bind:value={raceDate} required />
            {#if weeksLeft}<span class="hint">Dans {weeksLeft} semaines environ</span>{/if}
          </label>
        </div>
      </div>

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
        <button class="primary" disabled={!!busy}>Générer le plan avec Claude</button>
      </div>
    </form>

    <aside class="col-side">
      {#if active}
        <section class="card stack">
          <h3>Objectif en cours</h3>
          <p>{goalLabel(active)} · course le {formatDate(active.race_date)}</p>
          <p class="meta">Un nouvel objectif remplacera ce plan.</p>
        </section>
      {/if}
      <section class="card stack">
        <h3>Aperçu</h3>
        {#if weeksLeft}
          <p class="stat"><strong>{weeksLeft} semaines</strong><span>de préparation, {perWeek} séances par semaine</span></p>
        {:else}
          <p class="empty">Choisis la date de la course pour voir la durée du plan.</p>
        {/if}
      </section>
      <section class="tip stack" style:gap="8px">
        <strong>Données utilisées par Claude</strong>
        <ul class="plain stack" style:gap="4px">
          <li>Tes activités Garmin des 8 dernières semaines</li>
          <li>Tes zones cardiaques, ton seuil et ta VO2max</li>
          <li>Tes prédictions de temps de course</li>
        </ul>
      </section>
    </aside>
  </div>
{/if}
