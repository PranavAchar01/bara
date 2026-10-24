// Build-time import of the frozen fixtures in ../spec/fixtures. Loaded lazily so
// they land in their own chunk; the real-backend path only needs the demo prompts.
import type { RestFixture, StreamFixture } from "./types";

const streamLoaders = import.meta.glob<StreamFixture>("../../../spec/fixtures/*.json", { import: "default" });
const restLoaders = import.meta.glob<RestFixture>("../../../spec/fixtures/rest/*.json", { import: "default" });

export interface FixtureSet {
  streams: Map<string, StreamFixture>;
  rest: RestFixture[];
}

let cached: Promise<FixtureSet> | null = null;

export function loadFixtures(): Promise<FixtureSet> {
  if (!cached) {
    cached = (async () => {
      const streams = new Map<string, StreamFixture>();
      for (const load of Object.values(streamLoaders)) {
        const f = await load();
        if (f.kind === "stream") streams.set(f.fixture, f);
      }
      const rest: RestFixture[] = [];
      for (const load of Object.values(restLoaders)) rest.push(await load());
      return { streams, rest };
    })();
  }
  return cached;
}

/** Demo prompts for C03: the first match_prompt of each stream fixture that has one. */
export async function demoPrompts(): Promise<{ fixture: string; prompt: string }[]> {
  const { streams } = await loadFixtures();
  const order = [
    "exact_keyboard",
    "compose_wireless_split_oled",
    "clarify_vague_gadget",
    "failed_critical_missing",
  ];
  const out: { fixture: string; prompt: string }[] = [];
  const names = [...streams.keys()].sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  for (const name of names) {
    const p = streams.get(name)?.match_prompts?.[0];
    if (p) out.push({ fixture: name, prompt: p });
  }
  return out;
}
