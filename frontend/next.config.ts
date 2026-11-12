import type { NextConfig } from "next";

// Default: static export. The dashboard is plain files served by the FastAPI process (one service, same origin).
const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};

// Hosted mode (Vercel): the pages are served by the host and /api/* is forwarded to the backend on the
// server, so the browser still sees one origin and the session cookie keeps working. The backend address
// comes from the environment so it is never written in this repository.
const apiOrigin = (process.env.SONIC_API_ORIGIN ?? "").trim().replace(/\/+$/, "");
if (process.env.VERCEL && !apiOrigin) {
  throw new Error("SONIC_API_ORIGIN is not set. Add it in the Vercel project settings (see host_front_back.md).");
}
if (apiOrigin) {
  if (!/^https?:\/\/[^/]+$/.test(apiOrigin)) {
    throw new Error("SONIC_API_ORIGIN must look like https://host with no path.");
  }
  config.output = undefined;
  // API paths have no trailing slash; without this they would be redirected before being forwarded.
  config.skipTrailingSlashRedirect = true;
  config.rewrites = async () => [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  // Same headers the FastAPI process sets when it serves the pages itself.
  config.headers = async () => [
    {
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        {
          key: "Content-Security-Policy",
          value:
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; " +
            "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; " +
            "base-uri 'self'; form-action 'self'; object-src 'none'",
        },
      ],
    },
  ];
} else if (process.env.NODE_ENV === "development") {
  // `next dev` only: forward API calls to the local backend (rewrites are not part of a static export)
  config.output = undefined;
  config.rewrites = async () => [{ source: "/api/:path*", destination: "http://127.0.0.1:8790/api/:path*" }];
}
export default config;
