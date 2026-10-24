// Finding the build engine from the deployed site. The engine runs on Pranav's Mac behind a tunnel
// whose URL changes; /api/engine (a Vercel function) hands that URL out. The engine is open to
// anyone with the site; a key is sent only when one was entered (an engine started with one).
import { readServer, withToken } from "./mode";

export type EngineState = "local" | "checking" | "live" | "offline" | "locked";

export type Discovery =
  | { state: "live"; url: string }
  | { state: "locked"; detail: string }
  | { state: "offline"; detail: string };

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

const PROBE_MS = 8000;

function timeout(ms: number): AbortSignal | undefined {
  return typeof AbortSignal !== "undefined" && "timeout" in AbortSignal ? AbortSignal.timeout(ms) : undefined;
}

export async function discoverEngine(key: string | null, fetchFn: Fetch = fetch): Promise<Discovery> {
  let url: string | null;
  try {
    const res = await fetchFn("/api/engine", { headers: key ? { "x-bara-token": key } : {}, cache: "no-store", signal: timeout(PROBE_MS) });
    if (res.status === 401) return { state: "locked", detail: "That access key was not accepted." };
    if (!res.ok) return { state: "offline", detail: "No engine is published right now." };
    url = readServer(((await res.json()) as { url?: string }).url);
  } catch {
    return { state: "offline", detail: "Could not reach the site's engine lookup." };
  }
  if (!url) return { state: "offline", detail: "No engine is published right now." };
  try {
    const res = await fetchFn(withToken(`${url}/v1/vocab`, key), { cache: "no-store", signal: timeout(PROBE_MS) });
    if (res.status === 401) return { state: "locked", detail: "The engine did not accept that access key." };
    if (!res.ok) return { state: "offline", detail: `The engine answered ${res.status}.` };
    return { state: "live", url };
  } catch {
    return { state: "offline", detail: "The engine on the Mac is not answering (server or tunnel stopped)." };
  }
}
