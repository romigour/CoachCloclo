<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";

  let {
    onsynced,
    onerror,
    auto = true,
    disabled = false,
  }: { onsynced?: () => void; onerror?: (e: unknown) => void; auto?: boolean; disabled?: boolean } = $props();

  let busy = $state(false);

  async function run() {
    if (busy) return;
    busy = true;
    try {
      await api.sync();
      onsynced?.();
    } catch (e) {
      onerror?.(e);
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    if (auto) run();
  });
</script>

<button class="sync" onclick={run} disabled={busy || disabled} aria-busy={busy}>
  {busy ? "Analyse de ta séance par Claude…" : "Synchroniser"}
</button>
