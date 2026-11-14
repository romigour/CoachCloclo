<script lang="ts">
  import { api, ApiError } from "../lib/api";
  import { READONLY } from "../lib/mode";

  let { error, onpin, setupAvailable = false }: { error: unknown; onpin?: () => void; setupAvailable?: boolean } = $props();

  let pin = $state("");
  let pinError = $state("");
  let busy = $state(false);

  const code = $derived(error instanceof ApiError ? error.code : null);
  const message = $derived.by(() => {
    if (!error) return "";
    switch (code) {
      case "llm_limit":
        return "Limite Claude atteinte : réessaie plus tard ou passe en mode clé API";
      case "garmin_unavailable":
        return "Garmin est indisponible pour le moment, réessaie plus tard.";
      case "garmin_rate_limited":
        return "Garmin limite les requêtes, réessaie plus tard.";
      case "csrf":
        return "Requête refusée : recharge la page.";
      case "too_large":
        return "Fichier GPX trop volumineux (10 Mo maximum).";
      case "invalid_gpx":
        return `GPX invalide : ${(error as Error).message}`;
      default:
        return error instanceof Error ? error.message : "Erreur inattendue";
    }
  });

  // garmin_auth ouvre l'écran de configuration (en lecture seule : l'écran de connexion)
  const settingsHash = READONLY ? "#/connection" : "#/setup";
  $effect(() => {
    if (code === "garmin_auth" && location.hash !== settingsHash) location.hash = settingsHash;
  });

  async function submitPin(e: Event) {
    e.preventDefault();
    busy = true;
    pinError = "";
    try {
      await api.pin(pin);
      pin = "";
      onpin?.();
    } catch (err) {
      pinError = err instanceof Error ? err.message : "Erreur";
    } finally {
      busy = false;
    }
  }
</script>

{#if error}
  {#if code === "pin_required"}
    <form class="card pin" onsubmit={submitPin}>
      <h2>PIN requis</h2>
      <label>
        Code PIN
        <input type="password" inputmode="numeric" autocomplete="current-password" bind:value={pin} required />
      </label>
      {#if pinError}<p class="error" role="alert">{pinError}</p>{/if}
      <button class="primary" disabled={busy}>Entrer</button>
    </form>
  {:else}
    <div class="banner error" role="alert">
      {message}
      {#if code === "llm_unavailable" && setupAvailable}
        <a href="#/welcome">Connecte Claude</a>
      {/if}
      {#if code === "schema_too_new" || code === "cloud_unreachable"}
        <a href={settingsHash}>{READONLY ? "Modifier la connexion" : "Ouvrir les Réglages"}</a>
      {/if}
    </div>
  {/if}
{/if}
