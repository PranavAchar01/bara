/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// BARA_SERVER=https://<tunnel> pnpm dev proxies /v1 and /assets to a remote server, so no local server or models are needed.
const backend = process.env.BARA_SERVER ?? "http://127.0.0.1:8790";
const repoRoot = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    fs: { allow: [repoRoot] },
    proxy: {
      "/v1": { target: backend, ws: true, changeOrigin: true },
      "/assets": { target: backend, changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 1600,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
