import { render, screen } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Proposal from "./Proposal.svelte";
import type { Change, SessionSpec } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

const spec = (title: string, sport?: "run" | "bike"): SessionSpec => ({
  week_index: 2, order: 1, suggested_day: "mercredi", type: "EF", target_kind: "hr", title, description: "",
  sport, steps: [],
});
const change = (op: Change["op"], session: SessionSpec | null): Change => ({
  op, session_id: op === "add" ? null : 7, session, reason: "Pour varier",
});

function mock(changes: Change[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (url === "/api/proposals/pending")
        return json({ id: 1, created_at: "2026-11-03T08:00:00", analysis: "Analyse", changes });
      if (url === "/api/plan") return json({ goal: {}, weeks: [], open_injury: null });
      return json({});
    }),
  );
}

test("a proposed bike session shows the bike chip", async () => {
  mock([change("add", spec("Sortie vélo douce", "bike")), change("modify", spec("Footing", "run"))]);
  render(Proposal);
  await screen.findByText("Sortie vélo douce");
  expect(screen.getAllByText("Vélo")).toHaveLength(1);
});

test("a removed session shows no bike chip", async () => {
  mock([change("remove", spec("Sortie vélo douce", "bike"))]);
  render(Proposal);
  await screen.findByText("Retirée");
  expect(screen.queryByText("Vélo")).toBeNull();
});
