<script lang="ts">
  import { onMount } from "svelte";
  import { api, type DiagnosticsView } from "../lib/api";

  let view = $state<DiagnosticsView | null>(null); // reste null si la lecture échoue : la carte est masquée
  let error = $state("");
  let busy = $state(false);

  onMount(async () => {
    try {
      view = await api.diagnostics();
    } catch {
      view = null;
    }
  });

  async function toggle(key: "trace_claude" | "trace_garmin", value: boolean) {
    if (!view || busy) return;
    busy = true;
    error = "";
    try {
      view = await api.saveDiagnostics({ [key]: value });
    } catch (e) {
      error = e instanceof Error ? e.message : "Enregistrement impossible";
    } finally {
      busy = false;
    }
  }

  async function openFolder() {
    error = "";
    try {
      await api.openLogs();
    } catch (e) {
      error = e instanceof Error ? e.message : "Ouverture impossible";
    }
  }
</script>

{#if view}
  <section class="card stack">
    <h2>Diagnostic</h2>
    <p>Enregistre le détail des échanges pour comprendre un échec. Les mots de passe et clés sont masqués.</p>
    <label class="inline">
      <input
        type="checkbox"
        checked={view.trace_claude}
        disabled={busy}
        onclick={(e) => {
          e.preventDefault();
          toggle("trace_claude", !view!.trace_claude);
        }}
      />
      Journal Claude
    </label>
    <label class="inline">
      <input
        type="checkbox"
        checked={view.trace_garmin}
        disabled={busy}
        onclick={(e) => {
          e.preventDefault();
          toggle("trace_garmin", !view!.trace_garmin);
        }}
      />
      Journal Garmin
    </label>
    <p class="meta">Dossier des journaux : <code>{view.logs_dir}</code></p>
    {#if view.can_open}
      <div class="row">
        <button type="button" onclick={openFolder}>Ouvrir le dossier des journaux</button>
      </div>
    {/if}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
  </section>
{/if}
