// DRF error bodies come in two shapes:
//   {"detail": "message"}                    (our 409/400 responses, throttling)
//   {"field": ["message", ...], ...}         (serializer validation)
// Pull out one human-readable message, or fall back to a generic one.
export async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    for (const value of Object.values(body ?? {})) {
      if (Array.isArray(value) && typeof value[0] === "string") return value[0];
    }
  } catch {
    // not JSON: use the fallback
  }
  return fallback;
}
