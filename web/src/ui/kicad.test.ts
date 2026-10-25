import { describe, expect, it } from "vitest";
import type { Board, KicadChecks } from "../spec/types";
import { kicadSummary } from "./kicad";

const sec = (error: number, warning: number) => ({ counts: { error, warning, info: 0 }, by_rule: {}, passed: error === 0 });

function board(id: string, side: Board["side"], report: KicadChecks | undefined): Board {
  return { board_id: id, source: "unknown", side, status: "ok", revision: 1, kicad_checks: report };
}

describe("kicadSummary", () => {
  it("counts pass, warn and error across tools and groups violations by rule", () => {
    const left = board("b_l", "left", {
      status: "ok",
      drc: sec(0, 0),
      erc: sec(2, 1),
      parity: sec(0, 3),
      violations: [
        { tool: "erc", rule: "pin_to_pin", severity: "error", message: "Output to Output", refs: ["U1", "U2"], instance_ids: ["i_mcu"] },
        { tool: "erc", rule: "pin_to_pin", severity: "error", message: "Output to Output", refs: ["U3"], instance_ids: [] },
        { tool: "parity", rule: "net_conflict", severity: "warning", message: "Pad missing net", refs: ["DS1"] },
      ],
    });
    const right = board("b_r", "right", { status: "ok", drc: sec(1, 0), violations: [] });
    const s = kicadSummary([left, right]);
    expect([s.pass, s.warn, s.fail]).toEqual([1, 1, 2]);
    expect([s.errors, s.warnings]).toEqual([3, 4]);
    expect(s.passRate.drc).toEqual({ passed: 1, total: 2 });
    expect(s.passRate.erc).toEqual({ passed: 0, total: 1 });
    expect(s.groups.map((g) => [g.rule, g.violations.length, g.board])).toEqual([
      ["pin_to_pin", 2, "left"],
      ["net_conflict", 1, "left"],
    ]);
  });

  it("says why when KiCad did not run", () => {
    const s = kicadSummary([board("b", "none", { status: "not_installed", message: "KiCad not installed" })]);
    expect(s.checked).toEqual([]);
    expect(s.missing).toBe("KiCad not installed");
    expect(kicadSummary([board("b", "none", undefined)]).missing).toBeNull();
  });
});
