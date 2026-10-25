// What a spoken turn means once it is heard: the ums, stutters and repeats taken out, and how long a
// pause has to last before Bara takes it as the end of the turn. Pure, so it is easy to test.

// "mm" alone is millimetres here, so only a long "mmm" or "mhm" counts as a filler
const FILLER = "(?:u+h+m*|u+m+|e+r+m+|e+r+|a+h+|h+m+|m{3,}|m+h+m+)";
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

// "the second one": the place word wins over the "one" that rides along with it
const ORDINALS = [/\b(first|1st)\b/, /\b(second|2nd)\b/, /\b(third|3rd)\b/, /\b(fourth|4th)\b/];
const NUMBERS = [/\b(one|1)\b/, /\b(two|2)\b/, /\b(three|3)\b/, /\b(four|4)\b/];

/** Which of Bara's offered answers a spoken reply means: by its words ("the wireless one") or its
 *  place ("the second one"). Null when it is neither, so it goes as free text. */
export function pickOption(spoken: string, options: { option_id: string; label: string }[]): string | null {
  const said = spoken.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  if (!said) return null;
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const byLabel = options.find((o) => {
    const l = norm(o.label);
    return l && (said.includes(l) || (said.length > 3 && l.includes(said)));
  });
  if (byLabel) return byLabel.option_id;
  for (const list of [ORDINALS, NUMBERS]) {
    const at = list.slice(0, options.length).findIndex((re) => re.test(said));
    if (at >= 0) return options[at].option_id;
  }
  return null;
}

/** What speech-to-text tends to make up from a cough, a click or near-silence. */
// ("okay", "yes" and the like are left alone: they are real answers to Bara's questions)
const PHANTOMS = /^(thank you|thanks|thanks for watching|thank you for watching|thank you so much for watching|you|bye|bye bye|the end|subtitles by .*|\.+)$/i;

/** A transcript that is most likely invented from noise: one of the phantom phrases, from barely any
 *  speech. A real "thank you" said at length still goes through. */
export function isNoise(text: string, loudMs: number): boolean {
  const t = text.trim().replace(/[.!?,]+$/g, "").trim();
  return !t || (PHANTOMS.test(t) && loudMs < 900);
}
