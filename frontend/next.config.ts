import type { NextConfig } from "next";

// Rewrites are compiled at build time, so this must be set before `next build`, not just at runtime.
// On Vercel it must be a plain variable: a Sensitive one reaches the CLI build as a placeholder.
const backend = process.env.BACKEND_INTERNAL_URL?.trim();
if (!backend || !/^https?:\/\//.test(backend)) {
  throw new Error(
    "BACKEND_INTERNAL_URL must be an http(s) URL (e.g. https://polycoin-api.onrender.com). " +
      "On Vercel, add it as a plain variable, not a Sensitive one.",
  );
}

// Content-Security-Policy (Phase 12.2, D6). Everything comes from this site. The only other place
// a page may connect to is the user's own Ollama on this computer (lib/ollama.ts accepts only
// loopback addresses; CSP can't name the IPv6 one, so http://[::1] is refused here). Workers may
// be blob: URLs (the PDF reader). Inline scripts are allowed because Next.js writes small ones
// into every page; a per-request nonce would make every page server-rendered instead of static.
// Even so, injected code can't load another script or send data to another site with fetch.
// Development also needs eval and a websocket for hot reload.
const dev = process.env.NODE_ENV !== "production";
const ollama = ["localhost", "127.0.0.1"].flatMap((host) => [`http://${host}:*`, `https://${host}:*`]);
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${ollama.join(" ")}${dev ? " ws: wss:" : ""}`,
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

// Browser protections for every page. HSTS is added by Vercel itself.
const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*/`,
      },
    ];
  },
};

export default nextConfig;
