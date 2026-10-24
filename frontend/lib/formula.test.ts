import { describe, expect, it } from "vitest";
import catalogueJson from "./__fixtures__/catalogue.json";
import {
  DEFAULT_FORMULA,
  bindingAllowed,
  calcAllowed,
  defaultConfig,
  formatValue,
  formulaAllowed,
  isPercent,
  isPlainNumber,
  normalizeConfig,
} from "./insights";
import type { Catalogue, FormulaForm, PanelConfig } from "./types";

const catalogue = catalogueJson as unknown as Catalogue;

function formula(chart: PanelConfig["chart"] = "bar", as: FormulaForm = "percent", expression = "income - spend") {
  return normalizeConfig(
    { ...defaultConfig(chart), y: { measure: "formula", agg: "sum", formula: { expression, as } } },
    catalogue,
  );
}

describe("a calculated field in the editor draft", () => {
  it("is kept on the charts that allow it, with the catalogue's aggregation", () => {
    for (const chart of ["bar", "line", "area", "kpi"] as const) {
      const config = formula(chart);
      expect(config.y).toEqual({ measure: "formula", agg: "avg", formula: { expression: "income - spend", as: "percent" } });
    }
  });

  it("falls back to an ordinary measure on a chart that can't take one", () => {
    for (const chart of ["pie", "donut", "histogram", "calendar", "heatmap"] as const) {
      const config = formula(chart);
      expect(config.y.measure).not.toBe("formula");
      expect(config.y.formula).toBeUndefined();
    }
  });

  it("starts from the default formula when there is none yet", () => {
    const config = normalizeConfig({ ...defaultConfig("bar"), y: { measure: "formula", agg: "sum" } }, catalogue);
    expect(config.y.formula).toEqual(DEFAULT_FORMULA);
  });

  it("drops the formula when the measure changes", () => {
    const changed = normalizeConfig({ ...formula(), y: { ...formula().y, measure: "spend" } }, catalogue);
    expect(changed.y).toEqual({ measure: "spend", agg: "avg" });
  });

  it("keeps the text as typed (the server tidies it) but within the length limit", () => {
    const typed = formula("bar", "number", "income  -  ");
    expect(typed.y.formula?.expression).toBe("income  -  ");
    const long = formula("bar", "number", "1+".repeat(200));
    expect(long.y.formula?.expression).toHaveLength(catalogue.formula.max_length);
  });

  it("replaces an unknown result form", () => {
    expect(formula("bar", "words" as FormulaForm).y.formula?.as).toBe("number");
  });

  it("is only offered where the backend allows it", () => {
    expect(formulaAllowed("bar", catalogue)).toBe(true);
    expect(formulaAllowed("pie", catalogue)).toBe(false);
  });
});

describe("what a calculated field can be combined with", () => {
  it("cannot follow the dashboard's measure parameter", () => {
    expect(bindingAllowed(formula(), "measure")).toBe(false);
    expect(bindingAllowed(normalizeConfig(defaultConfig("bar"), catalogue), "measure")).toBe(true);
  });

  it("allows a moving average and a change, but not a running total or a share of the total", () => {
    const line = formula("line");
    expect(calcAllowed(line, catalogue, "moving_average")).toBe(true);
    expect(calcAllowed(line, catalogue, "change")).toBe(true);
    expect(calcAllowed(line, catalogue, "running_total")).toBe(false);
    expect(calcAllowed(line, catalogue, "percent_of_total")).toBe(false);
  });
});

describe("how a calculated field's values read", () => {
  it("as a percentage", () => {
    const config = formula("bar", "percent");
    expect(isPercent(config)).toBe(true);
    expect(formatValue("33.33", config)).toBe("33.3%");
  });

  it("as a plain number, without a ₹ sign", () => {
    const config = formula("bar", "number");
    expect(isPlainNumber(config)).toBe(true);
    expect(formatValue("1234.567", config)).toBe("1,234.57");
  });

  it("as money", () => {
    const config = formula("bar", "money");
    expect(isPercent(config)).toBe(false);
    expect(isPlainNumber(config)).toBe(false);
    expect(formatValue("1234.5", config)).toBe("₹1,234.50");
  });

  it("keeps its own unit under a moving average or a change as an amount", () => {
    const averaged = { ...formula("line", "percent"), calc: { type: "moving_average" as const, window: 3 } };
    expect(formatValue("12.5", averaged)).toBe("12.5%");
    const byAmount = { ...formula("line", "money"), calc: { type: "change" as const, vs: "previous" as const, as: "amount" as const } };
    expect(formatValue("50", byAmount)).toBe("₹50.00");
  });

  it("reads a change as a percentage when the change is shown as one", () => {
    const changed = { ...formula("line", "money"), calc: { type: "change" as const, vs: "previous" as const, as: "percent" as const } };
    expect(formatValue("10", changed)).toBe("10%");
  });

  it("shows no value as a dash", () => {
    expect(formatValue(null, formula())).toBe("–");
  });
});
