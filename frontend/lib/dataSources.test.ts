import { describe, expect, it } from "vitest";
import { knownSources, sourceName, sourceRef } from "@/lib/dataSources";
import type { DataSource } from "@/lib/types";

const KEYWORDS = ["IF", "THEN", "END"];

function source(id: string, name: string): DataSource {
  return { id, name, color: "#2A78D6", position: 0, transactions: 0, first_date: null, last_date: null, balance: null };
}

describe("sourceRef", () => {
  it("leaves one plain word as it is", () => {
    expect(sourceRef("OakBank", KEYWORDS)).toBe("OakBank");
    expect(sourceRef("oak_2", KEYWORDS)).toBe("oak_2");
  });

  it("puts anything else in brackets", () => {
    expect(sourceRef("Oak Salary", KEYWORDS)).toBe("[Oak Salary]");
    expect(sourceRef("2024 Savings", KEYWORDS)).toBe("[2024 Savings]");
    expect(sourceRef("If", KEYWORDS)).toBe("[If]");
  });
});

describe("knownSources", () => {
  it("drops an id that no longer exists", () => {
    expect(knownSources(["a", "gone"], [source("a", "Oak")])).toEqual(["a"]);
  });
});

describe("sourceName", () => {
  it("finds the name, or nothing", () => {
    expect(sourceName("a", [source("a", "Oak")])).toBe("Oak");
    expect(sourceName("b", [source("a", "Oak")])).toBe("");
  });
});
