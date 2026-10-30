<script lang="ts">
  import { api, type StatActivity } from "../../lib/api";
  import { fmtClock, fmtDay, fmtNumber, parseClock } from "../../lib/stats/format";
  import ErrorBanner from "../ErrorBanner.svelte";

  let {
    activity,
    onsaved,
    onclose,
  }: { activity: StatActivity; onsaved: (a: StatActivity) => void; onclose: () => void } = $props();

  // Copie locale du formulaire (valeurs initiales seulement) : la ligne de la page
  // n'est remplacée qu'après succès de l'API.
  const initial = () => ({ race: activity.race, name: activity.name });
  const { race, name: activityName } = initial();
  let name = $state(race?.name ?? activityName ?? "");
  let time = $state(race?.official_time_s != null ? fmtClock(race.official_time_s) : "");
  let overallRank = $state<number | null>(race?.overall_rank ?? null);
  let overallTotal = $state<number | null>(race?.overall_total ?? null);
  let category = $state(race?.category ?? "");
  let categoryRank = $state<number | null>(race?.category_rank ?? null);
  let categoryTotal = $state<number | null>(race?.category_total ?? null);
  let error = $state<unknown>(null);
  let busy = $state(false);

  /** Champ numérique vide (null / undefined / NaN) → null. */
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const text = (v: string) => (v.trim() ? v.trim() : null);

  const title = $derived(activity.name ?? `Sortie du ${fmtDay(activity.date)}`);
  const facts = $derived(
    [
      fmtDay(activity.date),
      activity.distance_m ? `${fmtNumber(activity.distance_m / 1000, 1)} km` : null,
      activity.duration_s ? `montre ${fmtClock(activity.duration_s)}` : null,
    ]
      .filter(Boolean)
      .join(" · "),
  );

  async function save(e: Event) {
    e.preventDefault();
    const official = parseClock(time);
    if (Number.isNaN(official)) {
      error = new Error("Temps officiel : format h:mm:ss attendu (par exemple 0:41:30)");
      return;
    }
    busy = true;
    error = null;
    try {
      const saved = await api.saveRace(activity.id, {
        name: text(name),
        official_time_s: official,
        overall_rank: num(overallRank),
        overall_total: num(overallTotal),
        category: text(category),
        category_rank: num(categoryRank),
        category_total: num(categoryTotal),
      });
      onsaved(saved);
    } catch (err) {
      error = err;
    } finally {
      busy = false;
    }
  }

  async function remove() {
    busy = true;
    error = null;
    try {
      await api.removeRace(activity.id);
      onsaved({ ...activity, race: null });
    } catch (err) {
      error = err;
    } finally {
      busy = false;
    }
  }

  function keydown(e: KeyboardEvent) {
    if (e.key === "Escape" && !busy) onclose();
  }
</script>

<svelte:window onkeydown={keydown} />

<div class="modal-backdrop">
  <div class="modal card" role="dialog" aria-modal="true" aria-label="Compétition — {title}">
    <form onsubmit={save}>
      <h3>{title}</h3>
      <p class="meta facts">{facts}</p>

      <label>
        Épreuve
        <input type="text" bind:value={name} maxlength="120" placeholder="10 km de Rennes" />
      </label>
      <label>
        Temps officiel <span class="hint">(h:mm:ss, vide = temps montre)</span>
        <input type="text" bind:value={time} inputmode="numeric" placeholder="0:41:30" autocomplete="off" />
      </label>
      <div class="pair">
        <label>
          Classement général
          <input type="number" min="1" step="1" inputmode="numeric" bind:value={overallRank} />
        </label>
        <label>
          Participants
          <input type="number" min="1" step="1" inputmode="numeric" bind:value={overallTotal} />
        </label>
      </div>
      <label>
        Catégorie
        <input type="text" bind:value={category} maxlength="40" placeholder="SEH, M0H…" />
      </label>
      <div class="pair">
        <label>
          Classement catégorie
          <input type="number" min="1" step="1" inputmode="numeric" bind:value={categoryRank} />
        </label>
        <label>
          Effectif
          <input type="number" min="1" step="1" inputmode="numeric" bind:value={categoryTotal} />
        </label>
      </div>

      <ErrorBanner {error} />

      <div class="row">
        <button type="submit" class="primary" disabled={busy}>Enregistrer</button>
        <button type="button" onclick={onclose} disabled={busy}>Annuler</button>
        <button type="button" class="danger" onclick={remove} disabled={busy}>Ce n'est pas une compétition</button>
      </div>
    </form>
  </div>
</div>

<style>
  .modal { max-height: 92vh; overflow-y: auto; }
  h3 { margin: 0; }
  .facts { margin: 0.2rem 0 0.4rem; }
  .hint { font-size: 0.75rem; }
  .pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 0.75rem; }
  .danger { color: var(--error); margin-left: auto; }
</style>
