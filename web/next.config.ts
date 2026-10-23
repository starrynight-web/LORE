import type { NextConfig } from "next";

const port = process.env.LORE_API_PORT || "7421";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `http://127.0.0.1:${port}/api/:path*`,
      },
      {
        source: "/graph/view",
        destination: `http://127.0.0.1:${port}/graph/view/`,
      },
      {
        source: "/graph/view/:path*",
        destination: `http://127.0.0.1:${port}/graph/view/:path*`,
      },
    ];
  },
};

export default nextConfig;
