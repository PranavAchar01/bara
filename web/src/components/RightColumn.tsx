import { useEffect, useMemo, useState } from "react";
import { focusPart, select, useApp, type CodeTab, type RightTab } from "../state/store";
import { focusKeyOf } from "../three/Viewport3D";
import { toggleTrace } from "../bot/traceState";
import { ClarifyCard, DecisionTrace, ReuseCard, SpecCard, StageTimeline } from "./LeftColumn";
import { PanelToolbar } from "./TopBar";
import { applyEdit } from "../net/client";
import { serverUrl } from "../net/mode";
import type { Board, BoardEvaluation, BuildPart, CheckResult, Connection, FirmwareFile } from "../spec/types";
import { Badge, Chip, Dot, Empty, Panel, ProvenanceBadge } from "../ui/common";
import { checkArea, checkInstances, checkTone, fmtMm, fmtMs, fmtValue, instanceTone, known, severityRank, vlabel } from "../ui/format";
import { elementPoses } from "../three/layout";

const TABS: { id: RightTab; label: string; key: string }[] = [
  { id: "design", label: "Design", key: "⌥1" },
  { id: "build", label: "Build", key: "⌥2" },
  { id: "code", label: "Code", key: "⌥3" },
];

const CODE_TABS: { id: CodeTab; label: string }[] = [
  { id: "connections", label: "Wiring" },
  { id: "board", label: "Board" },
  { id: "firmware", label: "Firmware" },
];

/** Which right tab a check's failure belongs to, for the tab badges. */
function checkTab(c: CheckResult): RightTab {
  const a = checkArea(c);
  return a === "connections" || a === "board" || a === "firmware" ? "code" : "design";
}

/** Right panel (Figma layout): Design, Build and Code tabs; each badge counts failing checks in that tab. */
export function RightColumn() {
  const tab = useApp((s) => s.rightTab);
  const codeTab = useApp((s) => s.codeTab);
  const checks = useApp((s) => s.build?.checks ?? []);
  const connCount = useApp((s) => s.build?.connections?.length ?? 0);
  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const c of checks) {
      if (checkTone(c) !== "fail") continue;
      const t = checkTab(c);
      out[t] = (out[t] ?? 0) + 1;
    }
    return out;
  }, [checks]);
  return (
    <div className="rightcol">
      <PanelToolbar />
      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            data-agent={`tab:${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`tab ${tab === t.id ? "active" : ""}`}
            title={`${t.label} (${t.key})`}
            onClick={() => useApp.setState({ rightTab: t.id })}
          >
            {t.label}
            {counts[t.id] ? <span className="tab-badge">{counts[t.id]}</span> : null}
          </button>
        ))}
      </nav>
      <div className="tab-body">
        {tab === "design" && (
          <>
            <ClarifyCard />
            <SpecCard />
            <ReuseCard />
            <ChecksPanel />
          </>
        )}
        {tab === "build" && (
          <>
            {/* the reasoning lives with the agent: click it for what it is thinking; the full log stays here, folded */}
            <div className="think-hint">
              <p>What Bara is thinking is on Bara. Click the agent to see its current step and the steps before it.</p>
              <button type="button" className="btn" onClick={toggleTrace}>
                Show its thoughts
              </button>
            </div>
            <details className="fold build-log">
              <summary className="muted small">Full build log</summary>
              <StageTimeline />
              <DecisionTrace />
            </details>
          </>
        )}
        {tab === "code" && (
          <>
            <div className="segmented" role="tablist" aria-label="Code">
              {CODE_TABS.map((t) => (
                <button
                  key={t.id}
                  data-agent={`codetab:${t.id}`}
                  type="button"
                  role="tab"
                  aria-selected={codeTab === t.id}
                  className={codeTab === t.id ? "active" : ""}
                  onClick={() => useApp.setState({ codeTab: t.id })}
                >
                  {t.label}
                  {t.id === "connections" && connCount ? <span className="muted"> {connCount}</span> : null}
                </button>
              ))}
            </div>
            {codeTab === "connections" && <ConnectionView />}
            {codeTab === "board" && <BoardView />}
            {codeTab === "firmware" && <FirmwareView />}
          </>
        )}
      </div>
    </div>
  );
}

/** C09 PartsList: grouped by slot. */
export function PartsList() {
  const build = useApp((s) => s.build);
  const selection = useApp((s) => s.selection);
  const done = build?.status === "done";
  const groups = useMemo(() => {
    const out: { key: string; label: string; parts: BuildPart[] }[] = [];
    const bySlot = new Map<string, BuildPart[]>();
    for (const p of build?.parts ?? []) {
      const k = p.slot_id ?? "_other";
      bySlot.set(k, [...(bySlot.get(k) ?? []), p]);
    }
    const slots = [...(build?.slots ?? [])].sort((a, b) => (a.order ?? 999) - (b.order ?? 999));
    for (const s of slots) {
      const parts = bySlot.get(s.slot_id);
      if (parts) out.push({ key: s.slot_id, label: s.label, parts });
      bySlot.delete(s.slot_id);
    }
    for (const [k, parts] of bySlot) out.push({ key: k, label: k === "_other" ? "Other" : k, parts });
    return out;
  }, [build?.parts, build?.slots]);
  const count = build?.parts.reduce((a, p) => a + p.quantity, 0) ?? 0;
  return (
    <Panel
      title="Layers"
      meta={build?.parts.length ? `${build.parts.length} lines · ${count} pcs` : undefined}
      actions={
        <button type="button" className="btn sm" disabled={!done} onClick={() => useApp.setState({ overlay: "addpart" })}>
          Add part
        </button>
      }
    >
      {groups.length === 0 ? (
        <Empty>Parts appear here as they are chosen.</Empty>
      ) : (
        groups.map((g) => (
          <div className="part-group" key={g.key}>
            <h3>{g.label}</h3>
            {g.parts.map((p) => (
              <div
                key={p.instance_id}
                data-agent={`row:${p.instance_id}`}
                className={`part-row ${selection === p.instance_id ? "selected" : ""} ${p.placement.source === "intent" ? "provisional" : ""}`}
                role="button"
                tabIndex={0}
                aria-pressed={selection === p.instance_id}
                data-focus-key={focusKeyOf(build, p)}
                onClick={() => {
                  select(p.instance_id);
                  focusPart(focusKeyOf(useApp.getState().build, p));
                }}
                onKeyDown={(e) => {
                  if (e.target !== e.currentTarget || (e.key !== "Enter" && e.key !== " ")) return;
                  e.preventDefault();
                  select(p.instance_id);
                  focusPart(focusKeyOf(useApp.getState().build, p));
                }}
              >
                <Dot tone={instanceTone(build, p.instance_id) ?? (known(p.status, ["ok", "warning", "failed"] as const) === "failed" ? "fail" : "ok")} />
                <span className="part-name">
                  {p.card.display_name}
                  {p.side && p.side !== "none" && p.side !== "center" ? <span className="muted small"> {p.side}</span> : null}
                </span>
                <span className="mono small">x{p.quantity}</span>
                <ProvenanceBadge card={p.card} />
                {done && (
                  <button
                    type="button"
                    className="btn ghost sm row-act"
                    title="Remove this part"
                    onClick={(e) => {
                      e.stopPropagation();
                      applyEdit([{ op: "remove_part", instance_id: p.instance_id }], `Remove ${p.card.display_name}`);
                    }}
                  >
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
        ))
      )}
    </Panel>
  );
}

const CHECK_GROUPS: { id: "fail" | "unknown" | "pass"; label: string }[] = [
  { id: "fail", label: "Failing" },
  { id: "unknown", label: "Unknown" },
  { id: "pass", label: "Passing" },
];

/** C17 ChecksPanel. */
export function ChecksPanel() {
  const checks = useApp((s) => s.build?.checks ?? []);
  const vocab = useApp((s) => s.vocab);
  const grouped = useMemo(() => {
    const g: Record<string, CheckResult[]> = { fail: [], unknown: [], pass: [] };
    for (const c of checks) g[known(c.status, ["pass", "fail"] as const)].push(c);
    for (const k of Object.keys(g)) g[k].sort((a, b) => severityRank(b.severity) - severityRank(a.severity));
    return g;
  }, [checks]);
  if (!checks.length) return <Panel title="Checks"><Empty>Checks run after placement.</Empty></Panel>;
  const row = (c: CheckResult) => {
    const inst = checkInstances(c);
    return (
      <button
        key={c.check_key}
        data-agent={`check:${c.check_key}`}
        type="button"
        className={`check-row tone-${checkTone(c)}`}
        title={`${vlabel(vocab, "check_rules", c.rule_id)}${c.measured !== undefined && c.measured !== null ? ` · ${fmtValue(c.measured, c.unit)}${c.limit !== undefined && c.limit !== null ? ` / ${fmtValue(c.limit, c.unit)}` : ""}` : ""}`}
        onClick={() => inst[0] && select(inst[0])}
      >
        <span className="dot" />
        <span className="check-main">
          <span>{c.message}</span>
          {c.fix_hint && c.status === "fail" && <span className="fix-hint small">{c.fix_hint}</span>}
        </span>
      </button>
    );
  };
  const rest = [...grouped.unknown, ...grouped.pass];
  return (
    <Panel title="Checks" meta={<span className="mono small muted">{grouped.pass.length}/{checks.length}</span>}>
      {/* One bar shows the health at a glance: green passing, red failing, grey not known */}
      <div className="check-bar" role="img" aria-label={`${grouped.pass.length} pass, ${grouped.fail.length} fail, ${grouped.unknown.length} unknown`}>
        {CHECK_GROUPS.map((grp) =>
          grouped[grp.id].length ? <span key={grp.id} className={`cb-${grp.id}`} style={{ flexGrow: grouped[grp.id].length }} /> : null,
        )}
      </div>
      {grouped.fail.length > 0 && <div className="check-group">{grouped.fail.map(row)}</div>}
      {rest.length > 0 && (
        <details className="fold">
          <summary className="muted small">
            {grouped.pass.length} passing{grouped.unknown.length ? ` · ${grouped.unknown.length} not known` : ""}
          </summary>
          <div className="check-group">{rest.map(row)}</div>
        </details>
      )}
    </Panel>
  );
}

function portLabel(parts: BuildPart[], instanceId: string, iface: string) {
  const p = parts.find((x) => x.instance_id === instanceId);
  return `${p?.label ?? p?.card.display_name ?? instanceId}.${iface}`;
}

/** C14 ConnectionView. */
export function ConnectionView() {
  const build = useApp((s) => s.build);
  const hover = useApp((s) => s.hoverConnection);
  const vocab = useApp((s) => s.vocab);
  const parts = build?.parts ?? [];
  const conns = build?.connections ?? [];
  const done = build?.status === "done";
  const order = ["electrical", "wireless", "mechanical", "unknown"];
  const sorted = [...conns].sort((a, b) => order.indexOf(known(a.kind, ["electrical", "wireless", "mechanical"] as const)) - order.indexOf(known(b.kind, ["electrical", "wireless", "mechanical"] as const)));
  return (
    <Panel
      title="Wiring"
      meta={conns.length ? `${conns.length}` : undefined}
      actions={
        <button type="button" className="btn sm" disabled={!done} onClick={() => useApp.setState({ overlay: "connect" })}>
          Connect
        </button>
      }
    >
      {sorted.length === 0 ? (
        <Empty>Connections appear after composition.</Empty>
      ) : (
        sorted.map((c: Connection) => (
          <div
            key={c.connection_id}
            className={`conn-row ${hover === c.connection_id ? "hover" : ""}`}
            onMouseEnter={() => useApp.setState({ hoverConnection: c.connection_id })}
            onMouseLeave={() => useApp.setState({ hoverConnection: null })}
          >
            <div className="conn-head">
              <Badge tone={known(c.kind, ["electrical", "wireless", "mechanical"] as const) === "electrical" ? "accent" : "muted"}>{c.kind}</Badge>
              <span className="conn-label">{c.label ?? vlabel(vocab, "interface_types", c.type)}</span>
              {c.status && c.status !== "ok" && <Badge tone="warn">{c.status}</Badge>}
              {done && (
                <button
                  type="button"
                  className="btn ghost sm row-act"
                  onClick={() => applyEdit([{ op: "disconnect", connection_id: c.connection_id }], `Disconnect ${c.label ?? c.connection_id}`)}
                >
                  Disconnect
                </button>
              )}
            </div>
            <div className="conn-ends mono small">
              <button type="button" className="linkish" onClick={() => select(c.from.instance_id)}>
                {portLabel(parts, c.from.instance_id, c.from.interface_id)}
              </button>
              <span className="muted"> to </span>
              <button type="button" className="linkish" onClick={() => select(c.to.instance_id)}>
                {portLabel(parts, c.to.instance_id, c.to.interface_id)}
              </button>
              {c.via_instance_id && <span className="muted"> via {portLabel(parts, c.via_instance_id, "").replace(/\.$/, "")}</span>}
            </div>
            {(c.nets ?? []).length > 0 && (
              <div className="chips">
                {c.nets?.map((n, i) => (
                  <Chip key={i} tone="muted">
                    {n.signal} {n.from_pin ?? ""}
                    {n.to_pin ? ` to ${n.to_pin}` : ""}
                  </Chip>
                ))}
              </div>
            )}
            {c.resolved && Object.keys(c.resolved).length > 0 && (
              <div className="small muted mono">
                {Object.entries(c.resolved)
                  .map(([k, v]) => `${k}=${fmtValue(v)}`)
                  .join("  ")}
              </div>
            )}
          </div>
        ))
      )}
    </Panel>
  );
}

/** C15 BoardView: SVG outline, part footprints, nets and routing status. */
export function BoardView() {
  const build = useApp((s) => s.build);
  const boards = build?.boards ?? [];
  const [active, setActive] = useState<string | null>(null);
  const board = boards.find((b) => b.board_id === active) ?? boards[0];
  if (!board) return <Panel title="Board"><Empty>The board appears after enclosure.</Empty></Panel>;
  const routing = known(board.routing?.status, ["routed", "partial", "unrouted", "skipped"] as const);
  return (
    <Panel
      title="Board"
      meta={
        <span className="chips">
          <Badge tone={routing === "routed" ? "ok" : routing === "partial" ? "warn" : "muted"}>{routing}</Badge>
          {board.drc && <Badge tone={board.drc === "pass" ? "ok" : board.drc === "fail" ? "fail" : "info"}>DRC {board.drc}</Badge>}
        </span>
      }
    >
      {boards.length > 1 && (
        <div className="seg">
          {boards.map((b) => (
            <button key={b.board_id} type="button" className={`seg-btn ${b.board_id === board.board_id ? "active" : ""}`} onClick={() => setActive(b.board_id)}>
              {b.side && b.side !== "none" ? b.side : b.board_id}
            </button>
          ))}
        </div>
      )}
      <BoardSvg board={board} />
      <div className="kv">
        <span>Source</span>
        <span>{board.source}</span>
        <span>Size</span>
        <span className="mono">
          {board.size_mm ? `${fmtMm(board.size_mm[0])} x ${fmtMm(board.size_mm[1])}` : ""} {board.thickness_mm ? `, ${fmtMm(board.thickness_mm)}` : ""}
        </span>
        <span>Layers</span>
        <span className="mono">{board.layers ?? ""}</span>
        <span>Routing</span>
        <span className="mono">
          {board.routing?.method ?? ""} {fmtMs(board.routing?.duration_ms)} {board.routing?.cache_hit ? "cached" : ""}
        </span>
      </div>
      {board.evaluation && <BoardEvaluationView ev={board.evaluation} />}
      {(board.routing?.unrouted_nets ?? []).length > 0 && (
        <div className="chips">
          {board.routing?.unrouted_nets?.map((n) => (
            <Chip key={n} tone="warn">
              unrouted {n}
            </Chip>
          ))}
        </div>
      )}
      {(board.nets ?? []).length > 0 && (
        <ul className="nets small">
          {board.nets?.map((n) => (
            <li key={n.name}>
              <span className="mono">{n.name}</span> <span className="muted">{n.members.map((m) => `${m.instance_id}.${m.pin}`).join(", ")}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/** KiCad's evaluation of the routed board: DRC, net integrity and the routing benchmark. */
function BoardEvaluationView({ ev }: { ev: BoardEvaluation }) {
  const layers = Object.entries(ev.track_mm ?? {});
  return (
    <div className="board-eval">
      <h3 className="small muted">KiCad evaluation</h3>
      <div className="kv">
        <span>DRC</span>
        <span className="mono">
          {ev.drc_errors} errors, {ev.drc_warnings} warnings, {ev.unconnected} unconnected
        </span>
        <span>Nets</span>
        <span className="mono">
          {ev.nets} nets, {ev.dangling_nets} on one pin
        </span>
        <span>Routed</span>
        <span className="mono">{ev.routed_pct}%</span>
        <span>Copper</span>
        <span className="mono">
          {ev.segments ?? 0} tracks, {ev.vias ?? 0} vias
          {ev.track_total_mm ? `, ${fmtMm(ev.track_total_mm)}` : ""}
          {layers.length ? ` (${layers.map(([l, mm]) => `${l} ${fmtMm(mm)}`).join(", ")})` : ""}
        </span>
        <span>Benchmark</span>
        <span className="mono">
          {ev.attempts} attempt(s){ev.strategy ? `, ${ev.strategy}` : ""}
          {ev.route_s != null ? `, route ${ev.route_s.toFixed(1)} s` : ""}
          {ev.drc_s != null ? `, DRC ${ev.drc_s.toFixed(1)} s` : ""}
          {ev.total_s != null ? `, total ${ev.total_s.toFixed(1)} s` : ""}
        </span>
      </div>
    </div>
  );
}

function BoardSvg(props: { board: Board }) {
  const { board } = props;
  const build = useApp((s) => s.build);
  const selection = useApp((s) => s.selection);
  const host = build?.parts.find((p) => p.instance_id === board.part_instance_id);
  const origin = host?.placement.position_mm ?? board.position_mm ?? [0, 0, 0];
  const outline: number[][] = board.outline_mm?.length
    ? board.outline_mm
    : board.size_mm
      ? [
          [0, 0],
          [board.size_mm[0], 0],
          [board.size_mm[0], -board.size_mm[1]],
          [0, -board.size_mm[1]],
        ]
      : [];
  const marks: { id: string; x: number; y: number; w: number; h: number; rot: number }[] = [];
  for (const id of board.for_instance_ids ?? []) {
    const p = build?.parts.find((x) => x.instance_id === id);
    if (!p) continue;
    const layout = build?.layouts?.find((l) => l.layout_id === p.placement.layout_id);
    const poses = elementPoses(p.placement, p.quantity, layout);
    const sx = layout ? layout.pitch_x_mm * 0.82 : 18;
    const sy = layout ? layout.pitch_y_mm * 0.82 : 33;
    for (const e of poses) {
      marks.push({ id, x: e.position[0] - origin[0], y: e.position[1] - origin[1], w: sx * (e.w_u ?? 1), h: sy * (e.h_u ?? 1), rot: e.yaw });
    }
  }
  const xs = [...outline.map((p) => p[0]), ...marks.flatMap((m) => [m.x - m.w / 2, m.x + m.w / 2])];
  const ys = [...outline.map((p) => p[1]), ...marks.flatMap((m) => [m.y - m.h / 2, m.y + m.h / 2])];
  if (!xs.length) return <Empty>No outline in this board.</Empty>;
  const minX = Math.min(...xs) - 4;
  const maxX = Math.max(...xs) + 4;
  const minY = Math.min(...ys) - 4;
  const maxY = Math.max(...ys) + 4;
  return (
    <svg className="board-svg" viewBox={`${minX} ${-maxY} ${maxX - minX} ${maxY - minY}`} role="img" aria-label="Board outline">
      {outline.length > 0 && <polygon points={outline.map((p) => `${p[0]},${-p[1]}`).join(" ")} className="board-outline" />}
      {marks.map((m, i) => (
        <rect
          key={i}
          x={m.x - m.w / 2}
          y={-m.y - m.h / 2}
          width={m.w}
          height={m.h}
          rx={1}
          transform={`rotate(${-m.rot} ${m.x} ${-m.y})`}
          className={`board-mark ${selection === m.id ? "selected" : ""}`}
          onClick={() => select(m.id)}
        />
      ))}
    </svg>
  );
}

/** C16 FirmwareView: file tree, read-only source, pin map, mode badge, compile progress. */
const COMPILE_LABEL: Record<string, string> = {
  pending: "build queued",
  running: "building",
  ok: "binary built",
  failed: "build failed",
  skipped: "not built",
  unknown: "build unknown",
};

export function FirmwareView() {
  const fw = useApp((s) => s.build?.firmware ?? null);
  const progress = useApp((s) => s.view.firmwareProgress);
  const running = useApp((s) => s.build?.status === "running");
  const [path, setPath] = useState<string | null>(null);
  const file = fw?.files.find((f) => f.path === path) ?? fw?.files[0];
  if (!fw) {
    return (
      <Panel title="Firmware">
        {progress ? <CompileProgress /> : <Empty>{running ? "Firmware is generated after the board." : "No firmware in this build."}</Empty>}
      </Panel>
    );
  }
  const mode = known(fw.mode, ["prebuilt", "compiled"] as const);
  const compile = known(fw.compile.status, ["pending", "running", "ok", "failed", "skipped"] as const);
  return (
    <Panel
      title="Firmware"
      meta={
        <span className="chips">
          {/* mode is where the source came from ("compiled" = generated for this board), not whether a binary exists;
              saying "Compiled" next to "compile skipped" contradicted itself. */}
          <Badge tone="accent" title={fw.mode_reason ?? undefined}>
            {mode === "prebuilt" ? "Prebuilt" : mode === "compiled" ? "Generated source" : "unknown"}
          </Badge>
          <Badge
            tone={compile === "ok" ? "ok" : compile === "failed" ? "fail" : compile === "running" ? "accent" : compile === "skipped" ? "warn" : "muted"}
            title={fw.compile.message ?? undefined}
          >
            {COMPILE_LABEL[compile]}
          </Badge>
        </span>
      }
    >
      <div className="kv">
        <span>Framework</span>
        <span>{fw.framework}</span>
        {fw.targets?.map((t) => (
          <FragmentRow key={t.target_id} k="Target" v={`${t.label ?? t.target_id} (${t.mcu_instance_id})`} />
        ))}
      </div>
      {fw.mode_reason && <p className="muted small">{fw.mode_reason}</p>}
      {(progress || compile === "running") && <CompileProgress />}
      {fw.compile.message && <p className="small">{fw.compile.message}</p>}
      <div className="fw-split">
        <ul className="file-tree" aria-label="Files">
          {fw.files.map((f) => (
            <li key={f.path}>
              <button type="button" className={`file ${file?.path === f.path ? "active" : ""}`} onClick={() => setPath(f.path)} title={f.path}>
                <span className="mono small">{f.path.split("/").slice(-2).join("/")}</span>
              </button>
            </li>
          ))}
        </ul>
        {file && <SourceView file={file} />}
      </div>
      {(fw.pin_map ?? []).length > 0 && (
        <table className="pinmap small">
          <thead>
            <tr>
              <th>Part</th>
              <th>Signal</th>
              <th>MCU pin</th>
            </tr>
          </thead>
          <tbody>
            {fw.pin_map?.map((p, i) => (
              <tr key={i}>
                <td className="mono">{p.instance_id}</td>
                <td className="mono">{p.signal}</td>
                <td className="mono">{p.mcu_pin}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(fw.compile.binaries ?? []).length > 0 && (
        <div className="chips">
          {fw.compile.binaries?.map((b) => (
            <a key={b.asset_id} className="chip tone-muted outline" href={serverUrl(b.url)} download>
              {b.url.split("/").pop()}
            </a>
          ))}
        </div>
      )}
    </Panel>
  );
}

function FragmentRow(props: { k: string; v: string }) {
  return (
    <>
      <span>{props.k}</span>
      <span>{props.v}</span>
    </>
  );
}

function CompileProgress() {
  const p = useApp((s) => s.view.firmwareProgress);
  if (!p) return null;
  return (
    <div className="compile-progress">
      <span className="small">
        {p.phase} {p.message ?? ""}
      </span>
      <span className="bar">
        <span style={{ width: `${Math.round((p.fraction ?? 0) * 100)}%` }} />
      </span>
    </div>
  );
}

function SourceView(props: { file: FirmwareFile }) {
  const { file } = props;
  const [text, setText] = useState<string | null>(file.content ?? null);
  const [state, setState] = useState<"idle" | "loading" | "missing">("idle");
  useEffect(() => {
    setText(file.content ?? null);
    if (file.content || !file.asset?.url) {
      setState(file.content ? "idle" : "missing");
      return;
    }
    let live = true;
    setState("loading");
    void fetch(serverUrl(file.asset.url))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((t) => {
        if (live) {
          setText(t);
          setState("idle");
        }
      })
      .catch(() => {
        if (live) setState("missing");
      });
    return () => {
      live = false;
    };
  }, [file.path, file.content, file.asset?.url]);
  return (
    <div className="source">
      <div className="source-h mono small">
        {file.path} <span className="muted">{file.language}</span>
        {file.bytes ? <span className="muted"> {file.bytes} B</span> : null}
      </div>
      {state === "loading" && <p className="muted small">Loading source</p>}
      {state === "missing" && <p className="muted small">Source file is not available on this server.</p>}
      {text !== null && <pre className="code">{text}</pre>}
    </div>
  );
}
