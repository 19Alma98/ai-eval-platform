import { PHASE_DEVELOPMENT_SERVER } from "next/constants";
import type { NextConfig } from "next";

/**
 * Sub-path the UI is served under behind a reverse proxy (e.g. "/opengrade"), fixed at
 * build time. The proxy strips it before forwarding, so FastAPI still serves `/`.
 */
const basePath = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "") || undefined;

/**
 * One build: a static export that FastAPI serves (packaged into opengrade_server/_ui,
 * used by both `opengrade ui` and the Docker image). `next dev` proxies the API instead.
 */
export default function nextConfig(phase: string): NextConfig {
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";
    return {
      basePath,
      experimental: { proxyTimeout: 600_000 },
      async rewrites() {
        return [
          { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
          { source: "/health", destination: `${apiOrigin}/health` },
        ];
      },
    };
  }
  return {
    output: "export",
    basePath,
    images: { unoptimized: true },
    trailingSlash: true,
  };
}
