// What a line typed over an open device asks for by its shape alone, for when no model reads it (no key,
// engine unreachable); the engine reads the same shapes (server/src/bara/intent.py read_shape). "a mouse
// next to it", "add a mouse to this keyboard", "connect a mouse", "make a matching mouse" are a device of
// its own made for this one; "add a knob to it" is a part for this one.
import { deviceKindOf } from "../project/deviceKind";

const VERB = "(?:add|connect|pair|attach|hook up|plug in|plug|make|build|give|design|create|put|want|need)";
const WANT = "(?:i (?:want|need|would like) to )?";
const ARTICLES = "(?:(?:an?|another|matching|some|new|second)\\s+)*";
const REF = "(?:the|this|my|it|that|our)\\b";
const BESIDE = ["to go with", "that goes with", "that pairs with", "paired with", "next to", "beside", "alongside", "that matches", "to match"];
const LINKS = [...BESIDE, "for", "to", "with", "on", "onto", "in"];
// "<verb> <thing> <link> <the build>"
const SHAPE = new RegExp(
  `^${WANT}(?:${VERB}\\s+)?(?:(?:me|us)\\s+)?${ARTICLES}([a-z0-9-]+(?:\\s+[a-z0-9-]+){0,3}?)(?:\\s+(${LINKS.join("|")})\\s+${REF}.*)?$`,
);
// "connect this keyboard to a mouse": the open device first, the new one after the link
const REVERSE = new RegExp(`^${WANT}${VERB}\\s+${REF}(?:\\s+[a-z0-9-]+){0,3}?\\s+(?:to|with|and)\\s+${ARTICLES}([a-z0-9-]+(?:\\s+[a-z0-9-]+){0,3})$`);

export interface Relation {
  kind: "companion" | "modify";
  thing: string;
  prompt: string;
}

/** What a line asks for by its shape alone, for when no model reads it. */
export function relation(text: string): Relation | null {
  const t = text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^(?:(?:please|can you|could you|now|and|also|then|ok|okay)\s+)+/, "");
  const rev = REVERSE.exec(t);
  if (rev && deviceKindOf(rev[1])) return { kind: "companion", thing: rev[1].trim(), prompt: `a ${rev[1].trim()}` };
  const m = SHAPE.exec(t);
  if (!m) return null;
  const thing = m[1].trim();
  const link = m[2];
  if (new RegExp(`^${REF}`).test(thing)) return null; // "connect this keyboard to the wifi" is about this one
  const matched = /\b(?:matching|another|second)\b/.test(t);
  const verb = new RegExp(`^${WANT}${VERB}\\b`).test(t);
  if ((link && BESIDE.includes(link)) || (deviceKindOf(thing) && (verb || !!link || matched))) return { kind: "companion", thing, prompt: `a ${thing}` };
  return link ? { kind: "modify", thing, prompt: text } : null;
}
