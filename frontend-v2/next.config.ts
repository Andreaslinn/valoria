import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  // Radar's real evaluation can exceed Next's default 30s proxy limit.
  // Keep transport open beyond the API client's bounded 120s request budget.
  experimental: { proxyTimeout: 130000 },
  distDir: process.env.NODE_ENV === "development" ? ".next-dev" : ".next",
  async rewrites() {
    const api = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
    // Same-origin transport: preserve FastAPI routes and bearer auth without changing backend CORS.
    return [{ source: "/backend/:path*", destination: `${api}/:path*` }];
  },
};

export default nextConfig;
