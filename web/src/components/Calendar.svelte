<script lang="ts">
  import type { Goal, Week } from "../lib/api";
  import { STATUS_LABEL } from "../lib/labels";
  import { formatDuration, peakLevel, totalSeconds } from "../lib/profile";
  import { days } from "../lib/week";
  import RaceDayCard from "./RaceDayCard.svelte";

  let {
    weeks,
    today,
    selected = null,
    readonly = false,
    races = [],
    onselect,
  }: {
    weeks: Week[];
    /** Objectifs du cycle : une carte « Course » le jour de chacun. */
    races?: Goal[];
    today: string;
    selected?: number | null;
    readonly?: boolean;
    onselect?: (id: number) => void;
  } = $props();

  const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  const short = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;

  // amène la semaine en cours à l'écran au premier affichage
  let grid = $state<HTMLElement | null>(null);
  $effect(() => {
    grid?.querySelector(".cal-row.current")?.scrollIntoView?.({ block: "center" });
  });

  function volume(w: Week): string {
    const secs = w.sessions.map((s) => totalSeconds(s.steps));
    return secs.every((s) => s != null) ? formatDuration(secs.reduce<number>((a, b) => a + (b ?? 0), 0)) : "";
  }
</script>

<div class="card calendar">
  <div class="calendar-grid" role="table" bind:this={grid} aria-label="Calendrier du programme">
    <div class="cal-row head" role="row">
      <span role="columnheader">Semaine</span>
      {#each ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."] as d}<span role="columnheader">{d}</span>{/each}
    </div>
    {#each weeks as w (w.week_index)}
      <div class="cal-row" class:current={days(w).some((d) => d.date === today)} role="row">
        <div class="cal-week" role="rowheader">
          <strong>S{w.week_index}</strong>
          <span>{short(w.week_monday)}</span>
          {#if volume(w)}<span>{volume(w)}</span>{/if}
        </div>
        {#each days(w) as d (d.date)}
          <div class="cal-cell" role="cell">
            {#each races.filter((g) => g.race_date === d.date) as g (g.id)}<RaceDayCard goal={g} />{/each}
            {#each d.sessions as s (s.id)}
              <button
                class="cal-session {s.status}"
                class:selected={selected === s.id}
                class:today={d.date === today}
                aria-pressed={selected === s.id}
                onclick={() => onselect?.(s.id)}
              >
                <span class="t">{s.title}</span>
                {#if totalSeconds(s.steps)}<span class="meta">{formatDuration(totalSeconds(s.steps)!)}</span>{/if}
                <span class="s {readonly ? '' : s.status}">
                  <span class="zone-bar lv{peakLevel(s.steps)}"></span>
                  {#if !readonly}{STATUS_LABEL[s.status]}{/if}
                </span>
              </button>
            {/each}
          </div>
        {/each}
      </div>
    {/each}
  </div>
</div>
