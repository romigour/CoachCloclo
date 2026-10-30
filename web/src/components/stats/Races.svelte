<script lang="ts">
  import EChart from "./EChart.svelte";
  import RaceEditDialog from "./RaceEditDialog.svelte";
  import type { StatActivity } from "../../lib/api";
  import { raceCandidates, type DistanceCategory, type RaceRow } from "../../lib/stats/races";
  import { themeColors } from "../../lib/stats/echarts";
  import { fmtClock, fmtDay, fmtMonthTick, fmtNumber, fmtPace } from "../../lib/stats/format";
  import { tooltipTheme, withAlpha } from "../../lib/stats/color";
  import { CATEGORY_LABEL, FAMILY_LABEL } from "../../lib/labels";

  type Progression = { category: DistanceCategory; points: { date: string; timeS: number }[] }[];

  let {
    acts,
    rows,
    progression,
    onchanged,
  }: {
    /** Toutes les activités (liste d'ajout, indépendante des filtres). */
    acts: StatActivity[];
    rows: RaceRow[];
    progression: Progression;
    onchanged: (row: StatActivity) => void;
  } = $props();

  const PICK_LIMIT = 60;

  let editing = $state<StatActivity | null>(null);
  let picking = $state(false);
  let query = $state("");

  const candidates = $derived(picking ? raceCandidates(acts, query) : []);

  function raceName(a: StatActivity): string {
    return a.race?.name ?? a.name ?? `Course du ${fmtDay(a.date)}`;
  }

  function pick(a: StatActivity) {
    picking = false;
    query = "";
    editing = a;
  }

  function saved(a: StatActivity) {
    editing = null;
    onchanged(a);
  }

  function pickerKey(e: KeyboardEvent) {
    if (e.key === "Escape" && picking) picking = false;
  }

  /** Une courbe par catégorie de distance (échelles trop différentes pour un seul graphique). */
  const charts = $derived.by(() => {
    const c = themeColors();
    return progression.map((p) => ({
      category: p.category,
      option: {
        grid: { top: 10, left: 4, right: 12, bottom: 4, containLabel: true },
        tooltip: {
          ...tooltipTheme(c),
          trigger: "item",
          formatter: (it: { dataIndex: number }) => {
            const pt = p.points[it.dataIndex];
            return pt ? `<b>${fmtDay(pt.date)}</b><br/>${CATEGORY_LABEL[p.category]} : <b>${fmtClock(pt.timeS)}</b>` : "";
          },
        },
        xAxis: {
          type: "time",
          axisLabel: {
            color: c.muted,
            hideOverlap: true,
            formatter: fmtMonthTick,
          },
          axisLine: { lineStyle: { color: c.border } },
          axisTick: { show: false },
          splitLine: { show: false },
        },
        yAxis: {
          type: "value",
          scale: true,
          inverse: true, // plus haut = plus rapide
          axisLabel: { color: c.muted, formatter: (v: number) => fmtClock(v) },
          splitLine: { lineStyle: { color: c.border, type: "dashed" } },
        },
        series: [
          {
            type: "line",
            name: CATEGORY_LABEL[p.category],
            data: p.points.map((pt) => [pt.date, pt.timeS]),
            symbolSize: 8,
            lineStyle: { color: c.accent, width: 2 },
            itemStyle: { color: c.accent },
            areaStyle: { color: withAlpha(c.accent, 0.1), origin: "end" },
          },
        ],
      },
    }));
  });
</script>

<svelte:window onkeydown={pickerKey} />

<div class="head">
  <button type="button" class="small" onclick={() => (picking = true)}>Ajouter une compétition</button>
</div>

{#if rows.length === 0}
  <p class="empty">Aucune compétition sur cette période</p>
{:else}
  <ul class="races">
    {#each rows as r (r.activity.id)}
      {@const race = r.activity.race}
      <li>
        <div class="top">
          <span class="date">{fmtDay(r.activity.date)}</span>
          <strong class="name">{raceName(r.activity)}</strong>
          <button type="button" class="small" onclick={() => (editing = r.activity)} aria-label="Modifier {raceName(r.activity)}">Modifier</button>
        </div>
        <div class="facts">
          {#if r.timeS !== null}
            <span class="time">{fmtClock(r.timeS)}</span>
            {#if !r.official}<span class="watch" title="Temps officiel non saisi : temps de la montre">montre</span>{/if}
          {/if}
          {#if r.paceSKm !== null}<span class="meta">{fmtPace(r.paceSKm)}</span>{/if}
          {#if r.activity.distance_m}
            <span class="meta">{fmtNumber(r.activity.distance_m / 1000, 1)} km{r.activity.family === "trail" ? ` · ${FAMILY_LABEL.trail}` : ""}</span>
          {/if}
        </div>
        {#if race && (race.overall_rank != null || race.category_rank != null)}
          <div class="ranks">
            {#if race.overall_rank != null}
              <span>
                {race.overall_rank}{race.overall_total != null ? ` / ${race.overall_total}` : ""} au général
                {#if r.overallTop !== null}<span class="top-pct">Top {r.overallTop} %</span>{/if}
              </span>
            {/if}
            {#if race.category_rank != null}
              <span>
                {race.category_rank}{race.category_total != null ? ` / ${race.category_total}` : ""} en {race.category ?? "catégorie"}
                {#if r.categoryTop !== null}<span class="top-pct">Top {r.categoryTop} %</span>{/if}
              </span>
            {/if}
          </div>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

{#if charts.length}
  <h3>Progression</h3>
  <div class="charts">
    {#each charts as ch (ch.category)}
      <div class="chart">
        <span class="cat">{CATEGORY_LABEL[ch.category]}</span>
        <EChart option={ch.option} height="160px" label="Progression des temps sur {CATEGORY_LABEL[ch.category]}" />
      </div>
    {/each}
  </div>
  <p class="hint">Plus haut = plus rapide. Distances comparées à ±3 % ; le trail n'est pas comparé.</p>
{/if}

{#if picking}
  <div class="modal-backdrop">
    <div class="modal card picker" role="dialog" aria-modal="true" aria-label="Ajouter une compétition">
      <h3>Ajouter une compétition</h3>
      <label>
        Rechercher
        <input type="search" bind:value={query} placeholder="Nom ou date (2026, 11/05/2026, mai…)" autocomplete="off" />
      </label>
      {#if candidates.length === 0}
        <p class="empty">Aucune sortie course ou trail ne correspond</p>
      {:else}
        <ul class="candidates">
          {#each candidates.slice(0, PICK_LIMIT) as a (a.id)}
            <li>
              <button type="button" onclick={() => pick(a)}>
                <span class="c-name">{a.name ?? "Sans nom"}</span>
                <span class="meta">
                  {fmtDay(a.date)}{a.distance_m ? ` · ${fmtNumber(a.distance_m / 1000, 1)} km` : ""}{a.family === "trail" ? " · Trail" : ""}{a.race ? " · déjà marquée" : ""}
                </span>
              </button>
            </li>
          {/each}
        </ul>
        {#if candidates.length > PICK_LIMIT}
          <p class="meta">{candidates.length - PICK_LIMIT} autres sorties : affine la recherche.</p>
        {/if}
      {/if}
      <div class="row">
        <button type="button" onclick={() => (picking = false)}>Fermer</button>
      </div>
    </div>
  </div>
{/if}

{#if editing}
  <RaceEditDialog activity={editing} onsaved={saved} onclose={() => (editing = null)} />
{/if}

<style>
  .head { display: flex; justify-content: flex-end; margin-top: -4px; }
  .races { list-style: none; margin: 0; padding: 0; }
  .races li { padding: 12px 0; border-bottom: 1px solid var(--divider); }
  .races li:last-child { border-bottom: none; }
  .top { display: flex; align-items: baseline; gap: 0.5rem; min-width: 0; }
  .date { color: var(--muted); font-size: 12px; white-space: nowrap; }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .top :global(button.small) { flex: none; }
  .facts { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.2rem 0.8rem; margin-top: 0.2rem; }
  .time { font-family: var(--font-display); font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .watch {
    margin-left: -0.5rem;
    font-size: 11px;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0 0.3rem;
  }
  .ranks { display: flex; flex-wrap: wrap; gap: 0.2rem 1rem; margin-top: 0.2rem; font-size: 13px; }
  .top-pct {
    margin-left: 0.3rem;
    padding: 0.05rem 0.4rem;
    border-radius: 999px;
    background: var(--accent-soft);
    color: var(--accent-strong);
    font-weight: 600;
    font-size: 12px;
    white-space: nowrap;
  }
  h3 { margin-top: 4px; font-size: 15px; }
  .picker h3 { margin-top: 0; }
  .charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.8rem; }
  .chart { min-width: 0; }
  .cat { font-size: 12px; color: var(--muted); font-weight: 600; }
  .hint { color: var(--muted); font-size: 12px; margin: 0.3rem 0 0; }
  .picker { display: flex; flex-direction: column; max-height: 85vh; }
  .candidates { list-style: none; margin: 0; padding: 0; overflow-y: auto; min-height: 0; }
  .candidates button {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.1rem;
    text-align: left;
    border: none;
    border-bottom: 1px solid var(--divider);
    border-radius: 0;
    background: transparent;
  }
  .candidates button:hover { background: var(--sunken); }
  .c-name { font-weight: 600; }
</style>
