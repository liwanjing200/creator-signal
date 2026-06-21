import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: { root: process.cwd() },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.hdslb.com" },
      { protocol: "https", hostname: "**.douyinpic.com" },
      { protocol: "https", hostname: "**.byteimg.com" }
    ]
  }
};

export default nextConfig;
