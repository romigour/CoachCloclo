<script lang="ts">
  import { api, type Activity, type Comparison, type Session } from "../lib/api";
  import { formatActivity } from "../lib/activity";
  import { formatDay } from "../lib/dates";
  import { STATUS_LABEL, TYPE_LABEL } from "../lib/labels";
  import { formatDuration, peakLevel, stepLevel, totalSeconds } from "../lib/profile";
  import { doneLabel, paceText, repeatSummary, stepLabel, targetLabel, VERDICT_LABEL } from "../lib/comparison";
  import { fmtClock } from "../lib/stats/format";
  import { formatSteps } from "../lib/steps";
  import { currentZones } from "../lib/zones.svelte";
  import Icon from "./Icon.svelte";
  import { READONLY } from "../lib/mode";
  import ExportDialog from "./ExportDialog.svelte";
  import IntensityProfile from "./IntensityProfile.svelte";

  /** Fenêtre des courses proposées au rattachement manuel. */
  const FREE_DAYS = 14;

  let {
    session,
    weekMonday,
    readonly = false,
    large = false,
    activities = [],
    onchanged,
    onerror,
  }: {
    session: Session;
    weekMonday: string;
    readonly?: boolean;
    large?: boolean;
    activities?: Activity[];
    onchanged?: () => void;
    onerror?: (e: unknown) => void;
  } = $props();

  let dialog = $state<"export" | "move" | null>(null);
  let busy = $state(false);
  let correcting = $state(false);
  let candidates = $state<Activity[] | null>(null);

  let comparison = $state<Comparison | null>(null);
  let comparisonAsked = false;
  let failed = $state(false);
  let detailsEl = $state<HTMLDetailsElement>();

  const matched = $derived(activities.find((a) => a.session_id === session.id) ?? null);
  /** Identité de ce qui est comparé : change avec la séance affichée ou l'activité rattachée. */
  const comparisonKey = $derived(`${session.id}:${matched?.id ?? ""}`);
  let seenKey = comparisonKey;

  // Une autre séance (ou une autre activité après « Corriger ») invalide le détail déjà chargé.
  $effect(() => {
    const key = comparisonKey;
    if (key === seenKey) return;
    seenKey = key;
    comparison = null;
    comparisonAsked = false;
    failed = false;
    if (detailsEl) detailsEl.open = false;
  });
  const lines = $derived(formatSteps(session.steps, currentZones()));
  const levels = $derived(session.steps.map((item) => ("repeat" in item ? peakLevel([item]) : stepLevel(item))));
  const total = $derived(totalSeconds(session.steps));

  async function act(fn: () => Promise<unknown>) {
    busy = true;
    try {
      await fn();
      onchanged?.();
    } catch (e) {
      onerror?.(e);
    } finally {
      busy = false;
    }
  }

  async function toggleCorrecting() {
    correcting = !correcting;
    if (!correcting) return;
    candidates = null;
    try {
      const free = await api.freeActivities(FREE_DAYS, session.sport);
      candidates = matched ? [matched, ...free] : free;
    } catch (e) {
      correcting = false;
      onerror?.(e);
    }
  }

  /** Charge le prévu / réalisé au premier dépliage seulement. */
  async function loadComparison() {
    if (comparisonAsked) return;
    comparisonAsked = true;
    failed = false;
    const key = comparisonKey;
    try {
      const result = await api.comparison(session.id);
      if (key === seenKey) comparison = result;
    } catch (e) {
      if (key !== seenKey) return;
      comparisonAsked = false;
      failed = true;
      onerror?.(e);
    }
  }

  function lapLine(l: { index: number; duration_s: number; distance_m: number; avg_hr: number | null; avg_pace_s_km: number | null }) {
    return [
      `${l.index + 1}`,
      `${Math.round(l.distance_m)} m`,
      fmtClock(l.duration_s),
      l.avg_pace_s_km != null ? paceText(l.avg_pace_s_km) : null,
      l.avg_hr != null ? `${Math.round(l.avg_hr)} bpm` : null,
    ]
      .filter(Boolean)
      .join(" · ");
  }

  async function rematch(activityId: number, sessionId: number | null) {
    await act(() => api.match(activityId, sessionId));
    correcting = false;
  }

  function done() {
    dialog = null;
    onchanged?.();
  }
</script>

<article class="session stack">
  <div class="row spread">
    <span class="row tight">
      <span class="chip">{TYPE_LABEL[session.type] ?? session.type}</span>
      {#if session.sport === "bike"}<span class="chip"><Icon name="bike" size={14} /> Vélo</span>{/if}
    </span>
    {#if READONLY || !readonly}
      <span class="pill {session.status}">{STATUS_LABEL[session.status]}</span>
    {/if}
  </div>

  <div class="stack tight">
    <h2 class="session-title" class:lg={large}>{session.title}</h2>
    <div class="stats">
      {#if total}<div class="stat"><strong>{formatDuration(total)}</strong><span>Durée</span></div>{/if}
      <div class="stat">
        <strong>{session.scheduled_date ? formatDay(session.scheduled_date) : session.suggested_day}</strong>
        <span>{session.scheduled_date ? "Prévue le" : "Jour conseillé"}</span>
      </div>
    </div>
  </div>

  <IntensityProfile steps={session.steps} small={!large} />

  {#if session.description}<p>{session.description}</p>{/if}

  {#if lines.length}
    <ol class="steps">
      {#each lines as line, i (i)}
        <li><span class="bar lv{levels[i]}"></span><span>{line}</span></li>
      {/each}
    </ol>
  {/if}

  {#if session.chaining_note}<p class="tip">{session.chaining_note}</p>{/if}

  {#if !READONLY && !readonly}
    <div class="row spread">
      {#if matched || session.status === "done"}
        <span class="matched">
          <span class="meta">Activité :</span>
          {matched ? formatActivity(matched) : "rattachée"}
        </span>
      {:else}
        <span></span>
      {/if}
      <button class="small" onclick={toggleCorrecting} disabled={busy} aria-expanded={correcting}>
        {matched || session.status === "done" ? "Corriger" : "Rattacher une activité"}
      </button>
    </div>
    {#if session.status === "done" && matched}
      <details class="cmp" bind:this={detailsEl} ontoggle={(e) => e.currentTarget.open && loadComparison()}>
        <summary>Prévu / réalisé</summary>
        {#if comparison?.available}
          {#if comparison.followed_workout}
            <ol class="cmp-steps">
              {#each comparison.steps as s, i (i)}
                {@const summary = i === 0 || comparison.steps[i - 1].group !== s.group ? repeatSummary(comparison.steps, s.group) : null}
                {#if summary}<li class="cmp-summary">{summary}</li>{/if}
                <li class="cmp-step" class:undone={!s.done}>
                  <span class="cmp-plan">
                    {stepLabel(s)}{#if targetLabel(s, comparison.target_kind)}{" · "}{targetLabel(s, comparison.target_kind)}{/if}
                  </span>
                  {#if s.done}
                    <span class="cmp-done">{doneLabel(s)}</span>
                    <span class="pill {s.verdict === 'in' ? 'done' : s.verdict ? 'todo' : ''}">
                      {s.verdict ? VERDICT_LABEL[s.verdict] : s.zone ? "donnée absente" : "sans cible"}
                    </span>
                  {:else}
                    <span class="cmp-done">non réalisée</span>
                  {/if}
                </li>
              {/each}
            </ol>
          {:else if comparison.laps.length}
            <p class="meta">Séance non suivie sur la montre : tours bruts</p>
            <ol class="cmp-steps">
              {#each comparison.laps as l (l.index)}<li class="cmp-step">{lapLine(l)}</li>{/each}
            </ol>
          {:else}
            <p class="meta">Aucun tour enregistré</p>
          {/if}
        {:else if comparison}
          {#if comparison.reason === "no_laps"}
            <p class="meta">Détail par étape disponible après la prochaine synchro</p>
          {/if}
        {:else if failed}
          <p class="meta">Impossible de charger le détail</p>
        {:else}
          <p class="meta">Chargement…</p>
        {/if}
      </details>
    {/if}
    {#if correcting && candidates}
      <div class="row correct">
        {#each candidates as a (a.id)}
          <button
            class="small"
            class:primary={a.session_id === session.id}
            onclick={() => rematch(a.id, session.id)}
            disabled={busy}
          >
            {formatActivity(a)}
          </button>
        {/each}
        {#if matched}
          <button class="small" onclick={() => rematch(matched.id, null)} disabled={busy}>Aucune</button>
        {/if}
        {#if !candidates.length}<span class="meta">Aucune course libre ces {FREE_DAYS} derniers jours</span>{/if}
      </div>
    {/if}
  {/if}

  {#if session.sync_error}<p class="banner error">{session.sync_error}</p>{/if}

  {#if !READONLY && !readonly && session.status !== "done" && session.status !== "missed"}
    <div class="actions">
      {#if session.status === "todo"}
        <button class="primary" onclick={() => (dialog = "export")} disabled={busy}>Envoyer sur la montre</button>
      {/if}
      {#if session.status === "sync_error"}
        <button class="primary" onclick={() => act(() => api.retry(session.id))} disabled={busy}>Réessayer</button>
      {/if}
      {#if session.status === "exported" || session.status === "sync_error"}
        <button onclick={() => (dialog = "move")} disabled={busy}>Changer de jour</button>
        <button class="danger" onclick={() => act(() => api.unschedule(session.id))} disabled={busy}>
          Retirer de Garmin
        </button>
      {/if}
    </div>
  {/if}
</article>

{#if !READONLY && dialog}
  <ExportDialog {session} {weekMonday} mode={dialog} onclose={() => (dialog = null)} ondone={done} {onerror} />
{/if}
