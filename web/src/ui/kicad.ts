import type { Board, KicadChecks, KicadViolation } from "../spec/types";
import type { Tone } from "./format";

export const KICAD_TOOLS = [
  { id: "drc", label: "DRC" },
  { id: "erc", label: "ERC" },
  { id: "parity", label: "Schematic parity" },
] as const;
export type KicadTool = (typeof KICAD_TOOLS)[number]["id"];

export interface KicadRuleGroup {
  key: string;
  tool: string;
  rule: string;
  severity: string;
  board: string;
  violations: KicadViolation[];
}

export interface KicadSummary {
  /** boards whose KiCad report ran */
  checked: { board: Board; report: KicadChecks }[];
  /** the reason no report ran ("KiCad not installed"), when none did */
  missing: string | null;
  errors: number;
  warnings: number;
  /** tool runs with no errors and no warnings / with warnings only / with errors */
  pass: number;
  warn: number;
  fail: number;
  /** per tool: boards passing (no errors) out of boards it ran on */
  passRate: Record<KicadTool, { passed: number; total: number }>;
  groups: KicadRuleGroup[];
}

const SEV_ORDER: Record<string, number> = { error: 0, warning: 1, info: 2 };

export function boardName(b: Board, many: boolean): string {
  if (!many) return "";
  return b.side && b.side !== "none" ? b.side : b.board_id;
}

export function kicadSummary(boards: Board[]): KicadSummary {
  const reports = boards.filter((b) => b.kicad_checks).map((b) => ({ board: b, report: b.kicad_checks as KicadChecks }));
  const checked = reports.filter((r) => r.report.status === "ok");
  const many = checked.length > 1;
  const out: KicadSummary = {
    checked,
    missing: checked.length ? null : (reports[0]?.report.message ?? null),
    errors: 0,
    warnings: 0,
    pass: 0,
    warn: 0,
    fail: 0,
    passRate: { drc: { passed: 0, total: 0 }, erc: { passed: 0, total: 0 }, parity: { passed: 0, total: 0 } },
    groups: [],
  };
  const groups = new Map<string, KicadRuleGroup>();
  for (const { board, report } of checked) {
    for (const t of KICAD_TOOLS) {
      const sec = report[t.id];
      if (!sec) continue;
      const e = sec.counts.error ?? 0;
      const w = sec.counts.warning ?? 0;
      out.errors += e;
      out.warnings += w;
      if (e) out.fail += 1;
      else if (w) out.warn += 1;
      else out.pass += 1;
      out.passRate[t.id].total += 1;
      if (sec.passed) out.passRate[t.id].passed += 1;
    }
    const name = boardName(board, many);
    for (const v of report.violations ?? []) {
      const key = `${board.board_id}|${v.tool}|${v.severity}|${v.rule}`;
      const g = groups.get(key) ?? { key, tool: v.tool, rule: v.rule, severity: v.severity, board: name, violations: [] };
      g.violations.push(v);
      groups.set(key, g);
    }
  }
  out.groups = [...groups.values()].sort(
    (a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9) || b.violations.length - a.violations.length,
  );
  return out;
}

export function severityTone(sev: string): Tone {
  return sev === "error" ? "fail" : sev === "warning" ? "warn" : "info";
}

export function ruleLabel(rule: string): string {
  const s = rule.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function toolLabel(tool: string): string {
  return KICAD_TOOLS.find((t) => t.id === tool)?.label ?? tool;
}
