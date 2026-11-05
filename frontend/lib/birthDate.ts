// The date of birth, asked at sign-up and by components/auth/AgeGate.tsx. The server decides
// (accounts/services.py): 18 or older, born no earlier than 1900.

export const BIRTH_DATE_HINT = "You must be 18 or older. Stored encrypted, and used only to confirm your age.";
export const EARLIEST_BIRTH_DATE = "1900-01-01";
