<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Goal, type Plan } from "../lib/api";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import WeekView from "../components/WeekView.svelte";

  let { onchanged }: { onchanged?: () => void } = $props();

  let type = $state<"route" | "trail">("route");
  let distance = $state(21.1);
  let dplus = $state(0);
  let raceDate = $state("");
  let perWeek = $state(4);
  let gpx = $state<File | null>(null);

  let goal = $state<Goal | null>(null);
  let plan = $state<Plan | null>(null);
  let summary = $state("");
  let busy = $state("");
  let error = $state<unknown>(null);

  // reprend un brouillon existant (objectif actif non validé)
  onMount(async () => {
    try {
      const p = await api.plan();
      if (p.goal && !p.goal.plan_accepted && p.weeks.length) {
        goal = p.goal;
        plan = p;
      }
    } catch (e) {
      error = e;
    }
  });

  async function generate(g: Goal) {
    busy = "Claude construit ton plan… (cela peut prendre une minute)";
    const r = await api.generate(g.id);
    summary = r.summary;
    plan = await api.plan();
  }

  async function submit(e: Event) {
    e.preventDefault();
    error = null;
    busy = "Création de l'objectif…";
    try {
      goal = await api.createGoal({
        type,
        distance_km: distance,
        d_plus_m: type === "trail" ? dplus : 0,
        race_date: raceDate,
        sessions_per_week: perWeek,
        gpx,
      });
      await generate(goal);
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  async function regenerate() {
    if (!goal) return;
    error = null;
    try {
      await generate(goal);
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  async function accept() {
    if (!goal) return;
    error = null;
    busy = "Validation…";
    try {
      await api.accept(goal.id);
      onchanged?.();
      location.hash = "#/plan";
    } catch (err) {
      error = err;
    } finally {
      busy = "";
    }
  }

  function pickFile(e: Event) {
    gpx = (e.target as HTMLInputElement).files?.[0] ?? null;
  }
</script>

<h1>Objectif</h1>
<ErrorBanner {error} />

{#if busy}
  <p class="card busy" role="status">{busy}</p>
{/if}

{#if plan && goal}
  <section class="card">
    <h2>Brouillon du plan</h2>
    <p class="meta">{goal.distance_km} km{goal.type === "trail" ? ` · ${goal.d_plus_m} m D+` : ""} · {plan.weeks.length} semaines</p>
    {#if summary}<p>{summary}</p>{/if}
    <div class="row">
      <button class="primary" onclick={accept} disabled={!!busy}>Valider le plan</button>
      <button onclick={regenerate} disabled={!!busy}>Régénérer</button>
    </div>
  </section>
  {#each plan.weeks as week (week.week_index)}
    <WeekView {week} readonly />
  {/each}
{:else}
  <form class="card" onsubmit={submit}>
    <label>
      Type de course
      <select bind:value={type}>
        <option value="route">Route</option>
        <option value="trail">Trail</option>
      </select>
    </label>
    <label>
      Distance (km)
      <input type="number" step="0.1" min="1" bind:value={distance} required />
    </label>
    {#if type === "trail"}
      <label>
        Dénivelé positif (m)
        <input type="number" min="0" step="10" bind:value={dplus} required />
      </label>
    {/if}
    <label>
      Date de la course
      <input type="date" bind:value={raceDate} required />
    </label>
    <label>
      Séances par semaine
      <input type="number" min="1" max="7" bind:value={perWeek} required />
    </label>
    <label>
      Tracé GPX (facultatif)
      <input type="file" accept=".gpx,application/gpx+xml" onchange={pickFile} />
    </label>
    <button class="primary" disabled={!!busy}>Générer le plan</button>
  </form>
{/if}
