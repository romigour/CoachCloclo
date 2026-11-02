<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Change, type Proposal, type Session } from "../lib/api";
  import { formatSteps } from "../lib/steps";
  import { currentZones } from "../lib/zones.svelte";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import IntensityProfile from "../components/IntensityProfile.svelte";
  import Icon from "../components/Icon.svelte";

  let { onchanged }: { onchanged?: () => void } = $props();

  let proposal = $state<Proposal | null>(null);
  let current = $state<Map<number, Session>>(new Map());
  let loaded = $state(false);
  let error = $state<unknown>(null);
  let busy = $state(false);
  let warning = $state("");

  const OP_LABEL = { modify: "Modifiée", add: "Ajoutée", remove: "Retirée" } as const;

  async function load() {
    try {
      const [p, plan] = await Promise.all([api.pendingProposal(), api.plan()]);
      proposal = p;
      current = new Map(plan.weeks.flatMap((w) => w.sessions).map((s) => [s.id, s]));
      loaded = true;
    } catch (e) {
      error = e;
    }
  }
  onMount(load);

  const before = (c: Change) => (c.session_id != null ? current.get(c.session_id) : undefined);
  const heading = (c: Change) => {
    const b = before(c);
    if (b) return b.title;
    if (c.session) return `Semaine ${c.session.week_index} · ${c.session.suggested_day}`;
    return c.session_id != null ? `Séance n° ${c.session_id}` : "Nouvelle séance";
  };

  async function decide(accept: boolean) {
    if (!proposal) return;
    busy = true;
    error = null;
    try {
      if (accept) {
        const r = await api.acceptProposal(proposal.id);
        if (r.sync_error_ids.length) {
          warning = "Certaines séances n'ont pas pu être synchronisées avec Garmin : réessaie depuis le programme.";
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

<header class="page-head">
  <div>
    {#if proposal}
      <p class="eyebrow">Reçue le {new Date(proposal.created_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })}</p>
      <h1>
        Claude propose {proposal.changes.length}
        {proposal.changes.length > 1 ? "changements" : "changement"}
      </h1>
    {:else}
      <h1>Propositions de Claude</h1>
    {/if}
  </div>
</header>

<ErrorBanner {error} onpin={load} />

{#if warning}
  <p class="banner warning">{warning} <a href="#/plan">Voir le programme</a></p>
{/if}

{#if proposal}
  <div class="cols">
    <section class="col-side card stack" style:flex-basis="320px">
      <h2>Ce que Claude a observé</h2>
      <p>{proposal.analysis}</p>
    </section>

    <section class="col-main">
      <h2>Changements proposés</h2>
      {#each proposal.changes as c, i (i)}
        {@const b = before(c)}
        <article class="card stack change {c.op}">
          <div class="row spread">
            <span class="row tight">
              <strong>{heading(c)}</strong>
              {#if c.session?.sport === "bike" && c.op !== "remove"}
                <span class="chip"><Icon name="bike" size={14} /> Vélo</span>
              {/if}
            </span>
            <span class="pill" class:done={c.op !== "remove"} class:missed={c.op === "remove"}>{OP_LABEL[c.op]}</span>
          </div>
          <div class="diff">
            <div class="side before">
              <span class="k">AVANT</span>
              <span class="v">{c.op === "add" ? "Aucune séance" : (b?.title ?? "Séance actuelle")}</span>
            </div>
            <Icon name="arrow" size={20} />
            <div class="side after">
              <span class="k">APRÈS</span>
              <span class="v">{c.op === "remove" ? "Séance retirée" : (c.session?.title ?? "")}</span>
            </div>
          </div>
          {#if c.session && c.op !== "remove"}
            <IntensityProfile steps={c.session.steps} small />
            <ul class="steps">
              {#each formatSteps(c.session.steps, currentZones()) as line, j (j)}<li>{line}</li>{/each}
            </ul>
          {/if}
          <p class="tip">{c.reason}</p>
        </article>
      {:else}
        <p class="card empty">Aucun changement proposé.</p>
      {/each}
    </section>
  </div>

  <div class="action-bar">
    <p>En acceptant, les séances déjà envoyées sont mises à jour dans ton calendrier Garmin.</p>
    <button onclick={() => decide(false)} disabled={busy}>Refuser</button>
    <button class="primary" onclick={() => decide(true)} disabled={busy}>Accepter les changements</button>
  </div>
{:else if loaded && !warning}
  <p class="card">Aucune proposition en attente. Claude en propose après l'analyse de tes séances. <a href="#/today">Retour à aujourd'hui</a></p>
{/if}
