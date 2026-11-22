<script lang="ts">
  import { api, type Cycle } from "../lib/api";
  import { READONLY } from "../lib/mode";
  import ErrorBanner from "./ErrorBanner.svelte";

  let {
    cycle,
    onproposal,
  }: {
    cycle: Cycle | null;
    /** La mise à jour a produit une proposition : la page l'ouvre. */
    onproposal?: (proposalId: number) => void;
  } = $props();

  let busy = $state(false);
  let error = $state<unknown>(null);

  // objectifs changés sur un plan validé ; un plan à régénérer a déjà son bandeau « Générer »
  const shown = $derived(!!cycle && cycle.adjust_due && cycle.plan_accepted && !cycle.needs_generation);

  /** Une seule demande à Claude pour tous les changements d'objectif en attente. */
  async function update() {
    busy = true;
    error = null;
    try {
      const r = await api.requestAdjustment();
      onproposal?.(r.proposal_id);
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }
</script>

{#if shown}
  <section class="card stack" aria-label="Plan à mettre à jour">
    <div class="row spread">
      <p>
        <strong>Tes objectifs ont changé</strong><br />
        <span class="meta">Lance la mise à jour quand tu as fini tes modifications.</span>
      </p>
      {#if READONLY}
        <span class="meta">À faire depuis l'ordinateur</span>
      {:else}
        <button class="primary" onclick={update} disabled={busy}>Mettre à jour l'entraînement</button>
      {/if}
    </div>
    {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
    <ErrorBanner {error} />
  </section>
{/if}
