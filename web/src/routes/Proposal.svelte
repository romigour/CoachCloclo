<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Proposal } from "../lib/api";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import SessionCard from "../components/SessionCard.svelte";

  let { onchanged }: { onchanged?: () => void } = $props();

  let proposal = $state<Proposal | null>(null);
  let loaded = $state(false);
  let error = $state<unknown>(null);
  let busy = $state(false);
  let warning = $state("");

  const OP_LABEL = { modify: "Modifier", add: "Ajouter", remove: "Retirer" } as const;

  async function load() {
    try {
      proposal = await api.pendingProposal();
      loaded = true;
    } catch (e) {
      error = e;
    }
  }
  onMount(load);

  async function decide(accept: boolean) {
    if (!proposal) return;
    busy = true;
    error = null;
    try {
      if (accept) {
        const r = await api.acceptProposal(proposal.id);
        if (r.sync_error_ids.length) {
          warning = "Certaines séances n'ont pas pu être synchronisées avec Garmin : réessaie depuis le plan.";
          proposal = null;
          onchanged?.();
          return;
        }
      } else {
        await api.rejectProposal(proposal.id);
      }
      onchanged?.();
      location.hash = "#/plan";
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }
</script>

<h1>Proposition de Claude</h1>
<ErrorBanner {error} onpin={load} />

{#if warning}
  <p class="banner warning">{warning} <a href="#/plan">Voir le plan</a></p>
{/if}

{#if proposal}
  <section class="card">
    <h2>Analyse</h2>
    <p>{proposal.analysis}</p>
  </section>
  <h2>Changements proposés</h2>
  {#each proposal.changes as c}
    <section class="card change {c.op}">
      <h3>{OP_LABEL[c.op]}{c.session_id != null ? ` la séance n° ${c.session_id}` : " une séance"}</h3>
      <p class="reason">{c.reason}</p>
      {#if c.session}
        <SessionCard
          session={{ ...c.session, id: c.session_id ?? 0, status: "todo", scheduled_date: null, chaining_note: c.session.chaining_note ?? null, sync_error: null }}
          weekMonday=""
          readonly
        />
        <p class="meta">Semaine {c.session.week_index}</p>
      {/if}
    </section>
  {:else}
    <p>Aucun changement proposé.</p>
  {/each}
  <div class="row sticky">
    <button class="primary" onclick={() => decide(true)} disabled={busy}>Accepter</button>
    <button onclick={() => decide(false)} disabled={busy}>Refuser</button>
  </div>
{:else if loaded && !warning}
  <p class="card">Aucune proposition en attente. <a href="#/plan">Retour au plan</a></p>
{/if}
