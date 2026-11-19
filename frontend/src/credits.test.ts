import { describe, expect, it } from "vitest";
import { costOfScript, costOfSeconds, plural, resetLabel } from "./credits";

describe("credit prices (the same rule as the server)", () => {
  it("is one credit per started minute, at least one", () => {
    expect([costOfSeconds(1), costOfSeconds(59), costOfSeconds(60), costOfSeconds(61), costOfSeconds(600)]).toEqual([1, 1, 1, 2, 10]);
    expect(costOfSeconds(61, 2)).toBe(1);   // a plan where a credit pays for two minutes
  });
  it("prices a typed script at 150 words a minute", () => {
    expect([costOfScript(""), costOfScript("word ".repeat(150)), costOfScript("word ".repeat(151))]).toEqual([1, 1, 2]);
  });
  it("formats the renewal date and counts", () => {
    expect(resetLabel("2026-12-01")).toMatch(/1/);
    expect(resetLabel("garbage")).toBe("garbage");
    expect([plural(1, "credit", "credits"), plural(3, "credit", "credits")]).toEqual(["1 credit", "3 credits"]);
  });
});
