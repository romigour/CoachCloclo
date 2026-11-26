import { render, screen } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import ClaudeUsage from "./ClaudeUsage.svelte";
import type { LlmUsageRow, LlmUsageView } from "../lib/api";

function row(over: Partial<LlmUsageRow>): LlmUsageRow {
  return {
    created_at: "2026-11-14T17:02:00+00:00", kind: "generation", status: "ok", attempts: 1, cost_eur: 0.41,
    input_tokens: 40000, output_tokens: 6000, duration_ms: 42000, mode: "cli", model: "claude-sonnet-5-5",
    ...over,
  };
}

function serve(view: LlmUsageView | null, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(view ?? {}), { status })),
  );
}
afterEach(() => vi.unstubAllGlobals());

test("affiche total du mois, moyenne et dernières actions", async () => {
  serve({
    month: { generations: 4, adjustments: 3, cost_eur: 2.1 },
    avg_generation_eur: 0.38,
    recent: [
      row({ attempts: 2 }),
      row({ kind: "adjustment", status: "failed", cost_eur: null }),
      row({ kind: "race_advice", created_at: "2026-11-15T08:00:00+00:00", cost_eur: 0.05 }),
    ],
  });
  render(ClaudeUsage);
  expect(await screen.findByText(/4 générations · 3 ajustements · ≈ 2,10 €/)).toBeInTheDocument();
  expect(screen.getByText(/Coût moyen d'une génération de plan : ≈ 0,38 €/)).toBeInTheDocument();
  expect(screen.getByText("Génération de plan")).toBeInTheDocument();
  expect(screen.getByText("Ajustement")).toBeInTheDocument();
  expect(screen.getByText("Conseils du jour J")).toBeInTheDocument();
  expect(screen.getByText("≈ 0,41 €")).toBeInTheDocument();
  expect(screen.getByText("2 essais")).toBeInTheDocument();
  expect(screen.getByText("échec")).toBeInTheDocument();
  expect(screen.getByText("—")).toBeInTheDocument();
  expect(screen.getByText(/En abonnement, ce n'est pas ce que tu paies/)).toBeInTheDocument();
});

test("base vide", async () => {
  serve({ month: { generations: 0, adjustments: 0, cost_eur: 0 }, avg_generation_eur: null, recent: [] });
  render(ClaudeUsage);
  expect(await screen.findByText("Aucune génération enregistrée pour l'instant")).toBeInTheDocument();
  expect(screen.queryByText(/Coût moyen/)).toBeNull();
});

test("erreur de chargement : message court", async () => {
  serve(null, 500);
  render(ClaudeUsage);
  expect(await screen.findByText("Consommation indisponible pour le moment")).toBeInTheDocument();
});

test("réponse inattendue : message court, sans planter la page", async () => {
  serve({} as LlmUsageView);
  render(ClaudeUsage);
  expect(await screen.findByText("Consommation indisponible pour le moment")).toBeInTheDocument();
});
