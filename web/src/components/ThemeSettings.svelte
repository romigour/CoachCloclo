<script lang="ts">
  import { setThemeChoice, themeChoice, type ThemeChoice } from "../lib/theme.svelte";

  const OPTIONS: { value: ThemeChoice; label: string }[] = [
    { value: "auto", label: "Auto" },
    { value: "light", label: "Clair" },
    { value: "dark", label: "Sombre" },
  ];
</script>

<div class="set-row">
  <div class="set-label">
    <h3 id="theme-h">Thème</h3>
    <p>Auto suit le réglage clair / sombre de Windows.</p>
  </div>
  <div class="set-ctl">
    <div class="segmented" role="radiogroup" aria-labelledby="theme-h">
      {#each OPTIONS as o (o.value)}
        <label>
          <input
            type="radio"
            name="theme"
            value={o.value}
            checked={themeChoice() === o.value}
            onchange={() => setThemeChoice(o.value)}
          />
          <span>{o.label}</span>
        </label>
      {/each}
    </div>
  </div>
</div>
