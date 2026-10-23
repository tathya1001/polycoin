import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// UX optimisation only: skip rendering pages for browsers with the wrong session state.
// This does NOT validate the token (it may be expired, and apiFetch refreshes it).
// Django is still the real gatekeeper for every API call.
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Production only: forward /api/* to Django with a shared secret, so Django can refuse
  // requests that skip this site (direct calls to Render could otherwise set their own
  // X-Forwarded-For to dodge throttling). ORIGIN_SECRET has no NEXT_PUBLIC_ prefix, so it stays
  // on the server and never reaches the browser. Without it (local development) the request
  // falls through to the rewrite in next.config.ts.
  if (pathname.startsWith("/api/")) {
    const secret = process.env.ORIGIN_SECRET;
    const backend = process.env.BACKEND_INTERNAL_URL;
    if (!secret || !backend) return NextResponse.next();

    const headers = new Headers(request.headers);
    headers.set("x-origin-secret", secret);
    // Django's URLs end in a slash and next.config.ts has trailing-slash redirects off.
    const slash = pathname.endsWith("/") ? "" : "/";
    return NextResponse.rewrite(new URL(`${backend}${pathname}${slash}${request.nextUrl.search}`), {
      request: { headers },
    });
  }

  const signedIn = request.cookies.has("access");

  // The home page is for visitors; signed-in users go straight to their dashboard.
  if (pathname === "/") {
    return signedIn ? NextResponse.redirect(new URL("/dashboard", request.url)) : NextResponse.next();
  }
  if (!signedIn) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Must be a literal: Next reads it at build time.
  matcher: [
    "/",
    "/api/:path*",
    "/dashboard/:path*",
    "/ask/:path*",
    "/transactions/:path*",
    "/categories/:path*",
    "/settings/:path*",
  ],
};
