import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/svelte";
import { afterEach } from "vitest";
import { clearCache } from "./lib/cache";

afterEach(() => {
  cleanup();
  clearCache(); // le cache est partagé par toutes les pages : chaque test part d'un cache vide
});
