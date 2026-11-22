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
  <div class="set-list">
    <div class="set-row">
      <div class="set-label"><label for="trace-claude">Journal Claude</label></div>
      <div class="set-ctl">
        <input
          id="trace-claude"
          type="checkbox"
          role="switch"
          class="switch"
          checked={view.trace_claude}
          disabled={busy}
          onclick={(e) => {
            e.preventDefault();
            toggle("trace_claude", !view!.trace_claude);
          }}
        />
      </div>
    </div>
    <div class="set-row">
      <div class="set-label"><label for="trace-garmin">Journal Garmin</label></div>
      <div class="set-ctl">
        <input
          id="trace-garmin"
          type="checkbox"
          role="switch"
          class="switch"
          checked={view.trace_garmin}
          disabled={busy}
          onclick={(e) => {
            e.preventDefault();
            toggle("trace_garmin", !view!.trace_garmin);
          }}
        />
      </div>
    </div>
    <div class="set-row">
      <div class="set-label">
        <h3>Dossier des journaux</h3>
        <p><code>{view.logs_dir}</code></p>
        {#if error}<p class="error" role="alert">{error}</p>{/if}
      </div>
      {#if view.can_open}
        <div class="set-ctl">
          <button type="button" onclick={openFolder}>Ouvrir le dossier des journaux</button>
        </div>
      {/if}
    </div>
  </div>
{/if}
