import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import RestHrSettings from "./RestHrSettings.svelte";

type View = {
  value: number | null;
  source: string | null;
  nights: number | null;
  manual: number | null;
  auto_value: number | null;
  auto_nights: number | null;
};

let view: View;
let puts: unknown[];
let putExtra: Record<string, unknown>;

beforeEach(() => {
  view = { value: 47, source: "nights", nights: 12, manual: null, auto_value: 47, auto_nights: 12 };
  puts = [];
  putExtra = { resent: 0, failed: [], applied: true };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/rest-hr" && init?.method === "PUT") {
        const body = JSON.parse(init.body as string);
        puts.push(body);
        view = { ...view, manual: body.manual, value: body.manual ?? view.auto_value, source: body.manual == null ? "nights" : "manual" };
        return new Response(JSON.stringify({ ...view, ...putExtra }), { status: 200 });
      }
      if (url === "/api/rest-hr") return new Response(JSON.stringify(view), { status: 200 });
      return new Response("{}", { status: 404 });
    }),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
});

test("affiche la provenance des nuits", async () => {
  render(RestHrSettings);
  expect(await screen.findByText("47 bpm, moyenne de 12 nuits avec la montre")).toBeInTheDocument();
});

test("affiche la provenance saisie à la main et le calcul automatique", async () => {
  view = { value: 44, source: "manual", nights: null, manual: 44, auto_value: 47, auto_nights: 12 };
  render(RestHrSettings);
  expect(await screen.findByText("44 bpm, saisie à la main")).toBeInTheDocument();
  expect(screen.getByText("Calcul automatique : 47 bpm (12 nuits)")).toBeInTheDocument();
});

test("pas de ligne de calcul automatique sans saisie manuelle", async () => {
  render(RestHrSettings);
  await screen.findByText(/moyenne de 12 nuits/);
  expect(screen.queryByText(/Calcul automatique/)).toBeNull();
});

test("enregistre une valeur puis revient à l'automatique en vidant le champ", async () => {
  render(RestHrSettings);
  const input = await screen.findByLabelText("FC repos");
  await fireEvent.input(input, { target: { value: "44" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(puts).toEqual([{ manual: 44 }]));
  await waitFor(() => expect(screen.getByLabelText("FC repos")).toHaveValue(44));

  await fireEvent.input(screen.getByLabelText("FC repos"), { target: { value: "" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(puts).toEqual([{ manual: 44 }, { manual: null }]));
});

test("refuse une valeur hors de 30–100", async () => {
  render(RestHrSettings);
  const input = await screen.findByLabelText("FC repos");
  await fireEvent.input(input, { target: { value: "29" } });
  expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
  await fireEvent.input(input, { target: { value: "101" } });
  expect(screen.getByRole("button", { name: "Enregistrer" })).toBeDisabled();
  await fireEvent.input(input, { target: { value: "30" } });
  expect(screen.getByRole("button", { name: "Enregistrer" })).toBeEnabled();
});

test("annonce les séances renvoyées à la montre, au singulier et au pluriel", async () => {
  putExtra = { resent: 2, failed: [], applied: true };
  render(RestHrSettings);
  await fireEvent.input(await screen.findByLabelText("FC repos"), { target: { value: "44" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByText("2 séances mises à jour sur ta montre")).toBeInTheDocument();

  putExtra = { resent: 1, failed: [], applied: true };
  await fireEvent.input(screen.getByLabelText("FC repos"), { target: { value: "45" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByText("1 séance mise à jour sur ta montre")).toBeInTheDocument();
});

test("annonce que la valeur s'appliquera à la prochaine synchro", async () => {
  putExtra = { resent: 0, failed: [], applied: false };
  render(RestHrSettings);
  await fireEvent.input(await screen.findByLabelText("FC repos"), { target: { value: "44" } });
  await fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByText("Enregistrée : elle s'appliquera à la prochaine synchro")).toBeInTheDocument();
});
