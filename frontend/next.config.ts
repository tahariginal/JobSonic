import type { NextConfig } from "next";

// Static export: the dashboard is plain files served by the FastAPI process (one service, same origin).
const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};
// `next dev` only: forward API calls to the local backend (rewrites are not part of a static export)
if (process.env.NODE_ENV === "development") {
  config.output = undefined;
  config.rewrites = async () => [{ source: "/api/:path*", destination: "http://127.0.0.1:8790/api/:path*" }];
}
export default config;
