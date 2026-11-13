<script lang="ts">
  import { api, type Cycle, type Goal, type PlanChange, type RaceSettings, type RaceView } from "../lib/api";
  import { formatDate } from "../lib/dates";
  import { goalLabel } from "../lib/goals";
  import { PRIORITY_LABELS } from "../lib/labels";
  import { fmtDuration, isDirty, settingsError, targetLabel } from "../lib/race";
  import { fmtClock, fmtDay, fmtNumber, fmtPace } from "../lib/stats/format";
  import ErrorBanner from "../components/ErrorBanner.svelte";
  import ElevationProfile from "../components/race/ElevationProfile.svelte";
  import AidStations from "../components/race/AidStations.svelte";
  import GoalEditDialog from "../components/GoalEditDialog.svelte";

  let {
    goals,
    goalId,
    cycle = null,
    onerror: report,
    onchanged,
  }: {
    /** Objectifs à venir, au choix dans le sélecteur. */
    goals: Goal[];
    /** Objectif affiché d'abord (le prochain par défaut). */
    goalId: number;
    /** Cycle actif : un objectif au-delà de sa fin (horizon) n'a pas encore de temps estimé. */
    cycle?: Cycle | null;
    onerror?: (e: unknown) => void;
    onchanged?: () => void;
  } = $props();

  // suit `goalId` quand il change (lien Jour J d'un autre objectif), modifiable par le sélecteur
  let selectedId = $derived(goalId);
  const goal = $derived(goals.find((g) => g.id === selectedId) ?? goals[0]);
  const inHorizon = $derived(!cycle || goal.race_date > cycle.end_date);
  const NO_REFERENCE = "Pas de temps de référence";
  const HORIZON_TIME = "Temps estimé à la préparation de son cycle, ou fixe un temps visé";

  let editing = $state(false);

  let view = $state<RaceView | null>(null);
  let draft = $state<RaceSettings | null>(null);
  let error = $state<unknown>(null);
  let busy = $state<"load" | "save" | "refresh" | "export" | "reimport" | null>(null);

  const current = $derived<RaceSettings | null>(draft);
  const dirty = $derived(!!view && !!current && isDirty(view.settings, current));
  const formError = $derived(current ? settingsError(current) : null);

  const plan = $derived(view?.plan ?? null);
  // un objectif de l'horizon attend son cycle pour être estimé : HORIZON_TIME remplace le message générique
  const warnings = $derived((plan?.warnings ?? []).filter((w) => !(inHorizon && w.startsWith(NO_REFERENCE))));
  const hasTarget = $derived(plan?.target_time_s != null);
  // les données Garmin ne servent qu'à l'estimation de repli et aux zones FC du trail
  const usesBasis = $derived(!hasTarget || view?.goal_type === "trail");
  const avgPace = $derived(plan?.reference_time_s ? plan.reference_time_s / plan.distance_km : null);
  const dPlus = $derived(plan?.segments.reduce((sum, s) => sum + s.d_plus_m, 0) ?? 0);
  const sent = $derived(!!view && view.workout_id !== null && !view.export_error);
  const stale = $derived(sent && !!view?.export_stale);

  function apply(v: RaceView) {
    view = v;
    draft = structuredClone(v.settings);
  }

  async function run(kind: NonNullable<typeof busy>, call: () => Promise<RaceView>) {
    busy = kind;
    try {
      apply(await call());
      error = null;
    } catch (e) {
      error = e;
      report?.(e);
    } finally {
      busy = null;
    }
  }

  const load = () => run("load", () => api.racePlan(goal.id));
  const save = () => {
    if (formError || !current) return;
    return run("save", () => api.saveRacePlan(goal.id, current));
  };
  const refresh = () => run("refresh", () => api.refreshRacePlan(goal.id));
  const reimport = () => run("reimport", () => api.reimportRacePlan(goal.id));
  const exportToWatch = () => run("export", () => api.exportRacePlan(goal.id));

  $effect(() => {
    goal.id;
    load();
  });

  // comme depuis la page Objectifs : la modification passe par une proposition de Claude
  function edited(r: PlanChange) {
    editing = false;
    onchanged?.();
    if (r.proposal_id != null) location.hash = "#/proposal";
    else if (r.needs_generation) location.hash = "#/goal"; // le bandeau « Générer » y attend
    else load();
  }
</script>

<header class="page-head">
  <div>
    <p class="eyebrow">{fmtDay(goal.race_date)}</p>
    <h1>Jour J</h1>
  </div>
  <label class="pick">
    Objectif
    <select bind:value={selectedId}>
      {#each goals as g (g.id)}
        <option value={g.id}>{goalLabel(g)} · {formatDate(g.race_date)} ({PRIORITY_LABELS[g.priority]})</option>
      {/each}
    </select>
  </label>
</header>

<ErrorBanner {error} onpin={load} />

{#if view && draft && plan}
  <section class="card lg stack" aria-label="Prédiction">
    <div class="head-grid">
      <div>
        <p class="meta">{hasTarget ? "Temps visé" : "Estimation d'après tes données Garmin"}</p>
        <p class="big">{plan.reference_time_s ? fmtDuration(plan.reference_time_s) : "—"}</p>
        <p class="meta">
          {#if hasTarget}{view.target_source === "claude" ? "estimé par Claude" : "fixé par toi"}{:else if inHorizon}{HORIZON_TIME}{:else}Pas de temps visé{/if}
        </p>
        <button type="button" onclick={() => (editing = true)}>Modifier l'objectif</button>
      </div>
      {#if usesBasis}
        <div>
          <p class="meta">Données Garmin du {fmtDay(view.basis_date)}</p>
          <button type="button" onclick={refresh} disabled={busy !== null || dirty}>Actualiser</button>
        </div>
      {/if}
      <div>
        <label for="race-start">Heure de départ</label>
        <input id="race-start" type="time" bind:value={draft.start_time} />
      </div>
      <div>
        <p class="meta">Allure moyenne</p>
        <p class="big">{avgPace ? fmtPace(avgPace) : "—"}</p>
      </div>
      {#if view.goal_type === "trail"}
        <div>
          <p class="meta">D+ (profil)</p>
          <p class="big">{fmtNumber(dPlus)} m</p>
        </div>
      {/if}
    </div>

    {#if warnings.length}
      <ul class="warnings" aria-label="Avertissements">
        {#each warnings as w, i (i)}<li>{w}</li>{/each}
      </ul>
    {/if}
  </section>

  {#if view.profile}
    <section class="card lg stack" aria-label="Profil">
      <h2>Profil</h2>
      <ElevationProfile profile={view.profile} segments={plan.segments} stations={view.goal_type === "trail" ? draft.aid_stations : []} />
    </section>
  {/if}

  <section class="card lg stack">
    <h2>Segments</h2>
    <div class="scroll">
      <table aria-label="Segments">
        <thead>
          <tr>
            <th>N°</th><th>Type</th><th>Km</th><th>D+ / D-</th><th>Pente</th><th>Allure</th>
            <th>Temps</th><th>Cumulé</th><th>Heure</th><th>Cible montre</th>
          </tr>
        </thead>
        <tbody>
          {#each plan.segments as s (s.index)}
            <tr>
              <td>{s.index}</td>
              <td>{s.kind}</td>
              <td>{fmtNumber(s.start_km, 1)} → {fmtNumber(s.end_km, 1)}</td>
              <td>+{s.d_plus_m} / -{s.d_minus_m} m</td>
              <td>{fmtNumber(s.avg_grade_pct, 1)} %</td>
              <td>{s.pace_s_km ? fmtPace(s.pace_s_km) : "—"}</td>
              <td>{s.time_s ? fmtClock(s.time_s) : "—"}</td>
              <td>{s.elapsed_s ? fmtClock(s.elapsed_s) : "—"}</td>
              <td>{s.clock ?? "—"}</td>
              <td>{targetLabel(s)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>

  {#if view.goal_type === "trail"}
    <section class="card lg stack">
      <h2>Ravitaillements</h2>
      <AidStations
        stations={draft.aid_stations}
        distanceKm={plan.distance_km}
        passages={plan.aid_passages}
        canReimport={busy === null && !dirty}
        onchange={(s) => (draft!.aid_stations = s)}
        onreimport={reimport}
      />
    </section>

    <section class="card lg stack">
      <h2>Nutrition</h2>
      <div class="head-grid">
        <div>
          <label for="race-carbs">Glucides (g/h)</label>
          <input id="race-carbs" type="number" min="0" bind:value={draft.carbs_g_h} />
        </div>
        <div>
          <label for="race-water">Eau (ml/h)</label>
          <input id="race-water" type="number" min="0" bind:value={draft.water_ml_h} />
        </div>
        <div>
          <label for="race-carry">Contenance emportée (ml)</label>
          <input id="race-carry" type="number" min="0" bind:value={draft.carry_ml} />
        </div>
      </div>
      <div class="scroll">
        <table aria-label="Nutrition">
          <thead>
            <tr><th>Tronçon</th><th>Km</th><th>Durée</th><th>Glucides</th><th>Eau</th><th>Alerte</th></tr>
          </thead>
          <tbody>
            {#each plan.nutrition as leg, i (i)}
              <tr>
                <td>{leg.from_name} → {leg.to_name}</td>
                <td>{fmtNumber(leg.from_km, 1)} → {fmtNumber(leg.to_km, 1)}</td>
                <td>{fmtDuration(leg.duration_s)}</td>
                <td>{fmtNumber(leg.carbs_g)} g</td>
                <td>{fmtNumber(leg.water_ml)} ml</td>
                <td>{#if leg.over_capacity}<span class="pill missed">Dépasse la contenance</span>{:else}—{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/if}

  <div class="row actions">
    {#if formError}<span class="error" role="alert">{formError}</span>{/if}
    {#if dirty}<span class="meta" role="status">Modifications non enregistrées</span>{/if}
    <button type="button" class="primary" onclick={save} disabled={busy !== null || !dirty || !!formError}>Enregistrer</button>
    <button type="button" onclick={exportToWatch} disabled={busy !== null || dirty}>Envoyer à la montre</button>
    {#if stale}
      <span class="meta" role="status">Plan modifié depuis l'envoi : renvoie-le à la montre</span>
    {:else if sent}
      <span class="meta" role="status">Envoyé à la montre</span>
    {/if}
    {#if view.export_error}<span class="error" role="alert">Échec de l'envoi : {view.export_error}</span>{/if}
  </div>
{/if}

{#if editing}
  <GoalEditDialog {goal} onclose={() => (editing = false)} onsaved={edited} />
{/if}

<style>
  .pick { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
  .head-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; align-items: start; }
  .big { font-size: 26px; font-weight: 700; margin: 0; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--divider); white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: 13px; }
  .error { color: var(--danger); margin: 0; }
  .warnings { margin: 0; padding-left: 18px; color: var(--todo); }
  .actions { align-items: center; gap: 12px; flex-wrap: wrap; }
</style>
