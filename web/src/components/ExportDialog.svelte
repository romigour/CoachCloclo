<script lang="ts">
  import { api, type Session } from "../lib/api";
  import { defaultExportDate, formatDay, todayIso, weekDays } from "../lib/dates";

  let {
    session,
    weekMonday,
    mode = "export",
    today = todayIso(),
    onclose,
    ondone,
    onerror,
  }: {
    session: Session;
    weekMonday: string;
    mode?: "export" | "move";
    today?: string;
    onclose?: () => void;
    ondone?: () => void;
    onerror?: (e: unknown) => void;
  } = $props();

  // jamais de date passée : le backend la refuserait
  const available = () => weekDays(weekMonday).filter((d) => d >= today);
  const days = $derived(available());
  const preferred = () => {
    const d =
      session.status !== "missed" && session.scheduled_date && weekDays(weekMonday).includes(session.scheduled_date)
        ? session.scheduled_date
        : defaultExportDate(weekMonday, session.suggested_day);
    return available().includes(d) ? d : (available()[0] ?? d);
  };

  let date = $state(preferred());
  let warnings = $state<string[]>([]);
  let busy = $state(false);
  let checkSeq = 0;

  // vérification à chaque changement de date ; les avertissements ne bloquent jamais
  $effect(() => {
    const d = date;
    if (!days.length) return;
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
    {#if days.length}
      <label>
        Jour
        <select bind:value={date}>
          {#each days as d}
            <option value={d}>{formatDay(d)}</option>
          {/each}
        </select>
      </label>
    {:else}
      <p class="warning" role="status">Cette semaine est passée : aucun jour disponible.</p>
    {/if}
    {#each warnings as w}
      <p class="warning" role="status">{w}</p>
    {/each}
    <div class="row">
      <button class="primary" onclick={submit} disabled={busy || !days.length}>{mode === "move" ? "Déplacer" : "Exporter"}</button>
      <button onclick={() => onclose?.()}>Annuler</button>
    </div>
  </div>
</div>
