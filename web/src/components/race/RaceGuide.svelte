<script lang="ts">
  import type { Snippet } from "svelte";
  import type { Phase, RaceView } from "../../lib/api";
  import { fmtDuration } from "../../lib/race";
  import { fmtClock, fmtNumber, fmtPace } from "../../lib/stats/format";

  let {
    view,
    horizon = false,
    settings,
  }: {
    view: RaceView;
    /** Objectif au-delà du cycle actif : son temps sera estimé à la préparation de son cycle. */
    horizon?: boolean;
    /** Réglages, affichés juste sous l'encadré (absents en lecture seule). */
    settings?: Snippet;
  } = $props();

  const NO_REFERENCE = "Pas de temps de référence";
  const STATUS_CLASS = { ok: "done", serré: "todo", "hors délai": "missed" } as const;

  const guide = $derived(view.guide);
  const plan = $derived(view.plan);
  const trail = $derived(view.goal_type === "trail");
  const hasTarget = $derived(plan.target_time_s != null);
  // un objectif de l'horizon attend son cycle pour être estimé : la mention sous le temps remplace l'avertissement
  const warnings = $derived(plan.warnings.filter((w) => !(horizon && w.startsWith(NO_REFERENCE))));
  const dPlus = $derived(plan.segments.reduce((sum, s) => sum + s.d_plus_m, 0));
  const start = $derived(guide.phases.find((p) => p.name === "Départ") ?? null);
  // l'arrivée redit le temps visé : l'encadré ne garde que les bornes intermédiaires
  const boxSplits = $derived(guide.splits.filter((s) => s.km < plan.distance_km));
  const overCapacity = $derived(plan.nutrition.some((leg) => leg.over_capacity));
  const intakeGroups = $derived.by(() => {
    const groups = new Map<string, string[]>();
    for (const it of guide.nutrition.intakes) {
      const at = `km ${fmtNumber(it.km, 1)}${it.clock ? ` (${it.clock})` : ""}`;
      groups.set(it.what, [...(groups.get(it.what) ?? []), at]);
    }
    return [...groups];
  });

  const timeNote = $derived(
    hasTarget
      ? view.target_source === "claude" ? "estimé par Claude" : "fixé par toi"
      : horizon ? "Temps estimé à la préparation de son cycle, ou fixe un temps visé" : "Pas de temps visé",
  );

  const km = (n: number) => fmtNumber(n, 1);
  const paceRange = (p: Phase) =>
    p.pace_low_s_km != null && p.pace_high_s_km != null ? `${fmtClock(p.pace_low_s_km)}–${fmtPace(p.pace_high_s_km)}` : null;
  const hrRange = (p: Phase) =>
    p.hr_zone ? `${p.hr_zone}${p.hr_low != null && p.hr_high != null ? ` · ${p.hr_low}–${p.hr_high} bpm` : ""}` : null;
  const target = (p: Phase) => (trail ? hrRange(p) : paceRange(p));
  // « Petit-déjeuner : un repas connu… » → « Petit-déjeuner » dans l'encadré ; le détail est dans Préparation
  const shortStep = (label: string) => label.split(" : ")[0];

  const hrCue = $derived.by(() => {
    const first = start ? hrRange(start) : null;
    const next = guide.phases.find((p) => p.name !== "Départ" && p.hr_zone);
    const then = next ? hrRange(next) : null;
    if (!first) return then;
    return then && then !== first ? `Départ en ${first}, puis ${then}` : `Toute la course en ${first}`;
  });

  function marginLabel(m: number | null): string | null {
    if (m == null) return null;
    return m >= 0 ? `${m} min de marge` : `${-m} min après la barrière`;
  }
</script>

<section class="card lg stack morning-box" aria-label="À retenir le matin">
  <h2>À retenir le matin</h2>
  <div class="stats">
    <div>
      <p class="meta">{hasTarget ? "Temps visé" : "Estimation d'après tes données Garmin"}</p>
      <p class="big">{guide.reference_time_s ? fmtDuration(guide.reference_time_s) : "—"}</p>
      <p class="meta">{timeNote}</p>
    </div>
    {#if trail}
      <div>
        <p class="meta">D+ (profil)</p>
        <p class="big">{fmtNumber(dPlus)} m</p>
      </div>
    {:else}
      <div>
        <p class="meta">Allure moyenne</p>
        <p class="big">{guide.avg_pace_s_km ? fmtPace(guide.avg_pace_s_km) : "—"}</p>
      </div>
    {/if}
  </div>

  <dl class="cues">
    {#if trail}
      {#if hrCue}
        <dt>Cardio</dt>
        <dd>{hrCue}</dd>
      {/if}
      {#if guide.phases.length}
        <dt>Phases</dt>
        <dd>
          {#each guide.phases as p, i (i)}{i ? " · " : ""}{p.name} km {km(p.start_km)}–{km(p.end_km)}{p.clock_end ? ` → ${p.clock_end}` : ""}{/each}
        </dd>
      {/if}
      {#if plan.aid_passages.length}
        <dt>Ravitos</dt>
        <dd>
          <ul class="plain">
            {#each plan.aid_passages as a, i (i)}
              <li>
                {a.station.name} {a.passage.clock}
                {#if a.station.cutoff}<span class="meta">· barrière {a.station.cutoff}</span>{/if}
                {#if marginLabel(a.passage.margin_min)}<span>· {marginLabel(a.passage.margin_min)}</span>{/if}
                {#if a.passage.status}<span class="pill {STATUS_CLASS[a.passage.status]}">{a.passage.status}</span>{/if}
              </li>
            {/each}
          </ul>
        </dd>
      {/if}
      <dt>Nutrition</dt>
      <dd>
        {guide.nutrition.carbs_g_h} g de glucides par heure · eau {fmtNumber(guide.nutrition.water_ml_h)} ml/h, emporte {fmtNumber(view.settings.carry_ml)} ml
        {#if overCapacity}<span class="pill missed">Un tronçon dépasse la contenance</span>{/if}
      </dd>
    {:else}
      {#if start && paceRange(start)}
        <dt>Départ</dt>
        <dd>{paceRange(start)} jusqu'au km {km(start.end_km)}, pas plus vite</dd>
      {/if}
      {#if boxSplits.length}
        <dt>Passages</dt>
        <dd>{#each boxSplits as s, i (i)}{i ? " · " : ""}{s.label} {fmtClock(s.elapsed_s)}{/each}</dd>
      {/if}
      <dt>Matin</dt>
      <dd>{#each guide.morning as m, i (i)}{i ? " · " : ""}{m.clock} {shortStep(m.label)}{/each}</dd>
      {#each intakeGroups as [what, at] (what)}
        <dt>Prises</dt>
        <dd>{what} : {at.join(" · ")}</dd>
      {/each}
    {/if}
  </dl>

  {#if warnings.length}
    <ul class="warnings" aria-label="Avertissements">
      {#each warnings as w, i (i)}<li>{w}</li>{/each}
    </ul>
  {/if}
</section>

{@render settings?.()}

<section class="card lg stack" aria-label="Pendant la course">
  <h2>Pendant la course</h2>
  <ol class="phases">
    {#each guide.phases as p, i (i)}
      <li class="phase stack tight">
        <div class="row spread">
          <h3>{p.name}</h3>
          <span class="meta">km {km(p.start_km)} → {km(p.end_km)}{p.clock_end ? ` · vers ${p.clock_end}` : ""}</span>
        </div>
        {#if target(p)}<p class="target">{target(p)}</p>{/if}
        {#if p.terrain.length}
          <ul class="terrain">
            {#each p.terrain as t, j (j)}<li>{t}</li>{/each}
          </ul>
        {/if}
        <p class="advice">{p.advice}</p>
      </li>
    {/each}
  </ol>
</section>

{#if guide.splits.length}
  <section class="card lg stack" aria-label="Passages">
    <h2>Passages</h2>
    <table aria-label="Passages">
      <thead><tr><th>Borne</th><th>Temps</th><th>Heure</th></tr></thead>
      <tbody>
        {#each guide.splits as s, i (i)}
          <tr><td>{s.label}</td><td>{fmtClock(s.elapsed_s)}</td><td>{s.clock}</td></tr>
        {/each}
      </tbody>
    </table>
  </section>
{/if}

<section class="card lg stack" aria-label="Eau et nutrition">
  <h2>Eau et nutrition</h2>
  <p>{guide.nutrition.principle}</p>
  <p class="meta">
    Glucides {guide.nutrition.carbs_g_h} g/h · eau {fmtNumber(guide.nutrition.water_ml_h)} ml/h{guide.nutrition.recommended ? " (recommandé pour la durée prévue)" : ""}
  </p>
  {#if guide.nutrition.intakes.length}
    <ul class="intakes">
      {#each guide.nutrition.intakes as it, i (i)}
        <li><strong>km {km(it.km)}</strong>{it.clock ? ` · ${it.clock}` : ""} : {it.what}</li>
      {/each}
    </ul>
  {/if}
  {#if trail && plan.nutrition.length}
    <div class="scroll">
      <table aria-label="Nutrition">
        <thead>
          <tr><th>Tronçon</th><th>Km</th><th>Durée</th><th>Glucides</th><th>Eau</th><th>Alerte</th></tr>
        </thead>
        <tbody>
          {#each plan.nutrition as leg, i (i)}
            <tr>
              <td>{leg.from_name} → {leg.to_name}</td>
              <td>{km(leg.from_km)} → {km(leg.to_km)}</td>
              <td>{fmtDuration(leg.duration_s)}</td>
              <td>{fmtNumber(leg.carbs_g)} g</td>
              <td>{fmtNumber(leg.water_ml)} ml</td>
              <td>{#if leg.over_capacity}<span class="pill missed">Dépasse la contenance</span>{:else}—{/if}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<section class="card lg stack" aria-label="Préparation">
  <h2>Préparation</h2>
  <div class="prep">
    {#each guide.preparation as block (block.title)}
      <div class="stack tight">
        <h3>{block.title}</h3>
        {#if block.title === "Le matin"}
          <ul class="schedule">
            {#each guide.morning as m, i (i)}<li><strong>{m.clock}</strong> {m.label}</li>{/each}
          </ul>
        {/if}
        <ul>
          {#each block.items as item, i (i)}<li>{item}</li>{/each}
        </ul>
      </div>
    {/each}
  </div>
</section>

<style>
  h2, h3 { margin: 0; }
  h3 { font-size: 16px; }
  p { margin: 0; }
  .morning-box { border: 2px solid var(--accent); }
  .stats { display: flex; flex-wrap: wrap; gap: 16px 40px; }
  .big { font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .cues { display: grid; grid-template-columns: max-content 1fr; gap: 8px 16px; margin: 0; font-size: 16px; }
  .cues dt { font-weight: 700; }
  .cues dd { margin: 0; font-variant-numeric: tabular-nums; }
  .plain { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .plain .pill { margin-left: 6px; }
  .warnings { margin: 0; padding-left: 18px; color: var(--todo); }
  .phases { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 16px; }
  .phase { padding-left: 12px; border-left: 3px solid var(--accent-soft); }
  .target { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .terrain { margin: 0; padding-left: 18px; color: var(--text-2); }
  .advice { color: var(--text-2); }
  .intakes, .schedule { margin: 0; padding-left: 18px; font-variant-numeric: tabular-nums; }
  .prep { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }
  .prep ul { margin: 0; padding-left: 18px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--divider); white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: 13px; }
  @media (max-width: 520px) {
    .cues { grid-template-columns: 1fr; gap: 2px; }
    .cues dd { margin-bottom: 8px; }
  }
</style>
