import { describe, it, expect } from "vitest";
import { formatPeriodLabel, granularityLabel } from "@/utils/period";

describe("utils/period.ts", () => {
  it("formatPeriodLabel: day -> MM-DD", () => {
    expect(formatPeriodLabel("2026-07-16", "day")).toBe("07-16");
  });

  it("formatPeriodLabel: week -> Wxx (no zero-pad)", () => {
    expect(formatPeriodLabel("2026-W29", "week")).toBe("W29");
    expect(formatPeriodLabel("2026-W05", "week")).toBe("W5");
  });

  it("formatPeriodLabel: month -> YYYY-MM (unchanged)", () => {
    expect(formatPeriodLabel("2026-07", "month")).toBe("2026-07");
  });

  it("formatPeriodLabel: empty period", () => {
    expect(formatPeriodLabel("", "day")).toBe("");
  });

  it("granularityLabel maps to Chinese", () => {
    expect(granularityLabel("day")).toBe("当日");
    expect(granularityLabel("week")).toBe("当周");
    expect(granularityLabel("month")).toBe("当月");
  });
});
