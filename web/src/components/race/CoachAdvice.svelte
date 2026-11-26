<script lang="ts">
  import type { RaceView } from "../../lib/api";
  import { fmtDay } from "../../lib/stats/format";

  let {
    view,
    disabled = false,
    onask,
  }: {
    view: RaceView;
    disabled?: boolean;
    /** Demande les conseils à Claude ; absent en lecture seule. Une erreur reste dans la section. */
    onask?: () => Promise<void>;
  } = $props();

  let busy = $state(false);
  let error = $state<string | null>(null);

  async function ask() {
    if (!onask) return;
    busy = true;
    error = null;
    try {
      await onask();
    } catch (e) {
      error = e instanceof Error ? e.message : "Erreur inattendue";
    } finally {
      busy = false;
    }
  }
</script>

<section class="card lg stack" aria-label="Conseils du coach">
  <div class="row spread">
    <h2>Conseils du coach</h2>
    {#if view.advice_at}<span class="meta">Conseils du {fmtDay(view.advice_at.slice(0, 10))}</span>{/if}
  </div>

  {#if view.advice}
    {#if view.advice_stale}
      <p class="stale" role="status">Objectif modifié depuis : redemande les conseils</p>
    {/if}
    <ul class="tips">
      {#each view.advice.tips as tip, i (i)}
        <li>
          <strong>{tip.title}</strong>
          <p>{tip.text}</p>
        </li>
      {/each}
    </ul>
  {:else if onask}
    <p class="meta">Claude relit ton objectif, tes notes et tes dernières courses pour ajouter quelques conseils personnels au guide.</p>
  {:else}
    <p class="meta">Demande-les depuis l'ordinateur.</p>
  {/if}

  {#if onask}
    <div class="row">
      <button type="button" onclick={ask} disabled={disabled || busy}>
        {busy ? "Claude réfléchit…" : view.advice ? "Redemander les conseils du coach" : "Demander les conseils du coach"}
      </button>
    </div>
  {/if}
  {#if error}<p class="error" role="alert">Conseils indisponibles : {error}</p>{/if}
</section>

<style>
  h2, p { margin: 0; }
  .tips { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
  .tips p { color: var(--text-2); margin-top: 2px; }
  .stale { color: var(--todo); }
  .error { color: var(--danger); }
</style>
