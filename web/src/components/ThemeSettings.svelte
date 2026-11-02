<script lang="ts">
  import { setThemeChoice, themeChoice, type ThemeChoice } from "../lib/theme.svelte";

  const OPTIONS: { value: ThemeChoice; label: string }[] = [
    { value: "auto", label: "Auto" },
    { value: "light", label: "Clair" },
    { value: "dark", label: "Sombre" },
  ];
</script>

<section class="card stack">
  <h2>Apparence</h2>
  <fieldset>
    <legend>Thème</legend>
    <div class="segmented">
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
  </fieldset>
  <p class="meta">Auto suit le réglage clair / sombre de Windows.</p>
</section>
