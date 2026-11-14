<script lang="ts">
  import { api, cycleGoal, type Activity, type Plan } from "../lib/api";
  import { formatDate, formatDay, todayIso } from "../lib/dates";
  import { currentWeek, focusSession, openSessions, sessionDate } from "../lib/week";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import Calendar from "../components/Calendar.svelte";
  import SessionCard from "../components/SessionCard.svelte";
  import Icon from "../components/Icon.svelte";
  import EventDialog from "../components/EventDialog.svelte";
  import InjuryBanner from "../components/InjuryBanner.svelte";
  import { READONLY } from "../lib/mode";
  import EventList from "../components/EventList.svelte";
  import PriorityBadge from "../components/PriorityBadge.svelte";
  import { goalLabel } from "../lib/goals";

  let {
    version = 0,
    today = todayIso(),
    onerror: report,
  }: { version?: number; today?: string; onerror?: (e: unknown) => void } = $props();

  let plan = $state<Plan | null>(null);
  let error = $state<unknown>(null);
  let selected = $state<number | null>(null);
  let activities = $state<Activity[]>([]);
  let reloads = $state(0); // incrémenté à chaque rechargement du plan, pour rafraîchir la liste des imprévus

  const now = $derived(plan ? currentWeek(plan.weeks, today) : null);
  // plan à recalculer après un changement d'objectif : le plan précédent reste affiché, en lecture seule
  const stale = $derived(
    !!plan?.cycle && !plan.cycle.plan_accepted && plan.cycle.needs_generation && plan.weeks.some((w) => w.sessions.length > 0),
  );
  let generating = $state(false);
  // le titre décrit la cible du cycle : la course qui le termine
  const goal = $derived(plan ? cycleGoal(plan) : null);
  const selection = $derived.by(() => {
    for (const w of plan?.weeks ?? []) {
      const s = w.sessions.find((x) => x.id === selected);
      if (s) return { session: s, week: w };
    }
    return null;
  });

  async function load() {
    try {
      plan = await api.plan();
      reloads++;
      if (selected == null) selected = focusSession(currentWeek(plan.weeks, today), today)?.id ?? null;
    } catch (e) {
      error = e;
      report?.(e);
    }
  }

  $effect(() => {
    version; // recharge après chaque synchro
    load();
  });

  // activités de la semaine de la séance ouverte (pour « Corriger »)
  $effect(() => {
    const idx = selection?.week.week_index;
    if (idx == null) return;
    api
      .activities(idx)
      .then((a) => (activities = a))
      .catch(() => (activities = []));
  });

  let declaring = $state(false);

  function goProposal() {
    location.hash = "#/proposal";
  }

  function fail(e: unknown) {
    error = e;
    report?.(e);
  }

  async function generate() {
    error = null;
    generating = true;
    try {
      await api.generate();
      await load();
    } catch (e) {
      fail(e);
    } finally {
      generating = false;
    }
  }
</script>

<header class="page-head">
  <div>
    {#if goal}
      <p class="eyebrow">
        {goal.distance_km.toLocaleString("fr-FR")} km {goal.type === "trail" ? `trail · ${goal.d_plus_m} m D+` : "route"}
        · course le {formatDate(goal.race_date)}
      </p>
    {/if}
    <h1>Programme</h1>
  </div>
  {#if !READONLY && plan?.cycle?.plan_accepted}
    <button onclick={() => (declaring = true)}>Signaler un imprévu</button>
  {/if}
</header>

<ErrorBanner {error} onpin={load} />

{#if !READONLY && declaring && plan?.cycle}
  <EventDialog
    cycle={plan.cycle}
    weeks={plan.weeks}
    sessions={openSessions(plan.weeks, today)}
    {today}
    onclose={() => (declaring = false)}
    onproposal={() => {
      declaring = false;
      location.hash = "#/proposal";
    }}
  />
{/if}

{#if plan}
  {#if !plan.cycle}
    <p class="card">Aucun objectif. <a href="#/goal">Créer un objectif</a></p>
  {:else if !plan.cycle.plan_accepted && !stale}
    <p class="card">Le plan n'est pas encore validé. <a href="#/goal">Relire le brouillon</a></p>
  {:else}
    {#if stale}
      <section class="card row spread" aria-label="Plan à recalculer">
        <p>Le plan doit être recalculé pour tenir compte de tes objectifs. En attendant, voici le plan précédent.</p>
        {#if !READONLY}<button class="primary" onclick={generate} disabled={generating}>Générer</button>{/if}
      </section>
      {#if generating}<p class="card busy" role="status">Claude construit ton plan… (cela peut prendre une minute)</p>{/if}
    {/if}
    <InjuryBanner injury={plan.open_injury ?? null} {today} onproposal={goProposal} onresumed={load} />
    <EventList {today} reload={reloads} onproposal={goProposal} onchanged={load} />
    <section aria-label="Avancement du plan">
      <div class="weeks-bar" style:grid-template-columns="repeat({plan.weeks.length}, minmax(0, 1fr))">
        {#each plan.weeks as w (w.week_index)}
          <div class:past={now && w.week_index < now.week_index} class:now={now?.week_index === w.week_index}></div>
        {/each}
      </div>
    </section>
    <div class="weeks-bar-legend">
      <span>S1</span>
      {#if now}<span>Semaine {now.week_index} en cours</span>{/if}
      <span>S{plan.weeks.length} · course</span>
    </div>

    <div class="cols">
      <div class="col-main" style:flex-grow="3">
        <Calendar weeks={plan.weeks} {today} {selected} races={plan.goals} onselect={(id) => (selected = id)} />
      </div>

      {#if selection}
        <aside class="col-side card" aria-label="Séance sélectionnée">
          <div class="row spread">
            <span class="meta">{formatDay(sessionDate(selection.session, selection.week.week_monday))} · S{selection.week.week_index}</span>
            <button class="icon" aria-label="Fermer le détail" onclick={() => (selected = null)}><Icon name="close" size={16} /></button>
          </div>
          <SessionCard
            session={selection.session}
            weekMonday={selection.week.week_monday}
            {activities}
            readonly={stale}
            onchanged={load}
            onerror={fail}
          />
        </aside>
      {/if}
    </div>

    {#if plan.horizon.length}
      <section class="card stack" aria-labelledby="plan-next">
        <h2 id="plan-next">Ensuite</h2>
        <p class="meta">Ces courses seront préparées par le cycle suivant.</p>
        <ul class="plain stack" style:gap="8px">
          {#each plan.horizon as g (g.id)}
            <li class="row">
              <PriorityBadge priority={g.priority} />
              <span>{goalLabel(g)}{g.type === "trail" ? ` · ${g.d_plus_m} m D+` : ""} · {formatDate(g.race_date)}</span>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {/if}
{:else if !error}
  <p class="busy">Chargement…</p>
{/if}
