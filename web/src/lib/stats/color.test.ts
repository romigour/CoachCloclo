import { expect, test } from "vitest";
import { withAlpha } from "./color";

test("withAlpha converts hex colours and leaves others untouched", () => {
  expect(withAlpha("#1f6feb", 0.5)).toBe("rgba(31, 111, 235, 0.5)");
  expect(withAlpha("#fff", 0.3)).toBe("rgba(255, 255, 255, 0.3)");
  expect(withAlpha("", 0.3)).toBe("");
  expect(withAlpha("rgb(1, 2, 3)", 0.3)).toBe("rgb(1, 2, 3)");
});
