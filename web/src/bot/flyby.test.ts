import { describe, expect, it } from "vitest";
import { loadFixtures } from "../spec/fixtures";
import type { Candidate, Decision, ServerEnvelope } from "../spec/types";
import {
  cardsFor,
  FlybyTracker,
  flybyFrom,
  type FlyItem,
  formatSpec,
  MAX_CARDS,
  pickCards,
  planFor,
  shuffleSequence,
  specLine,
} from "./flyby";

const fx = await loadFixtures();

/** Runs a fixture's server messages through the tracker, collecting every fly-by and where its winner landed. */
function run(name: string) {
  const f = fx.streams.get(name);
  if (!f) throw new Error(`no fixture ${name}`);
  const t = new FlybyTracker();
  const items: FlyItem[] = [];
  for (const step of f.steps) {
    if (step.dir !== "server") continue;
    const env = step.msg as ServerEnvelope;
    const item = t.feed(env.type, env.payload, env.seq);
    if (item) items.push(item);
  }
  return items.map((i) => ({ ...i, instance: t.instanceFor(i.winnerPartId) }));
}

const cand = (id: string, score: number | null = 0.5, extra: Partial<Candidate["card"]> = {}): Candidate => ({
  short_id: id,
  score,
  card: { part_id: id, display_name: id.toUpperCase(), kind: "module", ...extra },
});
const decision = (slot_id: string, chosen: string | null): Decision => ({
  decision_id: `d_${slot_id}`,
  slot_id,
  method: "model_pick",
  chosen_part_id: chosen,
  reason: "",
});

describe("fixture builds", () => {
  it("compose_wireless_split_oled: one fly-by per compared slot, winner known and placed", () => {
    const items = run("compose_wireless_split_oled");
    const summary = items.map((i) => ({
      slot: i.slotId,
      cards: i.cards.map((c) => c.name),
      winner: i.winner >= 0 ? i.cards[i.winner].name : null,
      row: i.instance,
    }));
    expect(summary).toEqual([
      { slot: "controller", cards: ["nice!nano v2", "SuperMini nRF52840", "BlueMicro840", "Puchi-BLE"], winner: "nice!nano v2", row: "u_mcu_l" },
      { slot: "battery", cards: ["LiPo 301230, 110 mAh", "LiPo 401230, 150 mAh"], winner: "LiPo 301230, 110 mAh", row: "u_bat_l" },
      { slot: "display", cards: ["SSD1306 OLED 128x32 (I2C)", "SH1106 OLED 128x64 (I2C)"], winner: "SSD1306 OLED 128x32 (I2C)", row: "u_oled_l" },
      { slot: "switches", cards: ["Gateron Yellow (MX)", "Cherry MX2A Brown"], winner: "Gateron Yellow (MX)", row: "u_sw_l" },
      { slot: "keycaps", cards: ["DSA 1u keycap (PBT)"], winner: "DSA 1u keycap (PBT)", row: "u_cap_l" },
    ]);
    // Foam had no survivors and the reused design's decisions were never compared.
    expect(items.some((i) => i.slotId === "foam" || i.slotId === "pcb")).toBe(false);
    const ctl = items[0];
    expect(ctl.countAfter).toBe(4);
    expect(ctl.cards[0]).toMatchObject({ kind: "Module", specs: "nRF52840 · BLE 5", score: 0.91 });
    expect(items[1].cards[0].specs).toBe("110 mAh · 3.7 V");
    expect(items[3].countAfter).toBe(112);
  });

  it("clarify_vague_gadget: single-option slots still fly the chosen card", () => {
    const items = run("clarify_vague_gadget");
    expect(items.map((i) => [i.slotId, i.cards.length, i.winner, i.instance])).toEqual([
      ["controller", 1, 0, "u_mcu"],
      ["sensor", 1, 0, "u_sens"],
      ["display", 1, 0, "u_oled"],
    ]);
  });

  it("failed_critical_missing and exact_keyboard: nothing to fly", () => {
    expect(run("failed_critical_missing")).toEqual([]);
    expect(run("exact_keyboard")).toEqual([]);
  });
});

describe("pickCards", () => {
  it("caps at six in server order", () => {
    const s = Array.from({ length: 9 }, (_, i) => cand(`p${i}`));
    expect(pickCards(s, "p1").map((c) => c.short_id)).toEqual(["p0", "p1", "p2", "p3", "p4", "p5"]);
    expect(MAX_CARDS).toBe(6);
  });
  it("always keeps the winner, taking the last seat", () => {
    const s = Array.from({ length: 9 }, (_, i) => cand(`p${i}`));
    expect(pickCards(s, "p8").map((c) => c.short_id)).toEqual(["p0", "p1", "p2", "p3", "p4", "p8"]);
  });
  it("drops duplicates and broken entries", () => {
    const s = [cand("a"), cand("a"), {} as Candidate, cand("b")];
    expect(pickCards(s, null).map((c) => c.short_id)).toEqual(["a", "b"]);
  });
});

describe("flybyFrom", () => {
  it("marks no winner when the decision chose nothing", () => {
    const item = flybyFrom({ slot_id: "x", survivors: [cand("a"), cand("b")] }, decision("x", null));
    expect(item?.winner).toBe(-1);
    expect(item?.winnerPartId).toBeNull();
  });
  it("returns null without survivors", () => {
    expect(flybyFrom({ slot_id: "x", survivors: [] }, decision("x", null))).toBeNull();
  });
  it("clamps scores and keeps missing ones null", () => {
    const item = flybyFrom({ slot_id: "x", survivors: [cand("a", 1.4), cand("b", null)] }, decision("x", "a"));
    expect(item?.cards.map((c) => c.score)).toEqual([1, null]);
  });
});

describe("card text", () => {
  it("formats specs compactly", () => {
    expect(formatSpec({ label: "Logic", value: 3.3, unit: "V" })).toBe("3.3 V");
    expect(formatSpec({ label: "Hot-swap", value: true })).toBe("Hot-swap");
    expect(formatSpec({ label: "Hot-swap", value: false })).toBeNull();
    expect(specLine([{ label: "A", value: "x" }, { label: "B", value: "x" }, { label: "C", value: "y" }])).toBe("x · y");
  });
  it("clips long names", () => {
    const item = flybyFrom({ slot_id: "x", survivors: [cand("a", 0.5, { display_name: "A very long part name that will not fit" })] }, decision("x", "a"));
    expect(item?.cards[0].name.length).toBeLessThanOrEqual(26);
    expect(item?.cards[0].name.endsWith("…")).toBe(true);
  });
});

describe("planFor", () => {
  const item = { cards: [1, 2, 3, 4].map((i) => ({ partId: `p${i}`, name: "", kind: "", specs: "", score: null })), winner: 2 };
  it("full fly-by stays within 1.6 to 2.4 s", () => {
    const p = planFor(item, 0, false);
    const total = p.fanMs + p.shuffleMs + p.settleMs + p.exitMs;
    expect(p.mode).toBe("full");
    expect(total).toBeGreaterThanOrEqual(1600);
    expect(total).toBeLessThanOrEqual(2400);
  });
  it("compresses as the queue grows, and shows only the winner past three waiting", () => {
    const full = planFor(item, 0, false);
    const quick = planFor(item, 2, false);
    const winner = planFor(item, 4, false);
    const sum = (p: typeof full) => p.fanMs + p.shuffleMs + p.settleMs + p.exitMs;
    expect(quick.mode).toBe("quick");
    expect(sum(quick)).toBeLessThan(sum(full));
    expect(winner.mode).toBe("winner");
    expect(sum(winner)).toBeLessThan(sum(quick));
    const f: FlyItem = { key: "k", slotId: "s", cards: item.cards, winner: 2, winnerPartId: "p3", countAfter: 4 };
    expect(cardsFor(f, "winner")).toEqual({ cards: [item.cards[2]], winner: 0 });
  });
  it("reduced motion is static with no shuffle", () => {
    const p = planFor(item, 0, true);
    expect(p).toMatchObject({ mode: "static", fanMs: 0, shuffleMs: 0 });
  });
});

describe("shuffleSequence", () => {
  it("ends on the winner with no repeats in a row", () => {
    for (const seed of [1, 7, 99, 12345]) {
      const s = shuffleSequence(4, 2, 7, seed);
      expect(s).toHaveLength(7);
      expect(s.at(-1)).toBe(2);
      for (let i = 1; i < s.length; i++) expect(s[i]).not.toBe(s[i - 1]);
      expect(s.every((k) => k >= 0 && k < 4)).toBe(true);
    }
  });
  it("is deterministic per seed", () => {
    expect(shuffleSequence(5, 0, 6, 3)).toEqual(shuffleSequence(5, 0, 6, 3));
  });
  it("handles one card and no winner", () => {
    expect(shuffleSequence(1, 0, 3)).toEqual([0, 0, 0]);
    expect(shuffleSequence(3, -1, 4).at(-1)).toBe(2);
    expect(shuffleSequence(0, 0, 4)).toEqual([]);
  });
});
