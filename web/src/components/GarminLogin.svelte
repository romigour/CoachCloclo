<script lang="ts">
  import { api, ApiError } from "../lib/api";
  import ErrorBanner from "./ErrorBanner.svelte";

  /** Formulaire de connexion Garmin (e-mail, mot de passe, MFA éventuel). `onconnected` est appelé une fois connecté. */
  let { onconnected }: { onconnected?: () => void | Promise<void> } = $props();

  let email = $state("");
  let password = $state("");
  let loginId = $state<string | null>(null);
  let code = $state("");
  let loginMessage = $state("");
  let error = $state<unknown>(null);
  let busy = $state(false);

  async function login(e: Event) {
    e.preventDefault();
    busy = true;
    loginMessage = "";
    error = null;
    try {
      const r = await api.login(email, password);
      password = "";
      if (r.status === "needs_mfa") loginId = r.login_id ?? null;
      else await onconnected?.();
    } catch (err) {
      if (err instanceof ApiError && err.code === "garmin_login_failed") loginMessage = "Identifiants Garmin refusés";
      else error = err;
    } finally {
      busy = false;
    }
  }

  async function sendMfa(e: Event) {
    e.preventDefault();
    if (!loginId) return;
    busy = true;
    loginMessage = "";
    error = null;
    try {
      await api.mfa(loginId, code);
      loginId = null;
      code = "";
      await onconnected?.();
    } catch (err) {
      if (err instanceof ApiError && err.code === "garmin_login_failed") loginMessage = "Code refusé";
      else if (err instanceof ApiError && err.code === "mfa_expired") {
        loginId = null;
        loginMessage = "Connexion expirée, recommence";
      } else error = err;
    } finally {
      busy = false;
    }
  }
</script>

<ErrorBanner {error} />
{#if loginId}
  <form class="stack" onsubmit={sendMfa}>
    <label>
      Code de vérification (MFA)
      <input bind:value={code} inputmode="numeric" autocomplete="one-time-code" required />
    </label>
    <div class="row"><button class="primary" disabled={busy}>Valider le code</button></div>
  </form>
{:else}
  <form class="stack" onsubmit={login}>
    <label>
      E-mail Garmin
      <input type="email" bind:value={email} autocomplete="username" required />
    </label>
    <label>
      Mot de passe
      <input type="password" bind:value={password} autocomplete="current-password" required />
    </label>
    <div class="row"><button class="primary" disabled={busy}>Se connecter</button></div>
  </form>
{/if}
{#if loginMessage}<p class="error" role="alert">{loginMessage}</p>{/if}
