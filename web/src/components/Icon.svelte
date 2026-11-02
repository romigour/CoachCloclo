<script lang="ts">
  // icônes au trait, coins arrondis ; décoratives (le texte voisin porte le sens)
  const PATHS = {
    today: "M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
    calendar: "M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM3 10h18M8 3v4M16 3v4",
    chart: "M4 20h16M7 16v-5M12 16V6M17 16v-8",
    chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
    flag: "M5 21V4M5 4h11l-2 4 2 4H5",
    // engrenage à 8 dents (l'ancien rayonnement se confondait avec « today »)
    settings:
      "M19.1 10.82L21.44 10.96L21.44 13.04L19.1 13.18L17.86 16.19L19.41 17.94L17.94 19.41L16.19 17.86L13.18 19.1L13.04 21.44L10.96 21.44L10.82 19.1L7.81 17.86L6.06 19.41L4.59 17.94L6.14 16.19L4.9 13.18L2.56 13.04L2.56 10.96L4.9 10.82L6.14 7.81L4.59 6.06L6.06 4.59L7.81 6.14L10.82 4.9L10.96 2.56L13.04 2.56L13.18 4.9L16.19 6.14L17.94 4.59L19.41 6.06L17.86 7.81zM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6",
    sync: "M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4",
    race: "M5 21V4M5 4h4v3h4V4h4v3h2v6h-2v-3h-4v3H9v-3H5",
    trend: "M3 17l5-6 4 3 5-7 4 5",
    close: "M6 6l12 12M18 6L6 18",
    arrow: "M5 12h14M13 6l6 6-6 6",
    upload: "M12 16V4M7 9l5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3",
  } as const;

  let { name, size = 18 }: { name: keyof typeof PATHS; size?: number } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.8"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"><path d={PATHS[name]} /></svg>
