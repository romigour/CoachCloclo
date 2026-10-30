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
    top: calc(var(--topbar-h) + env(safe-area-inset-top));
    z-index: 4;
    background: var(--bg);
    padding: 0.5rem 0 0.6rem;
    border-bottom: 1px solid var(--border);
  }
  .periods {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 3px;
    gap: 3px;
  }
  .periods button {
    min-height: 38px;
    padding: 0.35rem 0.25rem;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: var(--muted);
    font-size: 0.85rem;
    line-height: 1.15;
  }
  .periods button.on {
    background: var(--accent);
    color: var(--accent-text);
    font-weight: 600;
  }
  .line {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.5rem;
    margin-top: 0.5rem;
  }
  .field {
    margin: 0;
    flex: 1 1 9rem;
    min-width: 0;
    font-size: 0.8rem;
  }
  .field select,
  .field input {
    margin-top: 0.15rem;
    padding: 0.45rem 0.6rem;
    background: var(--card);
    min-height: 40px;
  }
  .reset {
    min-height: 40px;
    padding: 0.4rem 0.8rem;
    font-size: 0.85rem;
  }
  @media (min-width: 640px) {
    .periods button { font-size: 0.95rem; }
  }
</style>
