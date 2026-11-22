<script lang="ts">
  import { api, type Activity, type Plan, type Session, type Status, type Week } from "../lib/api";
  import { formatActivity } from "../lib/activity";
  import { goalLabel, nextRace } from "../lib/goals";
  import { addDays, formatDate, formatDay, todayIso } from "../lib/dates";
  import { STATUS_LABEL, TYPE_SHORT, typeFamily } from "../lib/labels";
  import { formatDuration, totalSeconds } from "../lib/profile";
  import { currentWeek, days, daysUntil, focusSession, openSessions, sessionDate } from "../lib/week";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import SessionCard from "../components/SessionCard.svelte";
  import Icon from "../components/Icon.svelte";
  import EventDialog from "../components/EventDialog.svelte";
  import EventList from "../components/EventList.svelte";
  import InjuryBanner from "../components/InjuryBanner.svelte";
  import PriorityBadge from "../components/PriorityBadge.svelte";
  import RaceDayCard from "../components/RaceDayCard.svelte";
  import { READONLY } from "../lib/mode";
  import AdjustBanner from "../components/AdjustBanner.svelte";

  let {
    version = 0,
    status = null,
    today = todayIso(),
    onerror: report,
  }: { version?: number; status?: Status | null; today?: string; onerror?: (e: unknown) => void } = $props();

  let plan = $state<Plan | null>(null);
  let activities = $state<Activity[]>([]);
  let error = $state<unknown>(null);
  let reloads = $state(0); // incrémenté à chaque rechargement du plan, pour rafraîchir la liste des imprévus
  let viewed = $state<number | null>(null); // semaine affichée (null : celle d'aujourd'hui)
  let picked = $state<number | null>(null); // séance choisie dans la semaine affichée
  let declaring = $state(false);
  let generating = $state(false);

  const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  const SHORT_DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
  const day = (iso: string) => Number(iso.slice(8, 10));
  const month = (iso: string) => MONTHS[Number(iso.slice(5, 7)) - 1];
  const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

  const weeks = $derived(plan?.weeks ?? []);
  const current = $derived(plan ? currentWeek(plan.weeks, today) : null);
  const week = $derived(weeks.find((w) => w.week_index === viewed) ?? current);
  const isCurrent = $derived(!!week && week.week_index === current?.week_index);
  const position = $derived(week ? weeks.indexOf(week) : -1);
  const strip = $derived(week ? days(week) : []);

  const focus = $derived.by(() => {
    if (!week) return null;
    const all = week.sessions;
    const chosen = all.find((s) => s.id === picked);
    if (chosen) return chosen;
    if (isCurrent) return focusSession(week, today);
    // autre semaine : sa première séance pas encore faite, sinon sa première séance
    const dated = [...all].sort((a, b) =>
      sessionDate(a, week.week_monday).localeCompare(sessionDate(b, week.week_monday)) || a.order - b.order);
    return dated.find((s) => s.status !== "done") ?? dated[0] ?? null;
  });
  const focusDate = $derived(focus && week ? sessionDate(focus, week.week_monday) : null);

  // compte à rebours : la prochaine course du cycle (voir nextRace)
  const goal = $derived(plan ? nextRace(plan, today) : null);
  const allSessions = $derived(weeks.flatMap((w) => w.sessions));
  // plan à recalculer après un changement d'objectif : le plan précédent reste affiché, en lecture seule
  const stale = $derived(
    !!plan?.cycle && !plan.cycle.plan_accepted && plan.cycle.needs_generation && allSessions.length > 0,
  );

  const done = $derived(week?.sessions.filter((s) => s.status === "done").length ?? 0);
  const volume = $derived.by(() => {
    const secs = week?.sessions.map((s) => totalSeconds(s.steps)) ?? [];
    return secs.length && secs.every((s) => s != null) ? formatDuration(secs.reduce<number>((a, b) => a + (b ?? 0), 0)) : null;
  });
  const lastActivity = $derived(
    isCurrent ? ([...activities].sort((a, b) => b.date.localeCompare(a.date))[0] ?? null) : null,
  );

  const heading = $derived.by(() => {
    if (!week || !current) return "";
    const delta = week.week_index - current.week_index;
    if (delta === 0) return "Cette semaine";
    if (delta === 1) return "Semaine prochaine";
    if (delta === -1) return "Semaine dernière";
    return `Semaine ${week.week_index}`;
  });
  const range = $derived.by(() => {
    if (!week) return "";
    const end = addDays(week.week_monday, 6);
    const sameMonth = week.week_monday.slice(5, 7) === end.slice(5, 7);
    return `${day(week.week_monday)}${sameMonth ? "" : ` ${month(week.week_monday)}`} – ${day(end)} ${month(end)}`;
  });

  const racesIn = (w: Week) => (plan?.goals ?? []).filter((g) => g.race_date >= w.week_monday && g.race_date <= addDays(w.week_monday, 6));

  async function load() {
    try {
      plan = await api.plan();
      reloads++;
    } catch (e) {
      fail(e);
    }
  }

  $effect(() => {
    version; // recharge après chaque synchro
    load();
  });

  // activités de la semaine affichée (rattachement, « Corriger », dernière sortie)
  $effect(() => {
    const idx = week?.week_index;
    if (idx == null) return;
    api
      .activities(idx)
      .then((a) => (activities = a))
      .catch(() => (activities = []));
  });

  function show(w: Week | undefined) {
    if (!w) return;
    viewed = w.week_index;
    picked = null;
  }

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

  const duration = (s: Session) => {
    const t = totalSeconds(s.steps);
    return t ? formatDuration(t) : "";
  };
</script>

<header class="page-head">
  <div>
    <p class="eyebrow">
      {capitalize(formatDay(today))}{#if current && plan}{" · "}Semaine {current.week_index} sur {plan.weeks.length}{/if}
    </p>
    <h1>Ma semaine</h1>
  </div>
  <div class="row">
    {#if !READONLY && plan?.cycle?.plan_accepted}
      <button class="ghost" onclick={() => (declaring = true)}>Signaler un imprévu</button>
    {/if}
    {#if goal}
      <div class="goal-pill">
        <span class="goal-what"><span class="meta">Objectif</span><strong>{goalLabel(goal)}{goal.type === "trail" ? ` · ${goal.d_plus_m} m D+` : ""}</strong></span>
        <span class="countdown">J-{daysUntil(today, goal.race_date)}</span>
      </div>
    {/if}
  </div>
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
      goProposal();
    }}
  />
{/if}

{#if plan}
  {#if !plan.cycle}
    <p class="card">
      Aucun objectif pour l'instant.
      {#if READONLY}À faire depuis l'ordinateur.{:else}<a href="#/goal">Créer un objectif</a>{/if}
    </p>
  {:else if !plan.cycle.plan_accepted && !stale}
    <p class="card">
      Ton plan n'est pas encore validé.
      {#if READONLY}À faire depuis l'ordinateur.{:else}<a href="#/goal">Relire le brouillon</a>{/if}
    </p>
  {:else}
    {#if stale}
      <section class="card row spread" aria-label="Plan à recalculer">
        <p>Le plan doit être recalculé pour tenir compte de tes objectifs. En attendant, voici le plan précédent.</p>
        {#if READONLY}
          <span class="meta">À faire depuis l'ordinateur</span>
        {:else}
          <button class="primary" onclick={generate} disabled={generating}>Générer</button>
        {/if}
      </section>
      {#if generating}<p class="card busy" role="status">Claude construit ton plan… (cela peut prendre une minute)</p>{/if}
    {/if}

    <AdjustBanner cycle={plan.cycle} onproposal={goProposal} />

    {#if status?.pending_proposal_id != null}
      {#if READONLY}
        <p class="proposal-banner">Une proposition d'ajustement t'attend sur l'ordinateur</p>
      {:else}
        <a class="proposal-banner" href="#/proposal">
          <span class="bubble"><Icon name="chat" size={18} /></span>
          <span class="what"><strong>Claude propose des changements à ton plan</strong><span>À valider ou refuser</span></span>
          <span class="go">Examiner <Icon name="arrow" size={16} /></span>
        </a>
      {/if}
    {/if}

    <InjuryBanner injury={plan.open_injury ?? null} {today} onproposal={goProposal} onresumed={load} />

    <div class="focus-row">
      <section class="focus" aria-label="Séance sélectionnée">
        {#if focus && week}
          <p class="when">
            {focusDate === today ? "Aujourd'hui · " : ""}{capitalize(formatDay(focusDate ?? week.week_monday))} · S{week.week_index}
          </p>
          <SessionCard
            session={focus}
            weekMonday={week.week_monday}
            large
            readonly={stale}
            {activities}
            onchanged={load}
            onerror={fail}
          />
        {:else}
          <p class="when">{isCurrent ? "Aujourd'hui" : `Semaine ${week?.week_index ?? ""}`}</p>
          <div class="stack rest">
            <h2>{isCurrent ? "Repos aujourd'hui" : "Aucune séance"}</h2>
            <p>{isCurrent ? "Plus aucune séance prévue cette semaine. Le repos fait partie du plan." : "Pas de séance prévue cette semaine-là."}</p>
            {#if weeks[position + 1]}
              <button class="primary" onclick={() => show(weeks[position + 1])}>Voir la semaine suivante</button>
            {/if}
          </div>
        {/if}
      </section>

      <div class="side">
        {#if week}
          <section class="card stack" aria-label="Bilan de la semaine">
            <span class="meta">Semaine {week.week_index} sur {weeks.length}</span>
            <p class="tally"><strong>{done}</strong><span class="of">/{week.sessions.length}</span> <span>séances faites</span></p>
            {#if week.sessions.length}
              <div class="dots" aria-hidden="true">
                {#each week.sessions as s (s.id)}<span class={s.status}></span>{/each}
              </div>
            {/if}
            {#if volume}<p class="meta">{volume} d'entraînement prévues</p>{/if}
          </section>
        {/if}
        {#if isCurrent}
          <section class="card stack" aria-label="Dernière activité">
            <span class="meta">Dernière activité</span>
            {#if lastActivity}
              <p>{formatActivity(lastActivity)}{#if lastActivity.avg_hr} · FC moy. {lastActivity.avg_hr}{/if}</p>
              <p class="meta">{lastActivity.session_id != null ? "Rattachée à une séance du plan" : "Pas rattachée à une séance"}</p>
            {:else}
              <p class="empty">Aucune activité cette semaine.</p>
            {/if}
          </section>
        {/if}
      </div>
    </div>

    {#if week}
      <section class="stack" aria-labelledby="week-heading">
        <div class="week-nav">
          <div class="row">
            <button class="square" aria-label="Semaine précédente" disabled={position <= 0} onclick={() => show(weeks[position - 1])}>
              <Icon name="prev" />
            </button>
            <div class="week-title">
              <h2 id="week-heading">{heading}</h2>
              <span class="meta">{range}{heading !== `Semaine ${week.week_index}` ? ` · S${week.week_index}` : ""}</span>
            </div>
            <button class="square" aria-label="Semaine suivante" disabled={position >= weeks.length - 1} onclick={() => show(weeks[position + 1])}>
              <Icon name="next" />
            </button>
            {#if !isCurrent && current}
              <button class="soft" onclick={() => show(current)}>Revenir à cette semaine</button>
            {/if}
          </div>
          <div class="timeline" role="group" aria-label="Aller à une semaine du plan">
            {#each weeks as w (w.week_index)}
              {@const race = racesIn(w).length > 0}
              <button
                class:past={current && w.week_index < current.week_index}
                class:now={w.week_index === current?.week_index}
                class:race
                aria-label="Semaine {w.week_index}{race ? ' (course)' : ''}"
                aria-current={w.week_index === week.week_index ? "true" : undefined}
                onclick={() => show(w)}
              >
                <span class="seg"></span>
                <span class="n">{race ? "J" : w.week_index}</span>
              </button>
            {/each}
          </div>
        </div>

        <div class="week-days">
          {#each strip as d (d.date)}
            {@const races = (plan.goals ?? []).filter((g) => g.race_date === d.date)}
            <div class="wday" class:today={d.date === today} class:off={!d.sessions.length && !races.length}>
              <span class="d">
                {SHORT_DAYS[(new Date(`${d.date}T00:00:00Z`).getUTCDay() + 6) % 7]} {day(d.date)}
                {#if d.date === today}<span class="today-tag">Auj.</span>{/if}
              </span>
              {#each races as g (g.id)}<RaceDayCard goal={g} />{/each}
              {#each d.sessions as s (s.id)}
                <button class="wsession" class:past={s.status === "done"} aria-pressed={focus?.id === s.id} onclick={() => (picked = s.id)}>
                  <span class="chip {typeFamily(s.type)}">{TYPE_SHORT[s.type] ?? s.type}</span>
                  <span class="t">{s.title}</span>
                  <span class="foot">
                    <span>{duration(s)}</span>
                    {#if !stale}<span class="st {s.status}">{STATUS_LABEL[s.status]}</span>{/if}
                  </span>
                </button>
              {:else}
                {#if !races.length}<span class="rest-label">Repos</span>{/if}
              {/each}
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <EventList {today} reload={reloads} onproposal={goProposal} onchanged={load} />

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
