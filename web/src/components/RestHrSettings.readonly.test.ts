import { render } from "@testing-library/svelte";
import { expect, test, vi } from "vitest";
import RestHrSettings from "./RestHrSettings.svelte";

vi.mock("../lib/mode", () => ({ READONLY: true }));

test("absent en lecture seule, sans appel réseau", () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  const { container } = render(RestHrSettings);
  expect(container.querySelector(".set-row")).toBeNull();
  expect(fetchSpy).not.toHaveBeenCalled();
});
