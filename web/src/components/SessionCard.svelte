<script lang="ts">
  import { api, type Activity, type Session } from "../lib/api";
  import { formatActivity } from "../lib/activity";
  import { formatDay } from "../lib/dates";
  import { STATUS_LABEL, TYPE_LABEL } from "../lib/labels";
  import { formatDuration, peakLevel, stepLevel, totalSeconds } from "../lib/profile";
  import { formatSteps } from "../lib/steps";
  import ExportDialog from "./ExportDialog.svelte";
  import IntensityProfile from "./IntensityProfile.svelte";

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

  const matched = $derived(activities.find((a) => a.session_id === session.id) ?? null);
  const lines = $derived(formatSteps(session.steps));
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
    <span class="chip">{TYPE_LABEL[session.type] ?? session.type}</span>
    {#if !readonly}
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

  {#if !readonly && (matched || session.status === "done")}
    <div class="row spread">
      <span class="matched">
        <span class="meta">Activité :</span>
        {matched ? formatActivity(matched) : "rattachée"}
      </span>
      <button class="small" onclick={() => (correcting = !correcting)} disabled={busy} aria-expanded={correcting}>
        Corriger
      </button>
    </div>
    {#if correcting}
      <div class="row correct">
        {#each activities as a (a.id)}
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
        {#if !activities.length}<span class="meta">Aucune activité cette semaine</span>{/if}
      </div>
    {/if}
  {/if}

  {#if session.sync_error}<p class="banner error">{session.sync_error}</p>{/if}

  {#if !readonly && session.status !== "done" && session.status !== "missed"}
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

{#if dialog}
  <ExportDialog {session} {weekMonday} mode={dialog} onclose={() => (dialog = null)} ondone={done} {onerror} />
{/if}
