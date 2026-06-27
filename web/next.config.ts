import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  // Exports each route as {route}/index.html instead of {route}.html, so
  // FastAPI's StaticFiles(html=True) can serve a hard refresh on e.g.
  // /overview directly (it resolves directory requests to index.html).
  trailingSlash: true,
};

export default nextConfig;
