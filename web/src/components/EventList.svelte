<script lang="ts">
  import { api, type CoachEvent, type EventKind } from "../lib/api";
  import { todayIso } from "../lib/dates";
  import ErrorBanner from "./ErrorBanner.svelte";

  let {
    today = todayIso(),
    onproposal,
    onchanged,
    reload = 0,
  }: {
    today?: string;
    onproposal?: (proposalId: number) => void;
    /** Un imprévu a été supprimé : la page recharge son plan (un arrêt ouvert peut disparaître). */
    onchanged?: () => void;
    /** Compteur incrémenté par la page quand son plan est rechargé : la liste se rafraîchit aussi. */
    reload?: number;
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

  let events = $state<CoachEvent[]>([]);
  let error = $state<unknown>(null);
  let busy = $state(false);
  let recompute = $state(false); // après une suppression : « Recalculer le plan ? »

  // en cours ou à venir : sans fin, ou finissant aujourd'hui ou plus tard
  const current = $derived(events.filter((e) => e.end_date == null || e.end_date >= today));

  async function load() {
    try {
      events = await api.events();
    } catch (e) {
      error = e;
    }
  }

  $effect(() => {
    reload; // recharge quand la page a rechargé son plan (ex. reprise après un arrêt)
    load();
  });

  async function remove(e: CoachEvent) {
    busy = true;
    error = null;
    try {
      await api.deleteEvent(e.id);
      recompute = true;
      await load();
      onchanged?.();
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

{#if current.length || recompute || error}
  <section class="card stack" aria-label="Imprévus">
    <h3>Imprévus</h3>
    {#if current.length}
      <ul class="stack">
        {#each current as e (e.id)}
          <li class="row spread">
            <span>{LABEL[e.kind]} · {range(e)}{#if e.note} · <span class="meta">{e.note}</span>{/if}</span>
            <button onclick={() => remove(e)} disabled={busy}>Supprimer</button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if recompute}
      <div class="row">
        <span>Recalculer le plan ?</span>
        <button class="primary" onclick={adjust} disabled={busy}>Oui</button>
        <button onclick={() => (recompute = false)} disabled={busy}>Non</button>
      </div>
      {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
    {/if}
    <ErrorBanner {error} />
  </section>
{/if}
