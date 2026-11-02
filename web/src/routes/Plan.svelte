<script lang="ts">
  import { api, type Activity, type Plan } from "../lib/api";
  import { formatDate, formatDay, todayIso } from "../lib/dates";
  import { currentWeek, focusSession, openSessions, sessionDate } from "../lib/week";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import Calendar from "../components/Calendar.svelte";
  import SessionCard from "../components/SessionCard.svelte";
  import Icon from "../components/Icon.svelte";
  import EventDialog from "../components/EventDialog.svelte";
  import InjuryBanner from "../components/InjuryBanner.svelte";
  import EventList from "../components/EventList.svelte";

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
</script>

<header class="page-head">
  <div>
    {#if plan?.goal}
      <p class="eyebrow">
        {plan.goal.distance_km.toLocaleString("fr-FR")} km {plan.goal.type === "trail" ? `trail · ${plan.goal.d_plus_m} m D+` : "route"}
        · course le {formatDate(plan.goal.race_date)}
      </p>
    {/if}
    <h1>Programme</h1>
  </div>
  {#if plan?.goal?.plan_accepted}
    <button onclick={() => (declaring = true)}>Signaler un imprévu</button>
  {/if}
</header>

<ErrorBanner {error} onpin={load} />

{#if declaring && plan?.goal}
  <EventDialog
    goal={plan.goal}
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
  {#if !plan.goal}
    <p class="card">Aucun objectif. <a href="#/goal">Créer un objectif</a></p>
  {:else if !plan.goal.plan_accepted}
    <p class="card">Le plan n'est pas encore validé. <a href="#/goal">Relire le brouillon</a></p>
  {:else}
    <InjuryBanner injury={plan.open_injury ?? null} goalId={plan.goal.id} {today} onproposal={goProposal} onresumed={load} />
    <EventList goalId={plan.goal.id} {today} reload={reloads} onproposal={goProposal} onchanged={load} />
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
        <Calendar weeks={plan.weeks} {today} {selected} onselect={(id) => (selected = id)} />
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
            onchanged={load}
            onerror={fail}
          />
        </aside>
      {/if}
    </div>
  {/if}
{:else if !error}
  <p class="busy">Chargement…</p>
{/if}
