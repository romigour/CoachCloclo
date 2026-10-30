import { describe, expect, it } from "vitest";
import { fmtClock, fmtMonthShort, fmtMonthTick, fmtPace, parseClock } from "./format";

describe("fmtClock", () => {
  it("m:ss sous l'heure, h:mm:ss au-delà", () => {
    expect(fmtClock(1234)).toBe("20:34");
    expect(fmtClock(2490)).toBe("41:30");
    expect(fmtClock(59)).toBe("0:59");
    expect(fmtClock(3600)).toBe("1:00:00");
    expect(fmtClock(5025)).toBe("1:23:45");
  });
  it("arrondit à la seconde sans produire « :60 »", () => {
    expect(fmtClock(59.6)).toBe("1:00");
    expect(fmtClock(3599.7)).toBe("1:00:00");
  });
});

describe("parseClock", () => {
  it("h:mm:ss et m:ss", () => {
    expect(parseClock("0:41:30")).toBe(2490);
    expect(parseClock("1:23:45")).toBe(5025);
    expect(parseClock("41:30")).toBe(2490);
    expect(parseClock(" 3:05:00 ")).toBe(11100);
  });
  it("vide → null, format invalide → NaN", () => {
    expect(parseClock("")).toBeNull();
    expect(parseClock("   ")).toBeNull();
    expect(parseClock("41")).toBeNaN();
    expect(parseClock("1:75:00")).toBeNaN();
    expect(parseClock("0:41:7")).toBeNaN();
    expect(parseClock("abc")).toBeNaN();
  });
  it("durée nulle → 0 (message distinct côté formulaire)", () => {
    expect(parseClock("0:00:00")).toBe(0);
    expect(parseClock("0:00")).toBe(0);
  });
});

describe("fmtPace", () => {
  it("m:ss /km", () => {
    expect(fmtPace(246.8)).toBe("4:07 /km");
    expect(fmtPace(300)).toBe("5:00 /km");
    expect(fmtPace(359.6)).toBe("6:00 /km");
  });
});

describe("étiquettes de mois courtes", () => {
  it("« janv. 26 » depuis « 2026-01 »", () => {
    expect(fmtMonthShort("2026-01")).toBe("janv. 26");
    expect(fmtMonthShort("2025-12")).toBe("déc. 25");
  });
  it("« mai 26 » depuis un horodatage local (axe temporel ECharts)", () => {
    expect(fmtMonthTick(new Date(2026, 4, 10).getTime())).toBe("mai 26");
  });
});
