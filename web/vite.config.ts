/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// BARA_SERVER=https://<tunnel> pnpm dev proxies /v1 and /assets to a remote server, so no local server or models are needed.
// BARA_SERVER=auto reads the current tunnel URL that scripts/tunnel.sh publishes to the deployed site.
const PUBLISHED = "https://bara-ivory-five.vercel.app/server.json";
const repoRoot = fileURLToPath(new URL("..", import.meta.url));

async function resolveBackend(): Promise<string> {
  const want = process.env.BARA_SERVER;
  if (want !== "auto") return want ?? "http://127.0.0.1:8790";
  const res = await fetch(PUBLISHED, { cache: "no-store" });
  const { url } = (await res.json()) as { url: string };
  return url;
}

export default defineConfig(async () => {
  const backend = await resolveBackend();
  return {
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
  };
});
