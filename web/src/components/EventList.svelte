<script lang="ts">
  import { api, type CoachEvent, type EventKind } from "../lib/api";
  import { todayIso } from "../lib/dates";
  import ErrorBanner from "./ErrorBanner.svelte";
  import { READONLY } from "../lib/mode";

  let {
    list,
    readError = null,
    today = todayIso(),
    onproposal,
    onchanged,
  }: {
    /** Imprévus lus par la page, en même temps que son plan. */
    list: CoachEvent[];
    /** Échec de cette lecture. */
    readError?: unknown;
    today?: string;
    onproposal?: (proposalId: number) => void;
    /** Un imprévu a été supprimé : la page relit son plan et ses imprévus (un arrêt ouvert peut disparaître). */
    onchanged?: () => void | Promise<void>;
  } = $props();

  const LABEL: Record<EventKind, string> = {
    unavailable: "Indisponible",
    injury: "Blessure / maladie",
    light_week: "Semaine allégée",
    fatigue: "Fatigue",
  };

  const dm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
  const range = (e: CoachEvent) =>
    e.end_date == null ? `depuis le ${dm(e.start_date)}` : `du ${dm(e.start_date)} au ${dm(e.end_date)}`;

  let error = $state<unknown>(null);
  let busy = $state(false);
  let recompute = $state(false); // après une suppression : « Recalculer le plan ? »

  // en cours ou à venir : sans fin, ou finissant aujourd'hui ou plus tard
  const current = $derived(list.filter((e) => e.end_date == null || e.end_date >= today));

  async function remove(e: CoachEvent) {
    busy = true;
    error = null;
    try {
      await api.deleteEvent(e.id);
      recompute = true;
      await onchanged?.();
    } catch (err) {
      error = err;
    } finally {
      busy = false;
    }
  }

  async function adjust() {
    busy = true;
    error = null;
    try {
      const r = await api.requestAdjustment();
      recompute = false;
      onproposal?.(r.proposal_id);
    } catch (err) {
      error = err;
    } finally {
      busy = false;
    }
  }
</script>

{#if current.length || recompute || error || readError}
  <section class="card stack" aria-label="Imprévus">
    <h3>Imprévus</h3>
    {#if current.length}
      <ul class="stack">
        {#each current as e (e.id)}
          <li class="row spread">
            <span>{LABEL[e.kind]} · {range(e)}{#if e.note} · <span class="meta">{e.note}</span>{/if}</span>
            {#if !READONLY}<button onclick={() => remove(e)} disabled={busy}>Supprimer</button>{/if}
          </li>
        {/each}
      </ul>
    {/if}
    {#if !READONLY && recompute}
      <div class="row">
        <span>Recalculer le plan ?</span>
        <button class="primary" onclick={adjust} disabled={busy}>Oui</button>
        <button onclick={() => (recompute = false)} disabled={busy}>Non</button>
      </div>
      {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
    {/if}
    <ErrorBanner error={error ?? readError} />
  </section>
{/if}
