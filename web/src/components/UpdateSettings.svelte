<script lang="ts">
  import { onMount } from "svelte";
  import { api, type UpdateView } from "../lib/api";
  import { installAndWait } from "../lib/update";

  let view = $state<UpdateView | null>(null); // reste null sous `coach start` : le bloc est masqué
  let checking = $state(false);
  let message = $state("");
  let phase = $state<"idle" | "downloading" | "installing" | "stuck">("idle");
  let progress = $state(0);

  onMount(async () => {
    try {
      view = await api.update();
    } catch {
      view = null;
    }
  });

  async function check() {
    checking = true;
    message = "";
    try {
      view = await api.checkUpdate();
      if (!view.available) message = "CoachCloclo est à jour";
    } catch (e) {
      message = e instanceof Error ? e.message : "Vérification impossible";
    } finally {
      checking = false;
    }
  }

  async function install() {
    if (!view) return;
    phase = "downloading";
    progress = 0;
    message = "";
    try {
      const result = await installAndWait(view.current, (v) => {
        progress = v.progress;
        if (v.state === "installing") phase = "installing";
        if (v.state === "failed") message = v.error ?? "La mise à jour a échoué";
      });
      if (result === "restarted") location.reload();
      else phase = result === "stuck" ? "stuck" : "idle";
    } catch (e) {
      message = e instanceof Error ? e.message : "La mise à jour a échoué";
      phase = "idle";
    }
  }
</script>

{#if view}
  <section class="card stack">
    <h2>Mise à jour</h2>
    <p>Version installée : {view.current}</p>
    {#if phase === "downloading"}
      <p class="busy" role="status">Téléchargement… {Math.round(progress)} %</p>
    {:else if phase === "installing"}
      <p class="busy" role="status">Mise à jour en cours, CoachCloclo va redémarrer…</p>
    {:else if phase === "stuck"}
      <p class="warning" role="status">La mise à jour semble bloquée : relance CoachCloclo depuis l'icône du bureau</p>
    {:else}
      <div class="row">
        <button type="button" onclick={check} disabled={checking}>Vérifier les mises à jour</button>
        {#if view.available}
          <button type="button" onclick={install}>Mettre à jour</button>
        {/if}
      </div>
      {#if view.available}<p>Version {view.latest} disponible</p>{/if}
      {#if message}<p role="status">{message}</p>{/if}
    {/if}
  </section>
{/if}
