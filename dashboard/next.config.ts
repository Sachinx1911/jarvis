import type { NextConfig } from "next";

// Static export (docs: node_modules/next/dist/docs/01-app/02-guides/static-exports.md, Next 16.4):
// `next build` writes plain HTML/CSS/JS to out/, which FastAPI (jarvis/web/app.py) serves on
// 127.0.0.1 next to the API. No Node server runs in production.
const nextConfig: NextConfig = {
  output: "export",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
