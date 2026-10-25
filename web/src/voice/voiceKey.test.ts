import { beforeEach, describe, expect, it, vi } from "vitest";
import { saveKey, voiceSid, withVoiceSid } from "./voiceKey";

describe("voice key", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  });

  it("adds a session id only when a key is saved, and never puts the key in a URL", async () => {
    expect(withVoiceSid("/v1/tts?text=hi")).toBe("/v1/tts?text=hi");
    await saveKey("sk-secret");
    expect(voiceSid()).toMatch(/^sid=[0-9a-f]{24}$/);
    expect(withVoiceSid("/v1/tts?text=hi")).toContain("&sid=");
    expect(withVoiceSid("/v1/voice")).not.toContain("sk-secret");
    await saveKey("");
    expect(withVoiceSid("/v1/voice")).toBe("/v1/voice");
  });

  it("sends the key once in a POST body", async () => {
    await saveKey("sk-secret");
    const call = vi.mocked(fetch).mock.calls[0];
    expect(String(call[0])).toContain("/v1/voice/key");
    expect(String(call[1]?.body)).toContain("sk-secret");
  });
});
