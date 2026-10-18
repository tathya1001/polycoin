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

// Baseline browser protections for every page. HSTS is added by Vercel itself. A full
// Content-Security-Policy is a separate piece of work (Next and ECharts both use inline styles).
const securityHeaders = [
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
