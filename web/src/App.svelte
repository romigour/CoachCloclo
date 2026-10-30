<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, type Status } from "./lib/api";
  import ErrorBanner from "./components/ErrorBanner.svelte";
  import Setup from "./routes/Setup.svelte";
  import Goal from "./routes/Goal.svelte";
  import Plan from "./routes/Plan.svelte";
  import Proposal from "./routes/Proposal.svelte";
  import Stats from "./routes/Stats.svelte";

  const ROUTES = ["stats", "setup", "goal", "plan", "proposal"] as const;
  type Route = (typeof ROUTES)[number];

  let route = $state<Route | null>(parse());
  let status = $state<Status | null>(null);
  let error = $state<unknown>(null);
  let version = $state(0);
  let ready = $state(false);
  let syncing = $state(false);
  let autoSyncStarted = false; // une seule synchro automatique par chargement de l'app

  function parse(): Route | null {
    const name = location.hash.replace(/^#\//, "");
    return (ROUTES as readonly string[]).includes(name) ? (name as Route) : null;
  }

  /** Relit l'état ; `clear` efface l'erreur affichée (pas depuis le sondage, qui la ferait disparaître). */
  async function refresh(clear = true) {
    try {
      const next = await api.status();
      // Fin d'import (réussie ou non) observée via le sondage : les statistiques doivent être rechargées.
      const ended = next.history.status === "done" || next.history.status === "error";
      if (status?.history.status === "running" && ended) version++;
      status = next;
      if (clear) error = null;
    } catch (e) {
      error = e;
    }
  }

  async function start() {
    await refresh();
    ready = true;
    if (!autoSyncStarted && !error && status?.garmin === "ok") {
      autoSyncStarted = true;
      autoSync();
    }
    if (!route && !error) {
      location.hash = status?.garmin === "auth_required" ? "#/setup" : status?.has_activities ? "#/stats" : status?.goal ? "#/plan" : "#/goal";
    }
  }

  // Pendant l'import de l'historique, on relit l'état toutes les 5 s ; l'intervalle s'arrête dès que l'état change.
  const importRunning = $derived(status?.history.status === "running");
  $effect(() => {
    if (!importRunning) return;
    const timer = setInterval(() => refresh(false), 5000);
    return () => clearInterval(timer);
  });

  onMount(() => {
    const onhash = () => {
      route = parse();
      error = null;
    };
    window.addEventListener("hashchange", onhash);
    start();
    return () => window.removeEventListener("hashchange", onhash);
  });

  async function autoSync() {
    syncing = true;
    try {
      await api.sync();
      await synced();
    } catch (e) {
      failed(e);
    } finally {
      syncing = false;
    }
  }

  async function synced() {
    version++;
    await refresh();
  }

  /** Connexion Garmin réussie depuis les Réglages : synchronise (même si une synchro a déjà eu lieu) puis oriente. */
  async function garminConnected() {
    await refresh();
    autoSyncStarted = true;
    if (status?.has_activities) {
      // Activités déjà là : on les montre tout de suite, la synchro se fait en arrière-plan.
      location.hash = "#/stats";
      if (!syncing) autoSync();
      return;
    }
    // Premier lancement : la synchro ramène les activités récentes et lance l'import de l'historique.
    if (!syncing) await autoSync();
    location.hash = status?.has_activities ? "#/stats" : status?.goal ? "#/plan" : "#/goal";
  }

  function failed(e: unknown) {
    error = e;
  }

  async function importHistory() {
    try {
      await api.importHistory();
      refresh();
    } catch (e) {
      // Un import est déjà en cours : on se contente de relire l'état.
      if (e instanceof ApiError && e.code === "history_running") refresh();
      else failed(e);
    }
  }
</script>

<header class="topbar">
  <strong>CoachCloclo</strong>
  <nav>
    <a href="#/stats" class:active={route === "stats"}>Stats</a>
    <a href="#/plan" class:active={route === "plan"}>Plan</a>
    <a href="#/goal" class:active={route === "goal"}>Objectif</a>
    <a href="#/setup" class:active={route === "setup"}>Réglages</a>
  </nav>
</header>

<main class:wide={route === "stats"}>
  <ErrorBanner {error} onpin={start} />

  {#if syncing}
    <p class="card busy" role="status">
      {status?.goal ? "Analyse de ta séance par Claude…" : "Synchronisation Garmin…"}
    </p>
  {/if}

  {#if status?.pending_proposal_id != null && route !== "proposal"}
    <a class="banner info" href="#/proposal">Claude propose des changements à ton plan — voir la proposition</a>
  {/if}

  {#if ready && !(error && (error as { code?: string }).code === "pin_required")}
    {#if route === "stats"}
      <Stats {version} history={status?.history ?? null} onimport={importHistory} />
    {:else if route === "setup"}
      <Setup onchanged={refresh} onconnected={garminConnected} />
    {:else if route === "goal"}
      <Goal onchanged={refresh} />
    {:else if route === "plan"}
      <Plan {version} {syncing} onsynced={synced} onerror={failed} />
    {:else if route === "proposal"}
      <Proposal onchanged={refresh} />
    {/if}
  {/if}
</main>
