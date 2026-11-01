<script lang="ts">
  import { onMount } from "svelte";
  import { api, ApiError, claudeSkipped, setupDone, type SetupStatus, type Status } from "./lib/api";
  import ErrorBanner from "./components/ErrorBanner.svelte";
  import UpdateBanner from "./components/UpdateBanner.svelte";
  import Sidebar from "./components/Sidebar.svelte";
  import Welcome from "./routes/Welcome.svelte";
  import Setup from "./routes/Setup.svelte";
  import Goal from "./routes/Goal.svelte";
  import Today from "./routes/Today.svelte";
  import Plan from "./routes/Plan.svelte";
  import Proposal from "./routes/Proposal.svelte";
  import Race from "./routes/Race.svelte";
  import Stats from "./routes/Stats.svelte";

  const ROUTES = ["today", "plan", "race", "stats", "goal", "setup", "proposal", "welcome"] as const;
  type Route = (typeof ROUTES)[number];

  let route = $state<Route | null>(parse());
  let status = $state<Status | null>(null);
  let setupAvailable = $state(false); // appli de bureau : l'écran d'accueil existe
  let error = $state<unknown>(null);
  let version = $state(0);
  let ready = $state(false);
  let syncing = $state(false);
  let lastSync = $state<Date | null>(null);
  let autoSyncStarted = false; // une seule synchro automatique par chargement de l'app

  function parse(): Route | null {
    const name = location.hash.replace(/^#\//, "");
    return (ROUTES as readonly string[]).includes(name) ? (name as Route) : null;
  }

  /** Page d'accueil : le plan en cours d'abord, sinon les statistiques, sinon l'objectif à fixer. */
  function home(): string {
    if (status?.garmin === "auth_required") return "#/setup";
    if (status?.goal?.plan_accepted) return "#/today";
    return status?.has_activities ? "#/stats" : "#/goal";
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

  /** État de l'écran d'accueil ; `null` sous `coach start` (404) ou si la lecture échoue. */
  async function readSetup(): Promise<SetupStatus | null> {
    try {
      return await api.setupStatus();
    } catch {
      return null;
    }
  }

  async function start() {
    const [setup] = await Promise.all([readSetup(), refresh()]);
    setupAvailable = setup !== null;
    ready = true;
    if (!autoSyncStarted && !error && status?.garmin === "ok") {
      autoSyncStarted = true;
      sync();
    }
    if (!route) {
      // Configuration incomplète : l'écran d'accueil, même si /api/status a échoué.
      if (setup && !setupDone(setup, claudeSkipped())) location.hash = "#/welcome";
      else if (!error) location.hash = home();
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

  /** Renvoie `false` si la synchro a échoué (l'erreur est alors affichée). */
  async function sync(): Promise<boolean> {
    if (syncing) return true;
    syncing = true;
    try {
      await api.sync();
      lastSync = new Date();
      version++;
      await refresh();
      return true;
    } catch (e) {
      failed(e);
      return false;
    } finally {
      syncing = false;
    }
  }

  /** Connexion Garmin réussie depuis les Réglages : synchronise (même si une synchro a déjà eu lieu) puis oriente. */
  async function garminConnected() {
    await refresh();
    autoSyncStarted = true;
    if (status?.has_activities) {
      // Activités déjà là : on les montre tout de suite, la synchro se fait en arrière-plan.
      location.hash = home();
      sync();
      return;
    }
    // Premier lancement : la synchro ramène les activités récentes et lance l'import de l'historique.
    // En cas d'échec on reste sur les Réglages : changer de page effacerait le message d'erreur.
    if (!(await sync())) return;
    location.hash = home();
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

<div class="shell">
  <Sidebar {route} {status} {syncing} {lastSync} onsync={sync} />

  <main class="content">
    <UpdateBanner />
    <ErrorBanner {error} onpin={start} {setupAvailable} />

    {#if syncing}
      <p class="card busy" role="status">
        {status?.goal ? "Analyse de ta séance par Claude…" : "Synchronisation Garmin…"}
      </p>
    {/if}

    {#if ready && !(error && (error as { code?: string }).code === "pin_required")}
      {#if route === "welcome"}
        <Welcome onconnected={garminConnected} />
      {:else if route === "setup"}
        <Setup onchanged={refresh} onconnected={garminConnected} />
      {:else if route === "goal"}
        <Goal onchanged={refresh} />
      {:else if route === "today"}
        <Today {version} {status} onerror={failed} />
      {:else if route === "plan"}
        <Plan {version} onerror={failed} />
      {:else if route === "race" && status?.goal}
        <Race goal={status.goal} onerror={failed} />
      {:else if route === "stats"}
        <Stats {version} history={status?.history ?? null} onimport={importHistory} />
      {:else if route === "proposal"}
        <Proposal onchanged={refresh} />
      {/if}
    {/if}
  </main>
</div>
