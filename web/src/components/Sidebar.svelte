<script lang="ts">
  import type { Status } from "../lib/api";
  import Icon from "./Icon.svelte";

  let {
    route,
    status,
    syncing = false,
    lastSync = null,
    onsync,
  }: {
    route: string | null;
    status: Status | null;
    syncing?: boolean;
    lastSync?: Date | null;
    onsync?: () => void;
  } = $props();

  const GARMIN = {
    ok: "Garmin connecté",
    auth_required: "Connexion Garmin requise",
    unavailable: "Garmin indisponible",
  } as const;

  const time = (d: Date) => d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
</script>

<aside class="sidebar">
  <div class="brand">
    <span class="brand-mark"><Icon name="trend" /></span>
    CoachCloclo
  </div>

  <nav class="nav" aria-label="Navigation principale">
    <a href="#/today" class:active={route === "today"} aria-current={route === "today" ? "page" : undefined}>
      <Icon name="today" /> Aujourd'hui
    </a>
    <a href="#/plan" class:active={route === "plan"} aria-current={route === "plan" ? "page" : undefined}>
      <Icon name="calendar" /> Programme
    </a>
    {#if status?.goal}
      <a href="#/race" class:active={route === "race"} aria-current={route === "race" ? "page" : undefined}>
        <Icon name="race" /> Jour J
      </a>
    {/if}
    <a href="#/stats" class:active={route === "stats"} aria-current={route === "stats" ? "page" : undefined}>
      <Icon name="chart" /> Statistiques
    </a>
    <a href="#/proposal" class:active={route === "proposal"} aria-current={route === "proposal" ? "page" : undefined}>
      <Icon name="chat" /> Propositions
      {#if status?.pending_proposal_id != null}
        <span class="count" aria-label="1 proposition en attente">1</span>
      {/if}
    </a>
    <a href="#/goal" class:active={route === "goal"} aria-current={route === "goal" ? "page" : undefined}>
      <Icon name="flag" /> Objectif
    </a>
    <a href="#/setup" class:active={route === "setup"} aria-current={route === "setup" ? "page" : undefined}>
      <Icon name="settings" /> Réglages
    </a>
  </nav>

  {#if status}
    <div class="garmin-box">
      <span class="state">
        <span class="dot" class:ok={status.garmin === "ok"} class:ko={status.garmin !== "ok"}></span>
        {GARMIN[status.garmin]}
      </span>
      {#if status.garmin === "ok"}
        {#if lastSync}<span class="meta">Dernière synchro à {time(lastSync)}</span>{/if}
        <button onclick={() => onsync?.()} disabled={syncing} aria-busy={syncing}>
          <Icon name="sync" size={15} />
          {syncing ? "Synchronisation…" : "Synchroniser"}
        </button>
      {:else}
        <a class="more" href="#/setup">Se connecter</a>
      {/if}
    </div>
  {/if}
</aside>
