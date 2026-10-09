import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// UX optimisation only: skip rendering the protected pages for browsers with no session cookie.
// This does NOT validate the token (it may be expired, and apiFetch refreshes it).
// Django is still the real gatekeeper for every API call.
export function proxy(request: NextRequest) {
  if (!request.cookies.has("access")) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/transactions/:path*", "/categories/:path*"],
};
