<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Cycle, type Goal, type GoalInput, type Plan, type PlanChange } from "../lib/api";
  import { WEEKDAYS, formatDate, todayIso } from "../lib/dates";
  import { goalLabel } from "../lib/goals";
  import { goalTimeLabel } from "../lib/race";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import Calendar from "../components/Calendar.svelte";
  import SessionCard from "../components/SessionCard.svelte";
  import Icon from "../components/Icon.svelte";
  import GoalForm from "../components/GoalForm.svelte";
  import GoalEditDialog from "../components/GoalEditDialog.svelte";
  import PlanSettingsDialog from "../components/PlanSettingsDialog.svelte";
  import PriorityBadge from "../components/PriorityBadge.svelte";
  import AvailabilityFields, { availabilityValid } from "../components/AvailabilityFields.svelte";

  let { onchanged, today = todayIso() }: { onchanged?: () => void; today?: string } = $props();

  let goals = $state<Goal[]>([]); // objectifs renvoyés par /status (à venir)
  let pastGoals = $state<Goal[]>([]); // objectifs courus, du plus récent au plus ancien
  let cycle = $state<Cycle | null>(null);
  let lastCycle = $state<Cycle | null>(null); // dernier cycle terminé : réglages du cycle suivant
  // réglages du cycle suivant (pré-remplis à la lecture du dernier cycle)
  let nextDays = $state<string[]>([...WEEKDAYS]);
  let nextLongRun = $state("");
  let nextBike = $state(false);
  let nextPerWeek = $state(3);
  let plan = $state<Plan | null>(null);
  let loaded = $state(false);
  let adding = $state(false);
  let stale = $state(false); // dernier changement : plan à régénérer (avant relecture du cycle)
  let summary = $state("");
  let busy = $state("");
  let error = $state<unknown>(null);
  let selected = $state<number | null>(null);
  let editing = $state<Goal | null>(null);
  let editingSettings = $state(false);

  const byDate = (a: Goal, b: Goal) => a.race_date.localeCompare(b.race_date) || a.id - b.id;
  const upcoming = $derived(goals.filter((g) => g.status !== "done").sort(byDate));
  // cycle terminé et objectifs encore à venir : le cycle suivant est à préparer
  const toPrepare = $derived(loaded && cycle === null && upcoming.length > 0);
  const needsGeneration = $derived(!!cycle && (cycle.needs_generation || stale));
  const draft = $derived(!!cycle && !cycle.plan_accepted && !needsGeneration && !!plan?.weeks.length);
  // plan à recalculer : le plan précédent reste affiché (lecture seule) jusqu'à « Générer »
  const previous = $derived(needsGeneration && !!plan?.weeks.some((w) => w.sessions.length > 0));
  // premier objectif : le formulaire s'affiche d'emblée
  const showForm = $derived(loaded && (adding || upcoming.length === 0));
  const selection = $derived.by(() => {
    for (const w of plan?.weeks ?? []) {
      const s = w.sessions.find((x) => x.id === selected);
      if (s) return { session: s, week: w };
    }
    return null;
  });

  async function load() {
    const [p, s] = await Promise.all([api.plan(), api.status()]);
    plan = p;
    cycle = s.cycle ?? p.cycle;
    goals = s.goals ?? [];
    pastGoals = s.past_goals ?? [];
    if (!cycle && s.last_cycle && s.last_cycle.id !== lastCycle?.id) {
      lastCycle = s.last_cycle;
      nextDays = [...s.last_cycle.available_days];
      nextLongRun = s.last_cycle.long_run_day ?? "";
      nextBike = s.last_cycle.include_bike;
      nextPerWeek = s.last_cycle.sessions_per_week;
    }
    stale = false;
    loaded = true;
  }

  onMount(async () => {
    try {
      await load();
    } catch (e) {
      error = e;
    }
  });

  async function generate() {
    busy = "Claude construit ton plan… (cela peut prendre une minute)";
    const r = await api.generate();
    summary = r.summary;
    await load();
  }

  /** Suite d'un ajout, d'une modification ou d'un retrait : proposition à relire, ou plan à régénérer. */
  async function changed(r: PlanChange) {
    onchanged?.();
    if (r.proposal_id != null) {
      location.hash = "#/proposal";
      return;
    }
    await load();
    if (r.needs_generation) stale = true;
  }

  async function add(input: GoalInput) {
    error = null;
    const first = cycle === null; // le premier objectif crée le cycle : on génère le plan aussitôt
    busy = first ? "Création de l'objectif…" : "Ajout de l'objectif… (Claude peut ajuster ton plan)";
    let created = false;
    try {
      const r = await api.createGoal(input);
      created = true;
      adding = false;
      if (first) {
        onchanged?.();
        await generate();
      } else {
        await changed(r);
      }
    } catch (err) {
      error = err;
      // l'objectif est enregistré même si la génération échoue : le bandeau « Générer » prendra le relais
      if (created) await load().catch(() => {});
    } finally {
      busy = "";
    }
  }

  /** Crée le cycle suivant avec les réglages choisis, puis génère son plan. */
  async function prepareNext() {
    error = null;
    busy = "Préparation du cycle suivant…";
    let created = false;
    try {
      await api.nextCycle({
        sessions_per_week: nextPerWeek,
        available_days: nextDays,
        long_run_day: nextLongRun,
        include_bike: nextBike,
      });
      created = true;
      onchanged?.();
      await generate();
    } catch (err) {
      error = err;
      // cycle créé mais génération en échec : le bandeau « Générer » prendra le relais
      if (created) await load().catch(() => {});
    } finally {
      busy = "";
    }
  }

  async function regenerate() {
    error = null;
    try {
      await generate();
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  async function accept() {
    error = null;
    busy = "Validation…";
    try {
      await api.accept();
      onchanged?.();
      location.hash = "#/today";
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  async function remove(g: Goal) {
    if (!confirm(`Retirer ${goalLabel(g)} du ${formatDate(g.race_date)} ?`)) return;
    error = null;
    busy = "Retrait de l'objectif… (Claude peut ajuster ton plan)";
    try {
      await changed(await api.removeGoal(g.id));
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  async function edited(r: PlanChange) {
    editing = null;
    try {
      await changed(r);
    } catch (err) {
      error = err;
    }
  }

  function settingsSaved() {
    editingSettings = false;
    onchanged?.();
    location.hash = "#/proposal";
  }

  /** « 800 m D+ · 18 avril 2027 » (D+ seulement pour un trail). */
  const details = (g: Goal) =>
    [g.type === "trail" ? `${g.d_plus_m} m D+` : "", formatDate(g.race_date)].filter(Boolean).join(" · ");
</script>

<header class="page-head">
  <div>
    <p class="eyebrow">Claude construit ton plan à partir de tes données Garmin</p>
    <h1>Objectifs</h1>
  </div>
</header>

<ErrorBanner {error} />

{#if busy}
  <p class="card busy" role="status">{busy}</p>
{/if}

{#if needsGeneration}
  <section class="card row spread" aria-label="Plan à recalculer">
    <p>
      Le plan doit être recalculé pour tenir compte de tes objectifs.{#if previous} En attendant, voici le plan
        précédent.{/if}
    </p>
    <button class="primary" onclick={regenerate} disabled={!!busy}>Générer</button>
  </section>
{:else if draft && plan}
  <section class="card stack" aria-labelledby="draft-title">
    <h2 id="draft-title">Brouillon du plan</h2>
    <p class="meta">{plan.weeks.length} semaines</p>
    {#if summary}<p>{summary}</p>{/if}
    <div class="row">
      <button class="primary" onclick={accept} disabled={!!busy}>Valider le plan</button>
      <button onclick={regenerate} disabled={!!busy}>Régénérer</button>
    </div>
  </section>
{/if}
{#if (draft || previous) && plan}
  <div class="cols">
    <div class="col-main" style:flex-grow="3">
      <!-- brouillon : sans statut ; plan précédent : statuts gardés (faites, exportées) -->
      <Calendar weeks={plan.weeks} {today} {selected} races={plan.goals} readonly={draft} onselect={(id) => (selected = id)} />
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
{/if}

{#if toPrepare}
  <section class="card stack" aria-labelledby="next-title">
    <h2 id="next-title">Préparer le cycle suivant</h2>
    <p>
      Ton cycle est terminé. Claude prépare le suivant jusqu'à ta prochaine course, en commençant par une
      récupération adaptée{#if pastGoals.length} à {goalLabel(pastGoals[0])}{/if}.
    </p>
    <fieldset>
      <legend>Séances par semaine</legend>
      <div class="segmented">
        {#each [2, 3, 4, 5, 6, 7] as n (n)}
          <label>
            <input type="radio" name="next-per-week" value={n} bind:group={nextPerWeek} />
            <span>{n}</span>
          </label>
        {/each}
      </div>
    </fieldset>
    <AvailabilityFields bind:days={nextDays} bind:longRunDay={nextLongRun} bind:includeBike={nextBike} perWeek={nextPerWeek} />
    <div class="row">
      <button class="primary" onclick={prepareNext} disabled={!!busy || !availabilityValid(nextDays, nextPerWeek)}>
        Préparer et générer
      </button>
    </div>
  </section>
{/if}

<div class="cols">
  <div class="col-main stack">
    {#if upcoming.length}
      <section class="card stack" aria-labelledby="goals-title">
        <div class="row spread">
          <h2 id="goals-title">À venir</h2>
          <div class="row">
            {#if cycle}<button type="button" onclick={() => (editingSettings = true)}>Réglages du plan</button>{/if}
            {#if !adding && !toPrepare}
              <button type="button" class="primary" onclick={() => (adding = true)}>Ajouter un objectif</button>
            {/if}
          </div>
        </div>
        <ul class="plain goals" aria-label="Objectifs à venir">
          {#each upcoming as g (g.id)}
            <li class="goal">
              <div class="stack" style:gap="4px">
                <div class="row">
                  <PriorityBadge priority={g.priority} />
                  <strong>{goalLabel(g)}</strong>
                </div>
                <span class="meta">{details(g)}</span>
                {#if goalTimeLabel(g)}<span class="meta">{goalTimeLabel(g)}</span>{/if}
              </div>
              <div class="row">
                <button type="button" onclick={() => (editing = g)} disabled={!!busy}>Modifier</button>
                <a class="button" href="#/race/{g.id}">Jour J</a>
                <button type="button" onclick={() => remove(g)} disabled={!!busy}>Retirer</button>
              </div>
            </li>
          {/each}
        </ul>
      </section>
    {:else if cycle}
      <div class="row end">
        <button type="button" onclick={() => (editingSettings = true)}>Réglages du plan</button>
      </div>
    {/if}

    {#if showForm}
      <GoalForm
        {cycle}
        firstGoal={upcoming.length === 0}
        {today}
        busy={!!busy}
        onsubmit={add}
        oncancel={upcoming.length ? () => (adding = false) : undefined}
      />
    {/if}

    {#if pastGoals.length}
      <details class="card">
        <summary>Objectifs courus</summary>
        <ul class="plain stack" style:gap="6px">
          {#each pastGoals as g (g.id)}
            <li class="row">
              <PriorityBadge priority={g.priority} />
              <span>{goalLabel(g)} · {details(g)}</span>
            </li>
          {/each}
        </ul>
      </details>
    {/if}
  </div>

  {#if showForm}
    <aside class="col-side">
      <section class="tip stack" style:gap="8px">
        <strong>Données utilisées par Claude</strong>
        <ul class="plain stack" style:gap="4px">
          <li>Tes activités Garmin des 8 dernières semaines</li>
          <li>Tes zones cardiaques, ton seuil et ta VO2max</li>
          <li>Tes prédictions de temps de course</li>
        </ul>
      </section>
    </aside>
  {/if}
</div>

{#if editing}
  <GoalEditDialog goal={editing} {today} onclose={() => (editing = null)} onsaved={edited} />
{/if}

{#if editingSettings && cycle}
  <PlanSettingsDialog {cycle} onclose={() => (editingSettings = false)} onsaved={settingsSaved} />
{/if}

<style>
  .goals { display: flex; flex-direction: column; }
  .goal {
    display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px;
    padding: 12px 0; border-top: 1px solid var(--divider);
  }
  .goal:first-child { border-top: none; }
  summary { cursor: pointer; font-weight: 600; }
</style>
