import { render, screen } from "@testing-library/svelte";
import { expect, test } from "vitest";
import Sidebar from "./Sidebar.svelte";
import type { GarminState, Status } from "../lib/api";

const status = { pending_proposal_id: null, next_goal: null } as Status;
const show = (garmin: GarminState) => render(Sidebar, { route: "week", status, garmin });

test("Garmin en cours de vérification : ni bouton ni lien", () => {
  show("checking");
  expect(screen.getByText("Vérification de Garmin…")).toBeVisible();
  const box = document.querySelector(".garmin-box")!;
  expect(box.querySelector("button, a")).toBeNull();
  expect(box.querySelector(".dot.ok, .dot.ko")).toBeNull();
});

test.each([
  ["ok", "Garmin connecté", "button"],
  ["auth_required", "Connexion Garmin requise", "a"],
  ["unavailable", "Garmin indisponible", "a"],
] as const)("état %s", (garmin, label, control) => {
  show(garmin);
  expect(screen.getByText(label)).toBeVisible();
  expect(document.querySelector(`.garmin-box ${control}`)).not.toBeNull();
});
