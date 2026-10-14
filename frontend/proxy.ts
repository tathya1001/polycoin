import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// UX optimisation only: skip rendering pages for browsers with the wrong session state.
// This does NOT validate the token (it may be expired, and apiFetch refreshes it).
// Django is still the real gatekeeper for every API call.
export function proxy(request: NextRequest) {
  const signedIn = request.cookies.has("access");

  // The home page is for visitors; signed-in users go straight to their dashboard.
  if (request.nextUrl.pathname === "/") {
    return signedIn ? NextResponse.redirect(new URL("/dashboard", request.url)) : NextResponse.next();
  }
  if (!signedIn) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Must be a literal: Next reads it at build time.
  matcher: ["/", "/dashboard/:path*", "/transactions/:path*", "/categories/:path*", "/settings/:path*"],
};
