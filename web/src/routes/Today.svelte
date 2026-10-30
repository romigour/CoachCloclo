<script lang="ts">
  import { api, type Activity, type Plan, type Status } from "../lib/api";
  import { formatActivity } from "../lib/activity";
  import { formatDay, todayIso } from "../lib/dates";
  import { STATUS_LABEL } from "../lib/labels";
  import { currentWeek, days, daysUntil, focusSession } from "../lib/week";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import SessionCard from "../components/SessionCard.svelte";
  import Icon from "../components/Icon.svelte";

  let {
    version = 0,
    status = null,
    today = todayIso(),
    onerror: report,
  }: { version?: number; status?: Status | null; today?: string; onerror?: (e: unknown) => void } = $props();

  let plan = $state<Plan | null>(null);
  let activities = $state<Activity[]>([]);
  let error = $state<unknown>(null);
  let picked = $state<number | null>(null);

  const week = $derived(plan ? currentWeek(plan.weeks, today) : null);
  const strip = $derived(week ? days(week) : []);
  const focus = $derived.by(() => {
    const all = week?.sessions ?? [];
    return all.find((s) => s.id === picked) ?? focusSession(week, today);
  });
  const sessions = $derived(plan?.weeks.flatMap((w) => w.sessions) ?? []);
  const doneCount = $derived(sessions.filter((s) => s.status === "done").length);
  const lastActivity = $derived([...activities].sort((a, b) => b.date.localeCompare(a.date))[0] ?? null);

  async function load() {
    try {
      plan = await api.plan();
      const w = currentWeek(plan.weeks, today);
      activities = w ? await api.activities(w.week_index).catch(() => []) : [];
    } catch (e) {
      error = e;
      report?.(e);
    }
  }

  $effect(() => {
    version; // recharge après chaque synchro
    load();
  });

  function fail(e: unknown) {
    error = e;
    report?.(e);
  }

  const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const goalLabel = (g: NonNullable<Plan["goal"]>) =>
    `${g.distance_km.toLocaleString("fr-FR")} km ${g.type === "trail" ? `trail · ${g.d_plus_m} m D+` : "route"}`;
</script>

<header class="page-head">
  <div>
    <p class="eyebrow">
      {capitalize(formatDay(today))}{#if week && plan}{" · "}Semaine {week.week_index} sur {plan.weeks.length}{/if}
    </p>
    <h1>Aujourd'hui</h1>
  </div>
  {#if plan?.goal}
    <p>{goalLabel(plan.goal)} · <strong>J-{daysUntil(today, plan.goal.race_date)}</strong></p>
  {/if}
</header>

<ErrorBanner {error} onpin={load} />

{#if plan}
  {#if !plan.goal}
    <p class="card">Aucun objectif pour l'instant. <a href="#/goal">Créer un objectif</a></p>
  {:else if !plan.goal.plan_accepted}
    <p class="card">Ton plan n'est pas encore validé. <a href="#/goal">Relire le brouillon</a></p>
  {:else}
    <section class="week-strip" aria-label="Semaine en cours">
      {#each strip as d (d.date)}
        {@const s = d.sessions[0]}
        {#if s}
          <button
            class="day"
            class:today={d.date === today}
            class:past={s.status === "done"}
            aria-pressed={focus?.id === s.id}
            onclick={() => (picked = s.id)}
          >
            <span class="d">{capitalize(formatDay(d.date).split(" ").slice(0, 2).join(" "))}{d.date === today ? " · aujourd'hui" : ""}</span>
            <span class="t">{s.title}</span>
            <span class="pill {s.status}">{STATUS_LABEL[s.status]}</span>
          </button>
        {:else}
          <div class="day rest" class:today={d.date === today}>
            <span class="d">{capitalize(formatDay(d.date).split(" ").slice(0, 2).join(" "))}</span>
            <span>Repos</span>
          </div>
        {/if}
      {/each}
    </section>

    <div class="cols">
      <div class="col-main">
        {#if focus && week}
          <div class="card lg">
            <SessionCard
              session={focus}
              weekMonday={week.week_monday}
              large
              {activities}
              onchanged={load}
              onerror={fail}
            />
          </div>
        {:else}
          <div class="card lg stack">
            <h2>Repos aujourd'hui</h2>
            <p class="meta">Plus aucune séance prévue cette semaine.</p>
            <a class="more" href="#/plan">Voir le programme</a>
          </div>
        {/if}
      </div>

      <div class="col-side">
        {#if status?.pending_proposal_id != null}
          <a class="proposal-card" href="#/proposal">
            <span class="k row"><Icon name="chat" size={16} /> PROPOSITION DE CLAUDE</span>
            <strong>Claude propose des changements à ton plan</strong>
            <span class="go">Examiner la proposition →</span>
          </a>
        {/if}

        <section class="card stack">
          <h3>Progression</h3>
          <div class="weeks-bar" style:grid-template-columns="repeat({plan.weeks.length}, minmax(0, 1fr))">
            {#each plan.weeks as w (w.week_index)}
              <div
                class:past={week && w.week_index < week.week_index}
                class:now={week && w.week_index === week.week_index}
              ></div>
            {/each}
          </div>
          <div class="stats">
            <div class="stat"><strong>{doneCount} / {sessions.length}</strong><span>séances réalisées</span></div>
            <div class="stat"><strong>{daysUntil(today, plan.goal.race_date)} j</strong><span>avant la course</span></div>
          </div>
        </section>

        <section class="card stack">
          <h3>Dernière activité</h3>
          {#if lastActivity}
            <p>{formatActivity(lastActivity)}{#if lastActivity.avg_hr} · FC moy. {lastActivity.avg_hr}{/if}</p>
            <p class="meta">
              {lastActivity.session_id != null ? "Rattachée à une séance du plan" : "Pas rattachée à une séance"}
            </p>
          {:else}
            <p class="empty">Aucune activité cette semaine.</p>
          {/if}
        </section>
      </div>
    </div>
  {/if}
{:else if !error}
  <p class="busy">Chargement…</p>
{/if}
