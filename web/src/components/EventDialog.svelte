<script lang="ts">
  import { api, type EventInput, type EventKind, type Goal, type Session, type Week } from "../lib/api";
  import { addDays, formatDay, todayIso, WEEKDAYS } from "../lib/dates";
  import ErrorBanner from "./ErrorBanner.svelte";

  let {
    goal,
    weeks,
    sessions,
    today = todayIso(),
    onclose,
    onproposal,
  }: {
    goal: Goal;
    weeks: Week[];
    /** Séances proposées pour une fatigue : celles qui ne sont pas faites, cette semaine ou à venir. */
    sessions: Session[];
    today?: string;
    onclose?: () => void;
    onproposal?: (proposalId: number) => void;
  } = $props();

  const KINDS: { kind: EventKind; label: string }[] = [
    { kind: "unavailable", label: "Indisponible" },
    { kind: "injury", label: "Blessure / maladie" },
    { kind: "light_week", label: "Semaine allégée" },
    { kind: "fatigue", label: "Fatigue / séance ratée" },
  ];

  const cap = (d: string) => d.charAt(0).toUpperCase() + d.slice(1);
  // une semaine déjà terminée ne peut plus être allégée
  const futureWeeks = $derived(weeks.filter((w) => addDays(w.week_monday, 6) >= today));
  const goalDays = $derived(WEEKDAYS.filter((d) => (goal.available_days ?? WEEKDAYS).includes(d)));

  let kind = $state<EventKind | null>(null);
  let start = $state("");
  let end = $state("");
  let weekMonday = $state("");
  let maxSessions = $state<number | null>(null); // `bind:value` d'un champ numérique : nombre, ou null si vide
  let days = $state<string[]>([]);
  let sessionId = $state("");
  let note = $state("");
  let busy = $state(false);
  let error = $state<unknown>(null);
  // l'imprévu est enregistré mais Claude a échoué : on ne le recrée pas, on redemande l'ajustement
  let failure = $state<string | null>(null);

  function pick(k: EventKind) {
    kind = k;
    if (k === "unavailable" || k === "injury") start = today;
    if (k === "light_week") weekMonday = futureWeeks[0]?.week_monday ?? "";
  }

  const endBeforeStart = $derived(!!start && !!end && end < start);
  const maxInvalid = $derived(maxSessions == null || !Number.isInteger(maxSessions) || maxSessions < 0);
  const valid = $derived.by(() => {
    if (kind === "unavailable") return !!start && !!end && !endBeforeStart;
    if (kind === "injury") return !!start && !endBeforeStart;
    if (kind === "light_week") return !!weekMonday && !maxInvalid;
    return kind === "fatigue";
  });

  function body(): EventInput {
    const b: EventInput = { kind: kind! };
    if (kind === "unavailable") Object.assign(b, { start_date: start, end_date: end });
    if (kind === "injury") {
      b.start_date = start;
      // `end_date` est le dernier jour bloqué (inclus) : la veille de la reprise, sans passer avant le début
      if (end) b.end_date = addDays(end, -1) < start ? start : addDays(end, -1);
    }
    if (kind === "light_week") {
      Object.assign(b, { start_date: weekMonday, end_date: addDays(weekMonday, 6), max_sessions: maxSessions! });
      if (days.length) b.days = days;
    }
    if (kind === "fatigue" && sessionId) b.session_id = Number(sessionId);
    if (note.trim()) b.note = note.trim();
    return b;
  }

  async function submit() {
    busy = true;
    error = null;
    try {
      const r = await api.createEvent(goal.id, body());
      if (r.proposal_id != null) onproposal?.(r.proposal_id);
      else failure = r.error ?? "Claude n'a pas pu ajuster ton plan";
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }

  async function retry() {
    busy = true;
    error = null;
    try {
      const r = await api.requestAdjustment(goal.id);
      onproposal?.(r.proposal_id);
    } catch (e) {
      error = e;
    } finally {
      busy = false;
    }
  }

  function toggleDay(day: string, checked: boolean) {
    days = WEEKDAYS.filter((d) => (d === day ? checked : days.includes(d)));
  }
</script>

<div class="modal-backdrop">
  <div class="modal card stack" role="dialog" aria-label="Signaler un imprévu">
    <h2>Signaler un imprévu</h2>

    {#if failure}
      <p>Ton imprévu est enregistré, mais Claude n'a pas pu ajuster ton plan.</p>
      <p class="hint" role="alert">{failure}</p>
      {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
      <ErrorBanner {error} />
      <div class="row end">
        <button class="primary" onclick={retry} disabled={busy}>Réessayer</button>
        <button onclick={() => onclose?.()} disabled={busy}>Fermer</button>
      </div>
    {:else if kind == null}
      <div class="stack">
        {#each KINDS as k (k.kind)}
          <button onclick={() => pick(k.kind)}>{k.label}</button>
        {/each}
      </div>
      <div class="row end"><button onclick={() => onclose?.()}>Annuler</button></div>
    {:else}
      {#if kind === "unavailable" || kind === "injury"}
        <label>
          Début
          <input type="date" bind:value={start} required />
        </label>
        <label>
          {kind === "injury" ? "Reprise prévue (facultatif)" : "Fin"}
          <input type="date" bind:value={end} min={start || undefined} required={kind === "unavailable"} />
        </label>
        {#if endBeforeStart}<span class="hint" role="alert">La fin doit être après le début</span>{/if}
      {:else if kind === "light_week"}
        <label>
          Semaine
          <select bind:value={weekMonday}>
            {#each futureWeeks as w (w.week_index)}
              <option value={w.week_monday}>Semaine {w.week_index} — du {formatDay(w.week_monday)}</option>
            {/each}
          </select>
        </label>
        <label>
          Nombre de séances maximum
          <input type="number" min="0" step="1" bind:value={maxSessions} aria-invalid={maxSessions != null && maxInvalid} />
        </label>
        <fieldset>
          <legend>Jours possibles cette semaine-là (facultatif)</legend>
          <div class="chips" role="group" aria-label="Jours possibles cette semaine-là">
            {#each goalDays as d (d)}
              <label class="day">
                <input type="checkbox" checked={days.includes(d)} onchange={(e) => toggleDay(d, e.currentTarget.checked)} />
                <span>{cap(d)}</span>
              </label>
            {/each}
          </div>
        </fieldset>
      {:else}
        <label>
          Séance ratée (facultatif)
          <select bind:value={sessionId}>
            <option value="">Aucune</option>
            {#each sessions as s (s.id)}
              <option value={String(s.id)}>{s.title}</option>
            {/each}
          </select>
        </label>
      {/if}
      <label>
        Précisions (facultatif)
        <textarea rows="3" bind:value={note}></textarea>
      </label>
      {#if busy}<p class="meta" role="status">Claude ajuste ton plan… (cela peut prendre une minute)</p>{/if}
      <ErrorBanner {error} />
      <div class="row end">
        <button class="primary" onclick={submit} disabled={busy || !valid}>Envoyer</button>
        <button onclick={() => (kind = null)} disabled={busy}>Retour</button>
        <button onclick={() => onclose?.()} disabled={busy}>Annuler</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .day { flex-direction: row; align-items: center; gap: 6px; }
</style>
