import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    root: ".",
  },
  async rewrites() {
    let apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    if (apiUrl && !apiUrl.startsWith("http://") && !apiUrl.startsWith("https://") && !apiUrl.startsWith("/")) {
      apiUrl = `https://${apiUrl}`;
    }
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
