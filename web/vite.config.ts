/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig(({ mode }) => {
  const mobile = mode === "mobile";
  return {
    // le build mobile est publié sur GitHub Pages, sous /CoachCloclo/app/
    base: mobile ? "/CoachCloclo/app/" : "/",
    plugins: [svelte()],
    build: {
      outDir: mobile ? "dist-mobile" : "../coach/web_dist",
      emptyOutDir: true,
      rollupOptions: {
        input: { main: "index.html", sw: "src/sw.ts" },
        output: {
          // le service worker garde un nom stable à la racine
          entryFileNames: (chunk) => (chunk.name === "sw" ? "sw.js" : "assets/[name]-[hash].js"),
        },
      },
    },
    server: mobile ? {} : { proxy: { "/api": "http://127.0.0.1:8765" } },
    resolve: process.env.VITEST ? { conditions: ["browser"] } : undefined,
    test: {
      environment: "jsdom",
      setupFiles: ["src/test-setup.ts"],
      globals: true,
    },
  };
});
