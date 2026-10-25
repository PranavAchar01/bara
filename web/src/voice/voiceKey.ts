// The visitor's own OpenAI key for voice. Voice models are the one paid part the engine does not
// front. The key lives only in this browser (localStorage) and goes to the engine once, in a POST
// body, to be held in memory for this page's session; later speech requests carry only a random
// session id, never the key. It is never logged.
import { create } from "zustand";
import { authHeaders, serverUrl } from "../net/mode";

const KEY = "voice.openai_key";

interface VoiceKeyState {
  /** A key is saved in this browser. */
  hasKey: boolean;
  /** The engine does not front voice and no key is set, so voice would fall back to the browser. */
  needsKey: boolean;
}

export const useVoiceKey = create<VoiceKeyState>(() => ({ hasKey: storedKey() !== "", needsKey: false }));

function storedKey(): string {
  try {
    return localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

function newSid(): string {
  const a = new Uint8Array(12);
  crypto.getRandomValues(a);
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}

const sid = newSid();
let registered = "";

/** Query fragment that ties speech requests to this page's key; empty without a key. */
export function voiceSid(): string {
  return storedKey() ? `sid=${sid}` : "";
}

/** Add the session id to a speech path. */
export function withVoiceSid(path: string): string {
  const q = voiceSid();
  return q ? `${path}${path.includes("?") ? "&" : "?"}${q}` : path;
}

/** Hand the saved key to the engine (once per value). Never throws. */
export async function registerKey(): Promise<void> {
  const key = storedKey();
  if (key === registered) return;
  try {
    const res = await fetch(serverUrl("/v1/voice/key"), {
      method: "POST",
      headers: { ...authHeaders(), "content-type": "application/json" },
      body: JSON.stringify({ sid, key }),
    });
    if (res.ok) registered = key;
  } catch {
    // the browser's own voice still works
  }
}

/** Save (or, with an empty string, remove) the key in this browser and tell the engine. */
export async function saveKey(key: string): Promise<void> {
  const clean = key.trim();
  try {
    if (clean) localStorage.setItem(KEY, clean);
    else localStorage.removeItem(KEY);
  } catch {
    // private window: the key lasts for this page only through the engine
  }
  useVoiceKey.setState({ hasKey: clean !== "" });
  await registerKey();
}
