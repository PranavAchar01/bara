import { useMemo } from "react";
import { focusPart, select, useApp } from "../state/store";
import { focusKeyOf } from "../three/Viewport3D";
import type { KicadViolation } from "../spec/types";
import { Chip, Dot } from "../ui/common";
import { fmtMm, vlabel } from "../ui/format";
import { KICAD_TOOLS, boardName, kicadSummary, ruleLabel, severityTone, toolLabel } from "../ui/kicad";

const SHOWN_PER_RULE = 40;

/** KiCad's own checks on the generated boards (kicad-cli DRC with schematic parity, ERC and board
 * statistics), inside the Checks panel. A violation that names a part selects it in 3D. */
export function KicadChecks() {
  const boards = useApp((s) => s.build?.boards);
  const summary = useMemo(() => kicadSummary(boards ?? []), [boards]);
  if (!summary.checked.length && !summary.missing) return null;
  return (
    <section className="kicad-checks" data-agent="kicad-checks">
      <h3 className="small muted">KiCad checks</h3>
      {summary.missing ? (
        <p className="small muted">{summary.missing}</p>
      ) : (
        <>
          <div className="chips">
            <Chip tone="ok" title="KiCad check runs with no errors and no warnings">
              {summary.pass} pass
            </Chip>
            <Chip tone="warn" title="Warnings across DRC, ERC and schematic parity">
              {summary.warnings} warn
            </Chip>
            <Chip tone="fail" title="Errors across DRC, ERC and schematic parity">
              {summary.errors} error
            </Chip>
          </div>
          <div className="kicad-tools small">
            {KICAD_TOOLS.map((t) => {
              const secs = summary.checked.map((c) => c.report[t.id]).filter((s) => !!s);
              if (!secs.length) return null;
              const e = secs.reduce((a, s) => a + (s.counts.error ?? 0), 0);
              const w = secs.reduce((a, s) => a + (s.counts.warning ?? 0), 0);
              return (
                <span key={t.id} className="kicad-tool">
                  <Dot tone={e ? "fail" : w ? "warn" : "ok"} />
                  {t.label} <span className="mono">{e ? `${e} errors` : "pass"}</span>
                  {w ? <span className="muted mono"> · {w} warnings</span> : null}
                </span>
              );
            })}
          </div>
          {summary.groups.length > 0 && <ViolationList groups={summary.groups} />}
          <KicadBenchmark />
        </>
      )}
    </section>
  );
}

function ViolationList({ groups }: { groups: ReturnType<typeof kicadSummary>["groups"] }) {
  const total = groups.reduce((a, g) => a + g.violations.length, 0);
  return (
    <details className="fold">
      <summary className="muted small">
        {total} violations in {groups.length} rules
      </summary>
      <div className="check-group">
        {groups.map((g) => (
          <details key={g.key} className="fold kicad-rule">
            <summary className={`small tone-${severityTone(g.severity)}`}>
              <Dot tone={severityTone(g.severity)} /> {toolLabel(g.tool)}: {ruleLabel(g.rule)}
              <span className="mono muted"> x{g.violations.length}</span>
              {g.board ? <span className="muted"> ({g.board})</span> : null}
            </summary>
            {g.violations.slice(0, SHOWN_PER_RULE).map((v, i) => (
              <ViolationRow key={i} v={v} />
            ))}
            {g.violations.length > SHOWN_PER_RULE && (
              <p className="small muted">and {g.violations.length - SHOWN_PER_RULE} more in the KiCad report</p>
            )}
          </details>
        ))}
      </div>
    </details>
  );
}

function ViolationRow({ v }: { v: KicadViolation }) {
  const inst = v.instance_ids?.[0];
  const pick = () => {
    if (!inst) return;
    select(inst);
    const build = useApp.getState().build;
    const part = build?.parts.find((p) => p.instance_id === inst);
    if (part && build?.status === "done") focusPart(focusKeyOf(build, part));
  };
  return (
    <button
      type="button"
      className={`check-row kicad-viol tone-${severityTone(v.severity)}`}
      disabled={!inst}
      title={[...(v.items ?? []), v.note ?? ""].filter(Boolean).join("\n")}
      onClick={pick}
    >
      <span className="dot" />
      <span className="check-main">
        <span className="small">{v.message}</span>
        {v.refs.length > 0 && (
          <span className="mono small muted">
            {v.refs.join(", ")}
            {inst ? "" : " (no part in the build)"}
          </span>
        )}
      </span>
    </button>
  );
}

const STEP_LABEL: Record<string, string> = {
  plan_s: "plan",
  kicad_build_s: "pcbnew",
  route_s: "route",
  ses_import_s: "import",
  drc_s: "DRC",
  glb_s: "GLB",
  kicad_checks_s: "KiCad checks",
};

/** Board numbers from KiCad, DRC/ERC pass rates and where the build's time went. */
function KicadBenchmark() {
  const boards = useApp((s) => s.build?.boards);
  const stages = useApp((s) => s.build?.timings_ms);
  const vocab = useApp((s) => s.vocab);
  const summary = useMemo(() => kicadSummary(boards ?? []), [boards]);
  const many = summary.checked.length > 1;
  const stageRows = Object.entries(stages ?? {}).filter(([, ms]) => typeof ms === "number");
  const stageTotal = stageRows.reduce((a, [, ms]) => a + ms, 0);
  return (
    <details className="fold kicad-bench">
      <summary className="muted small">Benchmark</summary>
      {summary.checked.map(({ board, report }) => {
        const s = report.stats;
        if (!s) return null;
        const tracks = Object.entries(s.track_mm ?? {});
        return (
          <div key={board.board_id} className="kv">
            {many && (
              <>
                <span>Board</span>
                <span className="mono">{boardName(board, true)}</span>
              </>
            )}
            <span>Size</span>
            <span className="mono">{s.width_mm != null && s.height_mm != null ? `${fmtMm(s.width_mm)} x ${fmtMm(s.height_mm)}` : ""}</span>
            <span>Layers</span>
            <span className="mono">{s.copper_layers ?? ""} copper</span>
            <span>Track</span>
            <span className="mono">
              {fmtMm(s.track_total_mm)}
              {tracks.length ? ` (${tracks.map(([l, mm]) => `${l} ${fmtMm(mm)}`).join(", ")})` : ""}
            </span>
            <span>Vias</span>
            <span className="mono">{s.vias ?? 0}</span>
            <span>Unrouted</span>
            <span className="mono">{s.unrouted ?? 0}</span>
            <span>Copper fill</span>
            <span className="mono">{s.copper_fill_pct != null ? `${s.copper_fill_pct}% outer layers` : ""}</span>
            <span>Components</span>
            <span className="mono">
              {s.components ?? 0} ({s.pads ?? 0} pads)
            </span>
            <span>KiCad time</span>
            <span className="mono">
              {Object.entries(report.timings ?? {})
                .map(([k, sec]) => `${k.replace(/_s$/, "").toUpperCase()} ${sec.toFixed(1)} s`)
                .join(", ")}
            </span>
          </div>
        );
      })}
      <div className="kv">
        {KICAD_TOOLS.map((t) => {
          const r = summary.passRate[t.id];
          return r.total ? (
            <PassRate key={t.id} label={`${t.label} pass rate`} passed={r.passed} total={r.total} />
          ) : null;
        })}
      </div>
      {stageRows.length > 0 && (
        <table className="kicad-stages small">
          <thead>
            <tr>
              <th>Stage</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {stageRows.map(([id, ms]) => (
              <tr key={id}>
                <td>{vlabel(vocab, "stages", id)}</td>
                <td className="mono">{(ms / 1000).toFixed(1)} s</td>
              </tr>
            ))}
            {summary.checked.map(({ board }) =>
              Object.entries(board.kicad_checks ? boardSteps(board.timings_s) : {}).map(([k, sec]) => (
                <tr key={`${board.board_id}:${k}`} className="muted">
                  <td>
                    {"  "}
                    {STEP_LABEL[k] ?? k}
                    {many ? ` (${boardName(board, true)})` : ""}
                  </td>
                  <td className="mono">{sec.toFixed(1)} s</td>
                </tr>
              )),
            )}
            <tr>
              <td>Total</td>
              <td className="mono">{(stageTotal / 1000).toFixed(1)} s</td>
            </tr>
          </tbody>
        </table>
      )}
    </details>
  );
}

function boardSteps(t: Record<string, number> | undefined): Record<string, number> {
  return Object.fromEntries(Object.entries(t ?? {}).filter(([k, v]) => k in STEP_LABEL && typeof v === "number"));
}

function PassRate(props: { label: string; passed: number; total: number }) {
  return (
    <>
      <span>{props.label}</span>
      <span className="mono">
        {Math.round((100 * props.passed) / props.total)}% ({props.passed}/{props.total} boards)
      </span>
    </>
  );
}
