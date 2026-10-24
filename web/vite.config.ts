/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";

// BARA_SERVER=https://<tunnel> pnpm dev proxies /v1 and /assets to a remote server, so no local server or models are needed.
// BARA_SERVER=auto uses the tunnel URL that scripts/serve-public.sh last published (api/engine.ts);
// that engine checks the access key, so open the page with ?key=... once.
const repoRoot = fileURLToPath(new URL("..", import.meta.url));

async function resolveBackend(): Promise<string> {
  const want = process.env.BARA_SERVER;
  if (want !== "auto") return want ?? "http://127.0.0.1:8790";
  const src = readFileSync(new URL("./api/engine.ts", import.meta.url), "utf8");
  const url = /const ENGINE_URL: string = "([^"]*)";/.exec(src)?.[1];
  if (!url) throw new Error("BARA_SERVER=auto: no engine published in api/engine.ts");
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
