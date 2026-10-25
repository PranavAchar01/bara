// What a line typed over an open device asks for by its shape alone, for when no model reads it (no key):
// "a mouse next to it" is a device of its own beside this one, "add a knob to it" a part for this one.
// "<verb> <thing> <link> <the build>": beside-links make a device of its own, the rest a part to add
const RELATION =
  /^(?:(?:add|connect|pair|attach|hook up|plug in|plug|make|build|give|design|create|put)\s+(?:me\s+)?)?(?:an?\s+|another\s+|matching\s+|some\s+)*([a-z0-9-]+(?:\s+[a-z0-9-]+){0,3}?)\s+(to go with|that goes with|that pairs with|paired with|next to|beside|alongside|to|with|for|on|onto|in)\s+(?:the|this|my|it|that|our)\b/;
const BESIDE = new Set(["to go with", "that goes with", "that pairs with", "paired with", "next to", "beside", "alongside"]);

/** What a line asks for by its shape alone, for when no model reads it. */
export function relation(text: string): { kind: "companion" | "modify"; thing: string; prompt: string } | null {
  const m = RELATION.exec(text.toLowerCase().replace(/[^a-z0-9\s-]/g, " ").replace(/\s+/g, " ").trim());
  if (!m) return null;
  const thing = m[1].trim();
  return BESIDE.has(m[2]) ? { kind: "companion", thing, prompt: `a ${thing}` } : { kind: "modify", thing, prompt: text };
}
