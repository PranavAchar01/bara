// Render-time helpers: enum normalisation (SPEC 1 item 8), vocab labels,
// status colours (SPEC 11.4) and number formatting (SPEC 3.1).
import type { Build, CheckResult, Severity, Vocab, VocabEntry } from "../spec/types";

/** Map a server enum value to `unknown` when this client does not know it. */
export function known<T extends string>(value: string | null | undefined, allowed: readonly T[]): T | "unknown" {
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : "unknown";
}

export type Vgroup = "functions" | "interface_types" | "device_classes" | "stages" | "check_rules" | "warning_codes" | "error_codes";

export function vocabEntry(vocab: Vocab | null, group: Vgroup, id: string | null | undefined): VocabEntry | undefined {
  if (!vocab || !id) return undefined;
  return vocab[group]?.find((e) => e.id === id);
}

/** Label from GET /v1/vocab; falls back to the raw id so nothing is hard coded. */
export function vlabel(vocab: Vocab | null, group: Vgroup, id: string | null | undefined): string {
  return vocabEntry(vocab, group, id)?.label ?? id ?? "";
}

export type Tone = "ok" | "fail" | "warn" | "info" | "accent" | "muted";

const SEVERITIES = ["info", "warning", "error", "critical"] as const;

export function severityRank(s: Severity | undefined): number {
  const k = known(s, SEVERITIES);
  return k === "unknown" ? -1 : SEVERITIES.indexOf(k);
}

/** SPEC 11.4: pass/ok green; fail with critical or error red; warning amber; info and unknown grey. */
export function checkTone(c: Pick<CheckResult, "status" | "severity">): Tone {
  const status = known(c.status, ["pass", "fail"] as const);
  if (status === "pass") return "ok";
  if (status === "unknown") return "info";
  const sev = known(c.severity, SEVERITIES);
  if (sev === "critical" || sev === "error") return "fail";
  // a failed check is never grey: grey reads as "not checked"
  return "warn";
}

export function severityTone(s: Severity | undefined): Tone {
  const sev = known(s, SEVERITIES);
  if (sev === "critical" || sev === "error") return "fail";
  if (sev === "warning") return "warn";
  return "info";
}

export function fmtMm(n: number | null | undefined): string {
  return typeof n === "number" && Number.isFinite(n) ? `${n.toFixed(1)} mm` : "";
}

export function fmtMs(n: number | null | undefined): string {
  return typeof n === "number" && Number.isFinite(n) ? `${Math.round(n)} ms` : "";
}

export function fmtValue(v: unknown, unit?: string | null): string {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map((x) => fmtValue(x)).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  const s = typeof v === "number" ? String(Math.round(v * 1000) / 1000) : String(v);
  return unit ? `${s} ${unit}` : s;
}

/** Subjects of a check that point at an instance. */
export function checkInstances(c: CheckResult): string[] {
  return (c.subjects ?? []).map((s) => s.instance_id).filter((x): x is string => !!x);
}

/** Failing checks (red tone) per instance, for C09 dots and the C10 red outline. */
export function failingByInstance(build: Build | null): Map<string, CheckResult[]> {
  const out = new Map<string, CheckResult[]>();
  for (const c of build?.checks ?? []) {
    if (checkTone(c) !== "fail") continue;
    for (const id of checkInstances(c)) out.set(id, [...(out.get(id) ?? []), c]);
  }
  return out;
}

/** Worst tone of the checks on one instance. */
export function instanceTone(build: Build | null, instanceId: string): Tone | null {
  let worst: Tone | null = null;
  const order: Tone[] = ["ok", "info", "warn", "fail"];
  for (const c of build?.checks ?? []) {
    if (!checkInstances(c).includes(instanceId)) continue;
    const t = checkTone(c);
    if (worst === null || order.indexOf(t) > order.indexOf(worst)) worst = t;
  }
  return worst;
}

/** Area of a check for the right column tab badges. */
export function checkArea(c: CheckResult): "parts" | "connections" | "board" | "firmware" | "checks" {
  const id = c.rule_id;
  if (id.startsWith("board.") || id.startsWith("pcb.")) return "board";
  if (id.startsWith("fw.")) return "firmware";
  if (id.startsWith("elec.") || (c.subjects ?? []).some((s) => s.connection_id)) return "connections";
  if (id.startsWith("mech.") || id.startsWith("lic.")) return "parts";
  return "checks";
}
