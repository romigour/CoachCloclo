import { describe, expect, it } from "vitest";
import { fmtClock, fmtPace, parseClock } from "./format";

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
    expect(parseClock("0:00:00")).toBeNaN();
  });
});

describe("fmtPace", () => {
  it("m:ss /km", () => {
    expect(fmtPace(246.8)).toBe("4:07 /km");
    expect(fmtPace(300)).toBe("5:00 /km");
    expect(fmtPace(359.6)).toBe("6:00 /km");
  });
});
