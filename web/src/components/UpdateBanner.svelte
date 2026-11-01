<script lang="ts">
  import { onMount } from "svelte";
  import { api, type UpdateView } from "../lib/api";
  import { installAndWait } from "../lib/update";

  const KEY = "coach.updateDismissed";

  let view = $state<UpdateView | null>(null);
  let dismissed = $state(readDismissed());
  let phase = $state<"idle" | "downloading" | "installing" | "stuck" | "failed">("idle");
  let progress = $state(0);
  let failure = $state("");

  function readDismissed(): string | null {
    try {
      return localStorage.getItem(KEY);
    } catch {
      return null;
    }
  }

  async function load() {
    try {
      view = await api.update();
    } catch {
      // pas de bandeau si la lecture échoue
    }
  }

  onMount(() => {
    load();
    // Laisse le temps à la vérification faite au lancement.
    const timer = setTimeout(load, 5000);
    return () => clearTimeout(timer);
  });

  const visible = $derived(view !== null && (phase !== "idle" || (view.available && view.latest !== dismissed)));

  function later() {
    if (!view?.latest) return;
    dismissed = view.latest;
    try {
      localStorage.setItem(KEY, view.latest);
    } catch {
      // mémorisation impossible : le bandeau reviendra au prochain chargement
    }
  }

  async function install() {
    if (!view) return;
    phase = "downloading";
    progress = 0;
    failure = "";
    try {
      const result = await installAndWait(view.current, (v) => {
        progress = v.progress;
        if (v.state === "installing") phase = "installing";
        if (v.state === "failed") failure = v.error ?? "La mise à jour a échoué";
      });
      if (result === "restarted") location.reload();
      else phase = result;
    } catch (e) {
      failure = e instanceof Error ? e.message : "La mise à jour a échoué";
      phase = "failed";
    }
  }
</script>

{#if visible && view}
  <div class="banner info" role="status">
    {#if phase === "downloading"}
      Téléchargement… {Math.round(progress)} %
    {:else if phase === "installing"}
      Mise à jour en cours, CoachCloclo va redémarrer…
    {:else if phase === "stuck"}
      La mise à jour semble bloquée : relance CoachCloclo depuis l'icône du bureau
    {:else if phase === "failed"}
      {failure}
      <button type="button" onclick={install}>Réessayer</button>
    {:else}
      Version {view.latest} disponible —
      <button type="button" onclick={install}>Mettre à jour</button>
      <button type="button" onclick={later}>Plus tard</button>
    {/if}
  </div>
{/if}
