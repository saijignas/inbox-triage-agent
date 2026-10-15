import path from "node:path";
import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Pin the tracing root to this folder so a stray lockfile in a parent directory can't change it.
  outputFileTracingRoot: path.dirname(fileURLToPath(import.meta.url)),
};

export default nextConfig;
