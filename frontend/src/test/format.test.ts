import { describe, expect, it } from "vitest";
import { fmtMoney, fmtPct, fmtSignedPct, signClass } from "../lib/format";

describe("format helpers", () => {
  it("formats money", () => {
    expect(fmtMoney(1234.5)).toBe("$1,234.50");
    expect(fmtMoney(null)).toBe("—");
  });
  it("formats percents from fractions", () => {
    expect(fmtPct(0.1234)).toBe("12.34%");
    expect(fmtSignedPct(0.01)).toBe("+1.00%");
    expect(fmtSignedPct(-0.01)).toBe("-1.00%");
    expect(fmtSignedPct(null)).toBe("—");
  });
  it("reserves green/red for signed returns only", () => {
    expect(signClass(0.05)).toContain("pos");
    expect(signClass(-0.05)).toContain("neg");
    expect(signClass(0)).toBe("");
    expect(signClass(null)).toBe("");
  });
});
