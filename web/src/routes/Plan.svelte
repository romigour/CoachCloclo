<script lang="ts">
  import { api, type Plan } from "../lib/api";
  import { formatDate } from "../lib/dates";
  import SyncButton from "../components/SyncButton.svelte";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import WeekView from "../components/WeekView.svelte";

  let {
    version = 0,
    syncing = false,
    onsynced,
    onerror: report,
  }: { version?: number; syncing?: boolean; onsynced?: () => void; onerror?: (e: unknown) => void } = $props();

  let plan = $state<Plan | null>(null);
  let error = $state<unknown>(null);

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
    <div class="sync-row">
      <SyncButton auto={false} disabled={syncing} {onsynced} onerror={fail} />
    </div>
    {#each plan.weeks as week (week.week_index)}
      <WeekView {week} onchanged={load} onerror={fail} />
    {/each}

  {/if}
{:else if !error}
  <p>Chargement…</p>
{/if}
