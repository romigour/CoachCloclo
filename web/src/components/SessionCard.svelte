<script lang="ts">
  import { api, type Activity, type Session } from "../lib/api";
  import { formatActivity } from "../lib/activity";
  import { formatDay } from "../lib/dates";
  import { STATUS_LABEL, TYPE_LABEL } from "../lib/labels";
  import { formatSteps } from "../lib/steps";
  import ExportDialog from "./ExportDialog.svelte";

  let {
    session,
    weekMonday,
    readonly = false,
    activities = [],
    onchanged,
    onerror,
  }: {
    session: Session;
    weekMonday: string;
    readonly?: boolean;
    activities?: Activity[];
    onchanged?: () => void;
    onerror?: (e: unknown) => void;
  } = $props();

  let dialog = $state<"export" | "move" | null>(null);
  let busy = $state(false);
  let correcting = $state(false);

  const matched = $derived(activities.find((a) => a.session_id === session.id) ?? null);

  const lines = $derived(formatSteps(session.steps));

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

<article class="card session">
  <header>
    <h3>{session.title}</h3>
    {#if !readonly}
      <span class="badge {session.status}">{STATUS_LABEL[session.status]}</span>
    {/if}
  </header>
  <p class="meta">
    {TYPE_LABEL[session.type] ?? session.type} · conseillé : {session.suggested_day}
    {#if session.scheduled_date} · prévu le {formatDay(session.scheduled_date)}{/if}
  </p>
  {#if session.chaining_note}<p class="note">{session.chaining_note}</p>{/if}
  <p>{session.description}</p>
  <ul class="steps">
    {#each lines as line}<li>{line}</li>{/each}
  </ul>
  {#if !readonly && (matched || session.status === "done")}
    <p class="matched">
      Activité : {matched ? formatActivity(matched) : "rattachée"}
      <button class="link" onclick={() => (correcting = !correcting)} disabled={busy}>Corriger</button>
    </p>
    {#if correcting}
      <div class="row correct">
        {#each activities as a (a.id)}
          <button class:primary={a.session_id === session.id} onclick={() => rematch(a.id, session.id)} disabled={busy}>
            {formatActivity(a)}
          </button>
        {/each}
        {#if matched}
          <button onclick={() => rematch(matched.id, null)} disabled={busy}>Aucune</button>
        {/if}
        {#if !activities.length}<span class="meta">Aucune activité cette semaine</span>{/if}
      </div>
    {/if}
  {/if}
  {#if session.sync_error}<p class="error">{session.sync_error}</p>{/if}

  {#if !readonly}
    <div class="row">
      {#if session.status === "todo" || session.status === "missed"}
        <button class="primary" onclick={() => (dialog = "export")} disabled={busy}>Exporter</button>
      {/if}
      {#if session.status === "exported" || session.status === "sync_error"}
        <button onclick={() => (dialog = "move")} disabled={busy}>Déplacer</button>
        <button onclick={() => act(() => api.unschedule(session.id))} disabled={busy}>Retirer</button>
      {/if}
      {#if session.status === "sync_error"}
        <button class="primary" onclick={() => act(() => api.retry(session.id))} disabled={busy}>Réessayer</button>
      {/if}
    </div>
  {/if}
</article>

{#if dialog}
  <ExportDialog {session} {weekMonday} mode={dialog} onclose={() => (dialog = null)} ondone={done} {onerror} />
{/if}
