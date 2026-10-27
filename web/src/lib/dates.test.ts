import { describe, expect, test } from "vitest";
import { defaultExportDate, weekDays, formatDay } from "./dates";

describe("dates", () => {
  test("weekDays returns monday..sunday", () => {
    expect(weekDays("2026-11-09")).toEqual([
      "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15",
    ]);
  });
  test("weekDays crosses month and year boundaries", () => {
    expect(weekDays("2026-12-28")[6]).toBe("2027-01-03");
  });
  test("defaultExportDate uses suggested day", () => {
    expect(defaultExportDate("2026-11-09", "jeudi")).toBe("2026-11-12");
    expect(defaultExportDate("2026-11-09", "dimanche")).toBe("2026-11-15");
  });
  test("formatDay is French", () => {
    expect(formatDay("2026-11-12")).toBe("jeudi 12 novembre");
  });
});
