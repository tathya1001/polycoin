import { describe, expect, it } from "vitest";
import { activeFilters, filterParams, filtersFromUrl, NO_FILTERS } from "./transactionFilters";
import type { Category, DataSource } from "./types";

const CATEGORIES = [{ id: "c-food", name: "Food" }, { id: "c-rent", name: "Rent" }] as Category[];
const SOURCES = [{ id: "s-oak", name: "OakBank" }] as DataSource[];

const url = (text: string) => filtersFromUrl(new URLSearchParams(text));
const query = (filters: Partial<typeof NO_FILTERS>) => filterParams({ ...NO_FILTERS, ...filters }, 1).toString();
const chips = (filters: Partial<typeof NO_FILTERS>) =>
  activeFilters({ ...NO_FILTERS, ...filters }, CATEGORIES, SOURCES).map((chip) => chip.label);

describe("filtersFromUrl", () => {
  it("reads what a chart click sends", () => {
    const filters = url("from=2026-01-01&to=2026-01-31&type=debit&category=c-food&data_source=s-oak,s-river");
    expect(filters).toMatchObject({
      from: "2026-01-01",
      to: "2026-01-31",
      type: "debit",
      categories: ["c-food"],
      sources: ["s-oak", "s-river"],
    });
  });

  it("starts empty", () => {
    expect(url("")).toEqual(NO_FILTERS);
  });

  it("ignores a type it doesn't know", () => {
    expect(url("type=sideways").type).toBe("");
  });
});

describe("filterParams", () => {
  it("sends only what is set", () => {
    expect(query({})).toBe("page=1");
  });

  it("sends each filter under the API's name", () => {
    const params = filterParams(
      { ...NO_FILTERS, name: " cafe ", amountMin: "10", balanceMax: "0", categories: ["a", "b"], sources: ["s"] },
      3,
    );
    expect(Object.fromEntries(params)).toEqual({
      page: "3",
      name: "cafe",
      amount_min: "10",
      balance_max: "0",
      category: "a,b",
      data_source: "s",
    });
  });

  it("leaves out a box holding only spaces", () => {
    expect(query({ notes: "   " })).toBe("page=1");
  });
});

describe("activeFilters", () => {
  it("is empty with no filters", () => {
    expect(chips({})).toEqual([]);
  });

  it("names one category or source, and counts several", () => {
    expect(chips({ categories: ["c-food"] })).toEqual(["Category: Food"]);
    expect(chips({ categories: ["c-food", "c-rent"] })).toEqual(["Category: 2 categories"]);
    expect(chips({ sources: ["s-oak"] })).toEqual(["Source: OakBank"]);
  });

  it("says a range in words", () => {
    expect(chips({ from: "2026-01-01" })).toEqual(["Date from 2026-01-01"]);
    expect(chips({ to: "2026-01-31" })).toEqual(["Date up to 2026-01-31"]);
    expect(chips({ from: "2026-01-01", to: "2026-01-31" })).toEqual(["Date 2026-01-01 to 2026-01-31"]);
  });

  it("gives the amount's type and range a chip each", () => {
    expect(chips({ type: "credit", amountMin: "10" })).toHaveLength(2);
  });

  it("clears only its own filter", () => {
    const [chip] = activeFilters({ ...NO_FILTERS, from: "2026-01-01", to: "2026-01-31" }, [], []);
    expect(chip.clear).toEqual({ from: "", to: "" });
  });

  it("still copes with a number that is still being typed", () => {
    expect(chips({ amountMin: "-" })).toEqual(["Amount from -"]);
  });
});
