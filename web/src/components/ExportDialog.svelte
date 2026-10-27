<script lang="ts">
  import { api, type Session } from "../lib/api";
  import { defaultExportDate, formatDay, weekDays } from "../lib/dates";

  let {
    session,
    weekMonday,
    mode = "export",
    onclose,
    ondone,
    onerror,
  }: {
    session: Session;
    weekMonday: string;
    mode?: "export" | "move";
    onclose?: () => void;
    ondone?: () => void;
    onerror?: (e: unknown) => void;
  } = $props();

  const days = $derived(weekDays(weekMonday));
  const preferred = () =>
    session.status !== "missed" && session.scheduled_date && weekDays(weekMonday).includes(session.scheduled_date)
      ? session.scheduled_date
      : defaultExportDate(weekMonday, session.suggested_day);

  let date = $state(preferred());
  let warnings = $state<string[]>([]);
  let busy = $state(false);
  let checkSeq = 0;

  // vérification à chaque changement de date ; les avertissements ne bloquent jamais
  $effect(() => {
    const d = date;
    const seq = ++checkSeq;
    api
      .exportCheck(session.id, d)
      .then((r) => {
        if (seq === checkSeq) warnings = r.warnings;
      })
      .catch((e) => {
        if (seq === checkSeq) onerror?.(e);
      });
  });

  async function submit() {
    busy = true;
    try {
      if (mode === "move") await api.moveSession(session.id, date);
      else await api.exportSession(session.id, date);
      ondone?.();
    } catch (e) {
      onerror?.(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="modal-backdrop">
  <div class="modal card" role="dialog" aria-label={mode === "move" ? "Déplacer la séance" : "Exporter la séance"}>
    <h3>{mode === "move" ? "Déplacer" : "Exporter"} « {session.title} »</h3>
    <label>
      Jour
      <select bind:value={date}>
        {#each days as d}
          <option value={d}>{formatDay(d)}</option>
        {/each}
      </select>
    </label>
    {#each warnings as w}
      <p class="warning" role="status">{w}</p>
    {/each}
    <div class="row">
      <button class="primary" onclick={submit} disabled={busy}>{mode === "move" ? "Déplacer" : "Exporter"}</button>
      <button onclick={() => onclose?.()}>Annuler</button>
    </div>
  </div>
</div>
