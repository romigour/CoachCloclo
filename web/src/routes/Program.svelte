<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Activity, type Plan } from "../lib/api";
  import { formatDate, formatDay, todayIso } from "../lib/dates";
  import { goalLabel, nextRace } from "../lib/goals";
  import { currentWeek, daysUntil, sessionDate } from "../lib/week";
  import Calendar from "../components/Calendar.svelte";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import Icon from "../components/Icon.svelte";
  import SessionCard from "../components/SessionCard.svelte";
  import { READONLY } from "../lib/mode";

  let { version = 0, today = todayIso() }: { version?: number; today?: string } = $props();

  let plan = $state<Plan | null>(null);
  let activities = $state<Activity[]>([]);
  let error = $state<unknown>(null);
  let selected = $state<number | null>(null);
  let closeButton = $state<HTMLButtonElement | null>(null);
  let opener: HTMLElement | null = null; // séance cliquée : reprend le focus à la fermeture

  const weeks = $derived(plan?.weeks ?? []);
  const current = $derived(plan ? currentWeek(weeks, today) : null);
  const sessions = $derived(weeks.flatMap((w) => w.sessions));
  const done = $derived(sessions.filter((s) => s.status === "done").length);
  const goal = $derived(plan ? nextRace(plan, today) : null);
  // comme « Ma semaine » : plan validé, ou plan précédent en attendant un nouveau calcul
  const visible = $derived(
    !!plan?.cycle && sessions.length > 0 && (plan.cycle.plan_accepted || plan.cycle.needs_generation),
  );
  const selection = $derived.by(() => {
    for (const week of weeks) {
      const session = week.sessions.find((s) => s.id === selected);
      if (session) return { week, session };
    }
    return null;
  });

  async function load() {
    try {
      plan = await api.plan();
      error = null;
    } catch (e) {
      error = e;
    }
  }

  $effect(() => {
    version; // recharge après chaque synchro
    load();
  });

  // activités de la semaine de la séance ouverte (activité rattachée)
  $effect(() => {
    const idx = selection?.week.week_index;
    if (idx == null) return;
    let stale = false;
    activities = [];
    api
      .activities(idx)
      .then((a) => {
        if (!stale) activities = a;
      })
      .catch(() => {}); // le détail reste lisible sans l'activité
    return () => {
      stale = true;
    };
  });

  $effect(() => {
    closeButton?.focus();
  });

  // le calendrier défile jusqu'à la semaine en cours : la page suivante repart du haut
  onMount(() => () => {
    document.documentElement.scrollTop = 0;
  });

  function open(id: number) {
    opener = document.activeElement as HTMLElement | null;
    selected = id;
  }

  function close() {
    selected = null;
    opener?.focus();
  }

  function onkeydown(e: KeyboardEvent) {
    if (!selection) return;
    if (e.key === "Escape") close();
    // seul élément actif de la fenêtre : le focus y reste
    else if (e.key === "Tab") {
      e.preventDefault();
      closeButton?.focus();
    }
  }
</script>

<svelte:window {onkeydown} />

<header class="page-head program-head">
  <div class="row">
    <a class="back" href="#/week"><Icon name="prev" size={16} /> Retour</a>
    <div>
      <h1>Programme complet</h1>
      {#if visible && plan?.cycle}
        <p class="meta">
          {formatDate(plan.cycle.plan_start)} – {formatDate(plan.cycle.end_date)}
          {#if current}{" · "}Semaine {current.week_index} sur {weeks.length}{/if}
          {" · "}{done} / {sessions.length} séances faites
        </p>
      {/if}
    </div>
  </div>
  {#if goal}
    <div class="goal-pill">
      <span class="goal-what"><span class="meta">Objectif</span><strong>{goalLabel(goal)}</strong></span>
      <span class="countdown">J-{daysUntil(today, goal.race_date)}</span>
    </div>
  {/if}
</header>

<ErrorBanner {error} onpin={load} />

{#if plan && visible}
  <Calendar {weeks} {today} {selected} races={plan.goals} detailed onselect={open} />
{:else if plan}
  <p class="card">
    Aucun programme à afficher pour l'instant.
    {#if READONLY}À faire depuis l'ordinateur.{:else}<a href="#/goal">Voir les objectifs</a>{/if}
  </p>
{:else if !error}
  <p class="busy">Chargement…</p>
{/if}

{#if selection}
  <div class="modal-backdrop" role="presentation" onclick={(e) => e.target === e.currentTarget && close()}>
    <div class="modal card program-detail" role="dialog" aria-modal="true" aria-label="Détail de la séance">
      <div class="row spread">
        <span class="meta">{formatDay(sessionDate(selection.session, selection.week.week_monday))} · S{selection.week.week_index}</span>
        <button class="icon" aria-label="Fermer le détail" bind:this={closeButton} onclick={close}><Icon name="close" size={16} /></button>
      </div>
      <SessionCard session={selection.session} weekMonday={selection.week.week_monday} {activities} readonly consult large />
    </div>
  </div>
{/if}

<style>
  .program-head { position: sticky; top: 0; z-index: 5; padding: 10px 0; background: var(--bg); align-items: center; }
  .back {
    display: inline-flex; align-items: center; gap: 6px; min-height: 44px; padding: 0 16px 0 12px; border-radius: 12px;
    border: 1px solid var(--border); background: var(--surface); color: var(--text-2); font-weight: 600; text-decoration: none;
  }
  .back:hover { color: var(--text); border-color: var(--muted); }
  .program-detail { width: min(640px, 100%); max-width: 640px; max-height: 100%; overflow-y: auto; }
  @media (max-width: 640px) {
    .program-head h1 { font-size: 22px; }
    .program-head .goal-pill, .program-head .meta { display: none; }
  }
</style>
