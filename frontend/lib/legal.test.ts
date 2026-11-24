import { describe, expect, it } from "vitest";
import { CONTACT_EMAIL, OPERATOR_LOCATION, OPERATOR_NAME, PRIVACY_POLICY_VERSION, policyDate } from "./legal";

describe("the Privacy Policy facts", () => {
  // A release gate: the published policy must name a real person and a working address.
  it("are filled in", () => {
    for (const value of [OPERATOR_NAME, OPERATOR_LOCATION, CONTACT_EMAIL]) {
      expect(value.trim()).not.toBe("");
      expect(value).not.toMatch(/TODO/i);
    }
    expect(CONTACT_EMAIL).toMatch(/^[^\s@]+@[^\s@]+\.[^\s@]+$/);
  });

  it("name the policy by a real date", () => {
    expect(PRIVACY_POLICY_VERSION).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(policyDate(PRIVACY_POLICY_VERSION)).not.toBe("Invalid Date");
    expect(policyDate("2026-11-24")).toBe("24 November 2026");
  });
});
