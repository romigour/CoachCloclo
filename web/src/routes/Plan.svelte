<script lang="ts">
  import { api, type Plan } from "../lib/api";
  import { formatDate } from "../lib/dates";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import WeekView from "../components/WeekView.svelte";

  let { version = 0, onerror: report }: { version?: number; onerror?: (e: unknown) => void } = $props();

  let plan = $state<Plan | null>(null);
  let error = $state<unknown>(null);

  let activityId = $state("");
  let targetSession = $state("");
  let matchMessage = $state("");

  async function load() {
    try {
      plan = await api.plan();
    } catch (e) {
      error = e;
      report?.(e);
    }
  }

  $effect(() => {
    version; // recharge après chaque synchro
    load();
  });

  function fail(e: unknown) {
    error = e;
    report?.(e);
  }

  const sessions = $derived((plan?.weeks ?? []).flatMap((w) => w.sessions.map((s) => ({ ...s, week: w.week_index }))));

  async function match(e: Event) {
    e.preventDefault();
    matchMessage = "";
    try {
      await api.match(Number(activityId), targetSession === "" ? null : Number(targetSession));
      matchMessage = targetSession === "" ? "Activité détachée" : "Activité rattachée";
      await load();
    } catch (err) {
      fail(err);
    }
  }
</script>

<h1>Plan</h1>
<ErrorBanner {error} onpin={load} />

{#if plan}
  {#if !plan.goal}
    <p class="card">Aucun objectif. <a href="#/goal">Créer un objectif</a></p>
  {:else if !plan.goal.plan_accepted}
    <p class="card">Le plan n'est pas encore validé. <a href="#/goal">Relire le brouillon</a></p>
  {:else}
    <p class="meta">
      Objectif : {plan.goal.distance_km} km{plan.goal.type === "trail" ? ` · ${plan.goal.d_plus_m} m D+` : ""}, le
      {formatDate(plan.goal.race_date)}
    </p>
    {#each plan.weeks as week (week.week_index)}
      <WeekView {week} onchanged={load} onerror={fail} />
    {/each}

    <details class="card">
      <summary>Corriger le rattachement d'une activité</summary>
      <form onsubmit={match}>
        <label>
          Numéro de l'activité
          <input type="number" min="1" bind:value={activityId} required />
        </label>
        <label>
          Séance
          <select bind:value={targetSession}>
            <option value="">Aucune (détacher)</option>
            {#each sessions as s}
              <option value={String(s.id)}>Semaine {s.week} · {s.title}</option>
            {/each}
          </select>
        </label>
        <button class="primary">Appliquer</button>
        {#if matchMessage}<span class="ok">{matchMessage}</span>{/if}
      </form>
    </details>
  {/if}
{:else if !error}
  <p>Chargement…</p>
{/if}
