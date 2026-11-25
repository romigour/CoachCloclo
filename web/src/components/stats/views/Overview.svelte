<script lang="ts">
  import ConsistencyCalendar from "../ConsistencyCalendar.svelte";
  import Insight from "../Insight.svelte";
  import KpiRow from "../KpiRow.svelte";
  import type { WeekStats } from "../../../lib/stats/consistency";
  import type { Period } from "../../../lib/stats/filter";
  import { regularityText, volumeText } from "../../../lib/stats/insights";
  import type { Kpi } from "../../../lib/stats/kpis";
  import { TABS, type StatsTab } from "../../../lib/stats/tabs";

  let {
    kpis,
    days,
    period,
    weeks,
    notes,
    onpick,
  }: {
    kpis: Kpi[];
    days: [string, number][];
    period: Period;
    weeks: WeekStats;
    notes: { tab: StatsTab; text: string }[];
    onpick: (p: Period) => void;
  } = $props();

  const tabOf = (key: StatsTab) => TABS.find((t) => t.key === key)!;
</script>

<section aria-labelledby="kpi-title">
  <h2 id="kpi-title" class="sr-only">Chiffres clés</h2>
  <KpiRow {kpis} />
  <Insight text={volumeText(kpis.find((k) => k.key === "hours")?.delta ?? null)} />
</section>

{#if notes.length > 0}
  <section class="card stack" aria-labelledby="notes-title">
    <h2 id="notes-title">En bref</h2>
    <ul class="notes" aria-label="Constats">
      {#each notes as n (n.tab)}
        <li>
          <a href={tabOf(n.tab).hash}>
            <span class="label">{tabOf(n.tab).label}</span>
            <span>{n.text}</span>
          </a>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<section class="card stack" aria-labelledby="reg-title">
  <div><h2 id="reg-title">Régularité</h2><p class="meta">Suis-je constant ?</p></div>
  <ConsistencyCalendar {days} {period} stats={weeks} {onpick} />
  <Insight text={regularityText(weeks)} />
</section>

<style>
  .notes {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
  }
  @media (min-width: 700px) {
    .notes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  a {
    display: flex;
    flex-direction: column;
    gap: 2px;
    height: 100%;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text);
    text-decoration: none;
  }
  a:hover { background: var(--sunken); }
  .label { color: var(--muted); font-size: 12px; font-weight: 600; }
</style>
