import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  async redirects() {
    return [
      {
        source: "/docs",
        destination: "/docs/quickstart",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;
