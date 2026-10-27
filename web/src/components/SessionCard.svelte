<script lang="ts">
  import { api, type Session } from "../lib/api";
  import { formatDay } from "../lib/dates";
  import { STATUS_LABEL, TYPE_LABEL } from "../lib/labels";
  import { formatSteps } from "../lib/steps";
  import ExportDialog from "./ExportDialog.svelte";

  let {
    session,
    weekMonday,
    readonly = false,
    onchanged,
    onerror,
  }: {
    session: Session;
    weekMonday: string;
    readonly?: boolean;
    onchanged?: () => void;
    onerror?: (e: unknown) => void;
  } = $props();

  let dialog = $state<"export" | "move" | null>(null);
  let busy = $state(false);

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
