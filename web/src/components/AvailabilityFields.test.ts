import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { expect, test } from "vitest";
import AvailabilityFields, { availabilityValid } from "./AvailabilityFields.svelte";
import { WEEKDAYS } from "../lib/dates";

const open = (props = {}) => render(AvailabilityFields, { days: [...WEEKDAYS], longRunDay: "", perWeek: 3, ...props });
const options = () => within(screen.getByLabelText("Jour de la sortie longue")).getAllByRole("option").map((o) => o.textContent);

test("unchecking a day removes it from the long run choices", async () => {
  open();
  expect(options()).toContain("Lundi");
  await fireEvent.click(screen.getByRole("checkbox", { name: "Lundi" }));
  expect(options()).not.toContain("Lundi");
  expect(options()[0]).toBe("Aucun");
});

test("unchecking the chosen long run day resets it to Aucun", async () => {
  open({ longRunDay: "dimanche" });
  const select = screen.getByLabelText("Jour de la sortie longue") as HTMLSelectElement;
  expect(select.value).toBe("dimanche");
  await fireEvent.click(screen.getByRole("checkbox", { name: "Dimanche" }));
  expect(select.value).toBe("");
});

test("warns when fewer days than sessions per week", async () => {
  open({ days: ["mardi", "jeudi", "dimanche"], perWeek: 3 });
  expect(screen.queryByText("Coche au moins 3 jours")).toBeNull();
  await fireEvent.click(screen.getByRole("checkbox", { name: "Jeudi" }));
  expect(screen.getByText("Coche au moins 3 jours")).toBeInTheDocument();
});

test("availabilityValid compares days with sessions per week", () => {
  expect(availabilityValid(["lundi", "mardi"], 3)).toBe(false);
  expect(availabilityValid(["lundi", "mardi", "jeudi"], 3)).toBe(true);
});

test("the bike checkbox is unchecked by default and toggles includeBike", async () => {
  open();
  const box = screen.getByRole("checkbox", { name: /Inclure du vélo/ }) as HTMLInputElement;
  expect(box.checked).toBe(false);
  await fireEvent.click(box);
  expect(box.checked).toBe(true);
});
