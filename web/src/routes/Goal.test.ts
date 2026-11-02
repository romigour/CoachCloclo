import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, expect, test, vi } from "vitest";
import Goal from "./Goal.svelte";

afterEach(() => vi.unstubAllGlobals());

const noPlan = () =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ goal: null, weeks: [] }), { status: 200 })));

test("goal form bounds match the backend (2 to 7 sessions, positive distance)", () => {
  noPlan();
  render(Goal);
  const perWeek = within(screen.getByRole("group", { name: "Séances par semaine" }));
  expect(perWeek.getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["2", "3", "4", "5", "6", "7"]);
  const distance = screen.getByLabelText("Distance (km)") as HTMLInputElement;
  expect(Number(distance.min)).toBeGreaterThan(0);
});

test("distance presets fill the distance field", async () => {
  noPlan();
  render(Goal);
  await fireEvent.click(screen.getByRole("button", { name: "Marathon · 42,2 km" }));
  expect((screen.getByLabelText("Distance (km)") as HTMLInputElement).value).toBe("42.2");
  expect(screen.getByRole("button", { name: "Marathon · 42,2 km" })).toHaveAttribute("aria-pressed", "true");
});

const mkGoal = (extra = {}) => ({
  id: 1, type: "route", distance_km: 21.1, d_plus_m: 0, race_date: "2027-03-01", sessions_per_week: 4,
  plan_start: "2027-01-01", plan_accepted: false, gpx_summary: null, target_time_s: null, target_source: null, ...extra,
});

function fillBase() {
  fireEvent.input(screen.getByLabelText("Date de la course"), { target: { value: "2027-03-01" } });
}

test("target time defaults to Claude estimate", () => {
  noPlan();
  render(Goal);
  expect(screen.getByRole("radio", { name: "Laisser Claude estimer" })).toBeChecked();
  expect(screen.queryByLabelText("Temps visé (h:mm)")).toBeNull();
});

test("choosing my own time shows the field and sends it", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.endsWith("/goals")) return new Response(JSON.stringify(mkGoal({ target_time_s: 6600, target_source: "user" })), { status: 200 });
    if (url.endsWith("/generate")) return new Response(JSON.stringify({ summary: "ok", weeks: 8 }), { status: 200 });
    return new Response(JSON.stringify({ goal: null, weeks: [] }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(Goal);
  await fireEvent.click(screen.getByRole("radio", { name: "Je fixe mon temps" }));
  await fireEvent.input(screen.getByLabelText("Temps visé (h:mm)"), { target: { value: "1:50" } });
  fillBase();
  await fireEvent.submit(screen.getByRole("button", { name: "Générer le plan avec Claude" }).closest("form")!);
  await vi.waitFor(() => {
    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/goals") && (i as RequestInit)?.method === "POST");
    expect(post).toBeTruthy();
    expect(((post![1] as RequestInit).body as FormData).get("target_time")).toBe("1:50");
  });
});

test("invalid own time blocks submit", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ goal: null, weeks: [] }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  render(Goal);
  await fireEvent.click(screen.getByRole("radio", { name: "Je fixe mon temps" }));
  await fireEvent.input(screen.getByLabelText("Temps visé (h:mm)"), { target: { value: "1h50" } });
  fillBase();
  await fireEvent.submit(screen.getByRole("button", { name: "Générer le plan avec Claude" }).closest("form")!);
  expect(await screen.findByText(/Temps visé invalide/)).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([, i]) => (i as RequestInit | undefined)?.method === "POST")).toBe(false);
});

test("draft shows Claude estimate", async () => {
  const goal = mkGoal({ target_time_s: 6720, target_source: "claude" });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ goal, weeks: [{ id: 1, week_index: 1, week_monday: "2027-01-04", sessions: [] }] }), { status: 200 })));
  render(Goal);
  expect(await screen.findByText(/Temps estimé par Claude : 1 h 52/)).toBeInTheDocument();
});

test("draft shows the Claude estimate right after generation, without remount", async () => {
  const claudeGoal = mkGoal({ target_time_s: 6720, target_source: "claude" });
  let generated = false;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.endsWith("/goals")) return new Response(JSON.stringify(mkGoal()), { status: 200 });
    if (url.endsWith("/generate")) {
      generated = true;
      return new Response(JSON.stringify({ summary: "ok", weeks: 8 }), { status: 200 });
    }
    const body = generated
      ? { goal: claudeGoal, weeks: [{ id: 1, week_index: 1, week_monday: "2027-01-04", sessions: [] }] }
      : { goal: null, weeks: [] };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  render(Goal);
  fillBase();
  await fireEvent.submit(screen.getByRole("button", { name: "Générer le plan avec Claude" }).closest("form")!);
  expect(await screen.findByText(/Temps estimé par Claude : 1 h 52/)).toBeInTheDocument();
});
