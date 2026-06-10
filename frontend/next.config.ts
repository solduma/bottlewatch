import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // API requests go straight to uvicorn in dev. In production, set
  // NEXT_PUBLIC_API_BASE in the deploy env to the public API URL.
};

export default nextConfig;
