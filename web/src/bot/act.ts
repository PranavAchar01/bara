// What a line typed (or said) in the workspace does, so the one prompt does everything and never throws
// a build away. In order: a change to a part (swap, recolour, move, rotate, remove) goes to the part in
// focus or the one the line names; a question gets a short answer; "add a knob" adds a part from the
// catalog; "a mouse next to it" starts a second device beside this one; anything else is a new device on
// a new canvas. Bara answers each in one short line (baraSay) and acts edits out on the canvas.
import { addCanvas, addCompanionCanvas } from "../state/canvases";
import { baraSay, useApp } from "../state/store";
import { applyEdit, getRest, startBuild } from "../net/client";
import { paths } from "../net/rest";
import type { Build, BuildPart, EditOp, PartsPage } from "../spec/types";
import { focusKeyOf } from "../three/Viewport3D";
import { speak } from "../voice/voice";
import { loadOptions } from "./AskBot";
import { parseAsk, resolveAsk } from "./ask";

/** Words that point at what is already on the canvas ("make it blue", "the keycaps"). */
const REFERS = /\b(it|its|this|that|these|those|the|my)\b/;
const STARTS_FRESH = /^(new|start over|start again|instead,?)\b/;
/** "Build around the Cherry MX2A Brown: a 40% board" (the pill's Build around it). */
const AROUND = /^build around (?:the )?(.+?):\s*(.*)$/i;

function say(text: string): void {
  baraSay(text);
  speak(text);
}

function singular(w: string): string {
  return w.endsWith("es") && w.length > 4 ? w.slice(0, -2) : w.endsWith("s") && w.length > 3 ? w.slice(0, -1) : w;
}

/**
 * The part a line is about: the one in focus or selected, else the slot or part it names ("the keycaps",
 * "the knob"). `all` is every instance in that slot, so "make the keycaps blue" means every keycap.
 */
export function targetOf(build: Build, text: string): { inst: BuildPart; all: BuildPart[] } | null {
  const s = useApp.getState();
  const words = new Set(text.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean).map(singular));
  const named = (label: string) => label.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 2).map(singular).some((w) => words.has(w));
  for (const slot of build.slots ?? []) {
    if (!named(slot.label)) continue;
    const all = build.parts.filter((p) => p.slot_id === slot.slot_id);
    if (all.length) return { inst: all[0], all };
  }
  const byName = build.parts.find((p) => named(p.card.display_name));
  if (byName) return { inst: byName, all: [byName] };
  const focused = s.focusKey ? build.parts.filter((p) => focusKeyOf(build, p) === s.focusKey) : [];
  if (focused.length) return { inst: focused[0], all: focused };
  const sel = build.parts.find((p) => p.instance_id === s.selection);
  return sel ? { inst: sel, all: [sel] } : null;
}

/** Recolouring or removing a slot by name means every part in it, not just the first. */
function widen(ops: EditOp[], all: BuildPart[]): EditOp[] {
  if (all.length < 2 || ops.length !== 1) return ops;
  const op = ops[0];
  if (op.op === "recolor" && op.instance_id) return all.map((p) => ({ ...op, instance_id: p.instance_id }));
  if (op.op === "remove_part") return all.map((p) => ({ op: "remove_part" as const, instance_id: p.instance_id }));
  return ops;
}

/** A new device, never over the one on screen: a fresh canvas when this one is in use. */
function newDevice(prompt: string): void {
  if (useApp.getState().build) addCanvas();
  startBuild(prompt);
}

/** The catalog's best part for "a knob", "an OLED screen": the whole phrase, then its words, longest first. */
async function findPart(thing: string): Promise<PartsPage["items"][number] | undefined> {
  const words = thing.split(/\s+/).filter((w) => w.length > 2).sort((a, b) => b.length - a.length);
  for (const q of [thing, ...(words.length > 1 ? words : [])]) {
    const res = await getRest().get<PartsPage>(paths.parts(q));
    const card = res.ok ? res.body.items?.[0] : undefined;
    if (card) return card;
  }
  return undefined;
}

async function addPart(thing: string): Promise<boolean> {
  const card = await findPart(thing);
  if (!card) return false;
  applyEdit([{ op: "add_part", part_id: card.part_id }], `Add ${card.display_name}`);
  say(`Adding the ${card.display_name}.`);
  return true;
}

export async function act(raw: string): Promise<void> {
  const text = raw.trim();
  if (!text) return;
  const s = useApp.getState();
  const build = s.build;
  // nothing finished on screen (an empty canvas, a build still running): it is a build to start
  if (!build || build.status !== "done" || s.mode.mock) {
    if (build && (build.status === "running" || build.status === "awaiting_input")) newDevice(text);
    else startBuild(text);
    return;
  }
  const lower = text.toLowerCase();
  if (STARTS_FRESH.test(lower)) return newDevice(text.replace(STARTS_FRESH, "").trim() || text);
  const around = AROUND.exec(text);
  if (around) {
    // a bigger thing grown from this part: its own device, standing beside this one
    const [, part, what] = around;
    addCompanionCanvas();
    startBuild(`${what.trim() || "a device"} built around the ${part}`);
    say(`Building ${what.trim() || "something"} around the ${part}.`);
    return;
  }

  const intent = parseAsk(text);
  const target = targetOf(build, text);
  if (target && intent.kind !== "unknown") {
    const options = intent.kind === "swap" ? await loadOptions(build.build_id, target.inst) : [];
    const out = resolveAsk(intent, { build, instance: target.inst, options });
    if (out.kind === "edit") {
      applyEdit(widen(out.ops, target.all), out.label);
      say(out.short);
    } else say(out.say);
    return;
  }

  // a second device, or a part to add, as the engine reads the line
  const r = await getRest().request<{ kind: string; thing: string | null; prompt: string }>("POST", "/v1/intent", {
    prompt: text,
    has_build: true,
    build_prompt: build.prompt,
    part_names: build.parts.map((p) => p.label ?? p.card.display_name),
  });
  if (r.ok && r.body.kind === "companion") {
    addCompanionCanvas();
    startBuild(r.body.prompt);
    say(`Starting a ${r.body.thing ?? "device"} next to this one.`);
    return;
  }
  if (r.ok && r.body.kind === "modify" && r.body.thing) {
    if (await addPart(r.body.thing)) return;
    say(`A ${r.body.thing} isn't among the parts I can add yet.`);
    return;
  }
  if (intent.kind === "question") {
    say("Pick a part and ask me about it.");
    return;
  }
  // it talks about what is here but asks for nothing I can do: say what I can, keep the build
  if (REFERS.test(lower) && text.split(/\s+/).length <= 8) {
    say("I can swap, recolour, move, remove or add parts. Or describe a new device.");
    return;
  }
  newDevice(text);
}
