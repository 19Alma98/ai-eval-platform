import type { NextConfig } from "next";

const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";
const isUiExport = process.env.AIOBS_UI_EXPORT === "1";

const nextConfig: NextConfig = {
  output: isUiExport ? "export" : "standalone",
  ...(isUiExport
    ? {
        images: { unoptimized: true },
        trailingSlash: true,
      }
    : {
        experimental: {
          proxyTimeout: 600_000,
        },
        async rewrites() {
          return [
            { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
            { source: "/health", destination: `${apiOrigin}/health` },
          ];
        },
      }),
};

export default nextConfig;
