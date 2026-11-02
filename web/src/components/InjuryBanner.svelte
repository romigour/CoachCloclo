<script lang="ts">
  import { api, type CoachEvent } from "../lib/api";
  import { todayIso } from "../lib/dates";
  import ErrorBanner from "./ErrorBanner.svelte";

  let {
    injury,
    goalId,
    today = todayIso(),
    onproposal,
    onresumed,
  }: {
    injury: CoachEvent | null;
    goalId: number;
    today?: string;
    onproposal?: (proposalId: number) => void;
    /** La reprise est enregistrée (avec ou sans proposition) : la page recharge son plan. */
    onresumed?: () => void;
  } = $props();

  let choosing = $state(false);
  let date = $state("");
  let busy = $state(false);
  let error = $state<unknown>(null);
  // la reprise est enregistrée mais Claude a échoué : on ne la renvoie pas, on redemande l'ajustement
  let failure = $state<string | null>(null);

  const dm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

  function open() {
    date = today;
    choosing = true;
  }

  async function resume() {
    if (!injury) return;
    busy = true;
    error = null;
    try {
      const r = await api.resumeInjury(injury.id, date);
      if (r.proposal_id != null) onproposal?.(r.proposal_id);
      else failure = r.error ?? "Claude n'a pas pu ajuster ton plan";
      onresumed?.();
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }

  async function retry() {
    busy = true;
    error = null;
    try {
      const r = await api.requestAdjustment(goalId);
      failure = null;
      onproposal?.(r.proposal_id);
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }
</script>

{#if failure}
  <div class="card stack">
    <p>Ta reprise est enregistrée, mais Claude n'a pas pu ajuster ton plan.</p>
    <p class="hint" role="alert">{failure}</p>
    {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
    <ErrorBanner {error} />
    <div class="row"><button class="primary" onclick={retry} disabled={busy}>Réessayer</button></div>
  </div>
{:else if injury}
  <div class="card stack">
    <div class="row spread">
      <span>Arrêt depuis le {dm(injury.start_date)}</span>
      {#if !choosing}<button onclick={open}>Signaler la reprise</button>{/if}
    </div>
    {#if choosing}
      <label>
        Date de reprise
        <input type="date" bind:value={date} />
      </label>
      {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
      <ErrorBanner {error} />
      <div class="row">
        <button class="primary" onclick={resume} disabled={busy || !date}>Confirmer la reprise</button>
        <button onclick={() => (choosing = false)} disabled={busy}>Annuler</button>
      </div>
    {/if}
  </div>
{/if}
