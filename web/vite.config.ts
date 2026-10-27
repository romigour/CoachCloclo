/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: "../coach/web_dist",
    emptyOutDir: true,
    rollupOptions: {
      input: { main: "index.html", sw: "src/sw.ts" },
      output: {
        // le service worker garde un nom stable à la racine
        entryFileNames: (chunk) => (chunk.name === "sw" ? "sw.js" : "assets/[name]-[hash].js"),
      },
    },
  },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  resolve: process.env.VITEST ? { conditions: ["browser"] } : undefined,
  test: {
    environment: "jsdom",
    setupFiles: ["src/test-setup.ts"],
    globals: true,
  },
});
