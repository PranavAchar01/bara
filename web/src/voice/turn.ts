// What a spoken turn means once it is heard: the ums, stutters and repeats taken out, and how long a
// pause has to last before Bara takes it as the end of the turn. Pure, so it is easy to test.

const FILLER = "(?:u+h+m*|u+m+|e+r+m+|e+r+|a+h+|h+m+|m+h*m+|mhm)";
const FILLERS = new RegExp(`(^|[\\s,])${FILLER}(?=[\\s,.!?]|$),?`, "gi");
const FILLER_WORD = new RegExp(`^${FILLER}$`, "i");
/** Words that say more is coming: a pause after one of these is a breath, not the end. */
const HANGING = new Set([
  "and", "or", "but", "so", "with", "without", "the", "a", "an", "to", "of", "for", "in", "on", "at",
  "that", "which", "like", "maybe", "then", "plus", "also", "because", "if", "my", "some", "its", "it's",
  "is", "are", "can", "could", "would", "should", "want", "need", "make", "build",
]);

/** The transcript as it was meant: fillers, stutters ("k- keyboard") and repeats ("the the") removed. */
export function cleanTranscript(raw: string): string {
  let t = ` ${raw} `;
  t = t.replace(FILLERS, "$1");
  // false starts cut off mid-word: "wi- wireless", "k-k-keyboard"
  t = t.replace(/\b([a-z]{1,4})-\s*(?:\1-\s*)*(?=\1)/gi, "");
  // a word or a two-word phrase said twice or more in a row: "I I want", "I want I want"
  t = t.replace(/\b([a-z']+\s+[a-z']+)(?:[\s,]+\1\b)+/gi, "$1");
  t = t.replace(/\b([a-z']+)(?:[\s,]+\1\b)+/gi, "$1");
  t = t
    .replace(/\s+([,.!?])/g, "$1")
    .replace(/([,.!?])[,]+/g, "$1")
    .replace(/^[\s,]+|[\s,]+$/g, "")
    .replace(/\s{2,}/g, " ");
  return t ? t[0].toUpperCase() + t.slice(1) : "";
}

/** How long a silence ends the turn, given what has been said so far. Null: nothing said yet. */
export function endOfTurnMs(heard: string): number | null {
  const t = heard.trim();
  if (!t) return null;
  if (/[.!?]$/.test(t)) return 600;
  const words = t.toLowerCase().split(/\s+/);
  const last = words[words.length - 1].replace(/[^a-z']/g, "");
  if (HANGING.has(last) || FILLER_WORD.test(last)) return 1700;
  return words.length < 3 ? 1100 : 850;
}
