<script lang="ts">
  import type { PersonalRecord } from "../../lib/api";
  import { recordRows } from "../../lib/stats/records";
  import { fmtClock, fmtDay, fmtNumber, fmtPace } from "../../lib/stats/format";

  /** null pendant le chargement ; [] si la liste est vide ou la requête a échoué. */
  let { records }: { records: PersonalRecord[] | null } = $props();

  const rows = $derived(records ? recordRows(records) : []);
</script>

<p class="meta note">Records absolus, non filtrés par période</p>

{#if records === null}
  <p class="meta loading">Chargement des records…</p>
{:else if rows.length === 0}
  <p class="empty">Records indisponibles</p>
{:else}
  <div class="scroll">
    <table>
      <thead>
        <tr>
          <th scope="col">Distance</th>
          <th scope="col" class="num">Temps</th>
          <th scope="col" class="num">Allure</th>
          <th scope="col">Date</th>
        </tr>
      </thead>
      <tbody>
        {#each rows as r (r.kind)}
          <tr>
            <th scope="row">
              {#if r.url}
                <a href={r.url} target="_blank" rel="noopener" title="Voir l'activité sur Garmin Connect">{r.label}<span class="ext" aria-hidden="true">↗</span></a>
              {:else}
                {r.label}
              {/if}
            </th>
            {#if r.timeS !== null}
              <td class="num strong">{fmtClock(r.timeS)}</td>
              <td class="num">{r.paceSKm !== null ? fmtPace(r.paceSKm) : "—"}</td>
            {:else}
              <td class="num strong">{fmtNumber(r.distanceKm ?? 0, 1)} km</td>
              <td class="num muted">—</td>
            {/if}
            <td class="muted">{r.date ? fmtDay(r.date) : "—"}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .loading { text-align: center; padding: 1.5rem 0.5rem; margin: 0; }
  .note { margin: -0.3rem 0 0.5rem; font-size: 0.8rem; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th, td { padding: 0.45rem 0.4rem; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--border); }
  thead th { color: var(--muted); font-weight: 500; font-size: 0.8rem; }
  tbody tr:last-child th, tbody tr:last-child td { border-bottom: none; }
  tbody th { font-weight: 600; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .strong { font-weight: 600; }
  .muted { color: var(--muted); }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .ext { font-size: 0.75em; margin-left: 0.2rem; }
</style>
