/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

// BARA_SERVER=https://<tunnel> pnpm dev proxies /v1 and /assets to a remote server, so no local server or models are needed.
// BARA_SERVER=auto asks the deployed site which tunnel serve-public.sh published (falling back to
// api/engine.ts in this checkout). The proxy adds the access key itself: BARA_ACCESS_TOKEN, else the
// macOS keychain item bara-access-token. The key stays in memory only.
const SITE = "https://bara-ivory-five.vercel.app";
const repoRoot = fileURLToPath(new URL("..", import.meta.url));

function accessKey(): string | null {
  if (process.env.BARA_ACCESS_TOKEN) return process.env.BARA_ACCESS_TOKEN;
  try {
    return execFileSync("security", ["find-generic-password", "-a", "pranav", "-s", "bara-access-token", "-w"], { encoding: "utf8" }).trim() || null;
  } catch {
    return null;
  }
}

async function resolveBackend(key: string | null): Promise<string> {
  const want = process.env.BARA_SERVER;
  if (want !== "auto") return want ?? "http://127.0.0.1:8790";
  if (key) {
    try {
      const res = await fetch(`${SITE}/api/engine`, { headers: { "x-bara-token": key } });
      if (res.ok) return ((await res.json()) as { url: string }).url;
    } catch {
      // offline: use the pointer in this checkout
    }
  }
  const src = readFileSync(new URL("./api/engine.ts", import.meta.url), "utf8");
  const url = /const ENGINE_URL: string = "([^"]*)";/.exec(src)?.[1];
  if (!url) throw new Error("BARA_SERVER=auto: no engine published");
  return url;
}

export default defineConfig(async () => {
  const key = process.env.BARA_SERVER ? accessKey() : null;
  const backend = await resolveBackend(key);
  const headers = key ? { "x-bara-token": key } : undefined;
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      fs: { allow: [repoRoot] },
      proxy: {
        "/v1": { target: backend, ws: true, changeOrigin: true, headers },
        "/assets": { target: backend, changeOrigin: true, headers },
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
