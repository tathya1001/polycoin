// Who runs MoneyAngle and how to reach them, as the Privacy Policy states it. One place, so the
// policy page, the sign-up form and the footer links agree.

// The policy's "last updated" date, which is also its version. Must equal PRIVACY_POLICY_VERSION
// in backend/config/settings.py, which records the version each new account accepted. Change
// both whenever the policy text changes.
export const PRIVACY_POLICY_VERSION = "2026-11-24";

// The one person who owns and runs MoneyAngle and answers every privacy request, with a contact
// address. Indian law asks for a real name and contact details on the policy. legal.test.ts fails
// if any of these is ever left as a placeholder, so an unfinished policy can't pass CI.
export const OPERATOR_NAME = "Tathya Patel";
export const OPERATOR_LOCATION = "Hyderabad, Telangana";
export const CONTACT_EMAIL = "tathya1001@gmail.com";

export const PRIVACY_POLICY_PATH = "/privacy";

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

/** "24 November 2026", from a "2026-11-24" version. */
export function policyDate(version: string = PRIVACY_POLICY_VERSION): string {
  return DATE_FORMAT.format(new Date(`${version}T00:00:00Z`));
}
