<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "../lib/api";

  let {
    onsynced,
    onerror,
    auto = true,
  }: { onsynced?: () => void; onerror?: (e: unknown) => void; auto?: boolean } = $props();

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

<button class="sync" onclick={run} disabled={busy} aria-busy={busy}>
  {busy ? "Analyse de ta séance par Claude…" : "Synchroniser"}
</button>
