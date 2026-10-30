<script lang="ts">
  import { onMount } from "svelte";
  import { api, type Status } from "./lib/api";
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

  async function refresh() {
    try {
      status = await api.status();
      error = null;
    } catch (e) {
      error = e;
    }
  }

  async function start() {
    await refresh();
    ready = true;
    if (!autoSyncStarted && !error && status?.garmin === "ok" && status.goal) {
      autoSyncStarted = true;
      autoSync();
    }
    if (!route && !error) {
      location.hash = status?.garmin === "auth_required" ? "#/setup" : status?.goal ? "#/plan" : "#/goal";
    }
  }

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
      synced();
    } catch (e) {
      failed(e);
    } finally {
      syncing = false;
    }
  }

  function synced() {
    version++;
    refresh();
  }

  function failed(e: unknown) {
    error = e;
  }

  async function importHistory() {
    try {
      await api.importHistory();
      refresh();
    } catch (e) {
      failed(e);
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
    <p class="card busy" role="status">Analyse de ta séance par Claude…</p>
  {/if}

  {#if status?.pending_proposal_id != null && route !== "proposal"}
    <a class="banner info" href="#/proposal">Claude propose des changements à ton plan — voir la proposition</a>
  {/if}

  {#if ready && !(error && (error as { code?: string }).code === "pin_required")}
    {#if route === "stats"}
      <Stats history={status?.history ?? null} onimport={importHistory} />
    {:else if route === "setup"}
      <Setup onchanged={refresh} />
    {:else if route === "goal"}
      <Goal onchanged={refresh} />
    {:else if route === "plan"}
      <Plan {version} {syncing} onsynced={synced} onerror={failed} />
    {:else if route === "proposal"}
      <Proposal onchanged={refresh} />
    {/if}
  {/if}
</main>
