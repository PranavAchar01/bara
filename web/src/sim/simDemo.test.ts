import { describe, expect, it } from "vitest";
import { demoScript } from "./SimDemo";

const keymap = (labels: string[]) => (label: string) => (labels.includes(label) ? `k_${label}` : null);

describe("demoScript", () => {
  it("types hello, a space, then one key on a held layer key", () => {
    const steps = demoScript(keymap(["H", "E", "L", "O", "Space", "Lower", "1"]));
    const taps = steps.filter((s) => s.kind === "tap");
    expect(taps.map((s) => s.kind === "tap" && s.id)).toEqual(["k_H", "k_E", "k_L", "k_L", "k_O", "k_Space", "k_1"]);
    expect(taps.at(-1)).toMatchObject({ hold: "k_Lower" });
  });

  it("skips keys the keymap does not have", () => {
    const steps = demoScript(keymap(["H", "O"]));
    expect(steps.filter((s) => s.kind === "tap")).toHaveLength(2);
    expect(steps.some((s) => s.kind === "tap" && s.hold)).toBe(false);
  });
});
