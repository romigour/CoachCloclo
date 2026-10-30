<script lang="ts">
  import type { Period, PeriodChoice, SportFilter } from "../../lib/stats/filter";
  import { SPORT_LABEL } from "../../lib/labels";

  let {
    choice,
    sport,
    options,
    years,
    period,
    onchange,
    onreset,
  }: {
    choice: PeriodChoice;
    sport: SportFilter;
    options: SportFilter[];
    years: number[];
    /** Période résolue : sert à pré-remplir les dates personnalisées. */
    period: Period;
    onchange: (choice: PeriodChoice, sport: SportFilter) => void;
    onreset: () => void;
  } = $props();

  const KINDS: { kind: PeriodChoice["kind"]; label: string }[] = [
    { kind: "12m", label: "12 derniers mois" },
    { kind: "year", label: "Année" },
    { kind: "all", label: "Tout" },
    { kind: "custom", label: "Personnalisée" },
  ];

  // Le sport mémorisé reste sélectionnable même s'il n'apparaît plus dans les données.
  const sports = $derived(options.includes(sport) ? options : [...options, sport]);
  const yearList = $derived(choice.kind === "year" && !years.includes(choice.year) ? [choice.year, ...years] : years);
  const isDefault = $derived(choice.kind === "12m" && sport === "all");

  function pick(kind: PeriodChoice["kind"]) {
    if (kind === choice.kind) return;
    if (kind === "year") onchange({ kind, year: years[0] ?? Number(period.to.slice(0, 4)) }, sport);
    else if (kind === "custom") onchange({ kind, from: period.from, to: period.to }, sport);
    else onchange({ kind }, sport);
  }

  function setDate(which: "from" | "to", value: string) {
    if (choice.kind !== "custom" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return;
    const next = { ...choice, [which]: value };
    if (next.from <= next.to) onchange(next, sport);
  }
</script>

<div class="filters">
  <div class="periods" role="group" aria-label="Période">
    {#each KINDS as k (k.kind)}
      <button type="button" class:on={choice.kind === k.kind} aria-pressed={choice.kind === k.kind} onclick={() => pick(k.kind)}>
        {k.label}
      </button>
    {/each}
  </div>

  <div class="line">
    {#if choice.kind === "year"}
      <label class="field">
        <span>Année</span>
        <select value={String(choice.year)} onchange={(e) => onchange({ kind: "year", year: Number(e.currentTarget.value) }, sport)}>
          {#each yearList as y (y)}<option value={String(y)}>{y}</option>{/each}
        </select>
      </label>
    {:else if choice.kind === "custom"}
      <label class="field">
        <span>Du</span>
        <input type="date" value={choice.from} max={choice.to} onchange={(e) => setDate("from", e.currentTarget.value)} />
      </label>
      <label class="field">
        <span>Au</span>
        <input type="date" value={choice.to} min={choice.from} onchange={(e) => setDate("to", e.currentTarget.value)} />
      </label>
    {/if}

    <label class="field">
      <span>Sport</span>
      <select value={sport} onchange={(e) => onchange(choice, e.currentTarget.value as SportFilter)}>
        {#each sports as s (s)}<option value={s}>{SPORT_LABEL[s]}</option>{/each}
      </select>
    </label>

    <button type="button" class="reset" disabled={isDefault} onclick={onreset}>Réinitialiser</button>
  </div>
</div>

<style>
  .filters {
    position: sticky;
    top: 0;
    z-index: 4;
    background: var(--bg);
    padding: 8px 0 12px;
    margin-top: -8px;
    border-bottom: 1px solid var(--border);
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 12px 16px;
  }
  /* même rendu que le sélecteur segmenté de la refonte (.segmented) */
  .periods {
    display: inline-grid;
    grid-template-columns: repeat(4, auto);
    background: var(--sunken);
    border-radius: 12px;
    padding: 4px;
    gap: 2px;
  }
  .periods button {
    min-height: 38px;
    padding: 0 12px;
    border: none;
    border-radius: 9px;
    background: transparent;
    color: var(--text-2);
    font-weight: 500;
    line-height: 1.15;
  }
  .periods button:hover:not(.on) { background: transparent; color: var(--text); }
  .periods button.on {
    background: var(--surface);
    color: var(--text);
    font-weight: 700;
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.08);
  }
  .line {
    flex: 1 1 320px;
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 10px;
  }
  .field {
    flex: 1 1 140px;
    max-width: 240px;
    min-width: 0;
    gap: 4px;
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
  }
  .field select,
  .field input { min-height: 40px; }
  .reset { min-height: 40px; font-weight: 500; }
  @media (max-width: 640px) {
    .periods { display: grid; width: 100%; grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .periods button { padding: 0 4px; font-size: 13px; }
  }
</style>
