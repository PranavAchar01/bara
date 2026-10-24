import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/store";
import { applyEdit, startBuild } from "../net/client";
import type { CheckResult, Suggestion } from "../spec/types";
import { STAGE_IDS } from "../spec/types";
import { Chip, Icon, Panel, useNow } from "../ui/common";
import { buildProgress, fmtDuration, fmtLeft } from "../state/progress";
import { checkTone, fmtMs, fmtValue, known, severityTone, vlabel } from "../ui/format";

/** How long a notification stays before it closes itself. */
const AUTO_CLOSE_MS = 8000;

/** Whole-build progress bar with time left while running, then a done confirmation. */
export function BuildProgress() {
  const status = useApp((s) => s.build?.status);
  const buildId = useApp((s) => s.build?.build_id ?? null);
  const stages = useApp((s) => s.view.stages);
  const startAt = useApp((s) => s.view.startAt);
  const total = useApp((s) => s.view.done?.total_ms ?? s.view.doneMs);
  const warnings = useApp((s) => s.build?.warnings?.length ?? 0);
  const [closed, setClosed] = useState<string | null>(null);
  const running = status === "running";
  const now = useNow(running, 1000);
  useEffect(() => {
    if (status !== "done" || !buildId) return;
    const h = setTimeout(() => setClosed(buildId), AUTO_CLOSE_MS);
    return () => clearTimeout(h);
  }, [status, buildId]);
  if (running) {
    const p = buildProgress(stages, startAt, now);
    const pct = Math.round(p.fraction * 100);
    return (
      <div className="build-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Build progress">
        <div className="bp-head">
          <span className="mono">{pct}%</span>
          {p.leftMs !== null && <span className="muted">{fmtLeft(p.leftMs)}</span>}
        </div>
        <div className="bp-track">
          <span style={{ width: `${Math.max(2, pct)}%` }} />
        </div>
      </div>
    );
  }
  if (status !== "done" || closed === buildId) return null;
  return (
    <div className="build-done" role="status" aria-live="polite">
      <span className="bd-check" aria-hidden>
        ✓
      </span>
      <strong>Build done</strong>
      {total !== null && total !== undefined && <span className="muted">in {fmtDuration(total)}</span>}
      {warnings > 0 && <span className="muted">· {warnings} warning{warnings > 1 ? "s" : ""} to look at</span>}
      <button type="button" className="btn ghost sm icon" aria-label="Close" onClick={() => setClosed(buildId)}>
        <Icon name="x" />
      </button>
    </div>
  );
}

/** C05 LatencyHUD: time to first part, per stage, total, model calls. */
export function LatencyHUD() {
  const view = useApp((s) => s.view);
  const focused = useApp((s) => s.focusKey !== null);
  const decisions = useApp((s) => s.build?.decisions ?? []);
  const vocab = useApp((s) => s.vocab);
  const models = decisions.filter((d) => d.model);
  const modelMs = models.reduce((a, d) => a + (d.model?.latency_ms ?? 0), 0);
  const total = view.done?.total_ms ?? view.doneMs;
  // the part in focus has the canvas to itself
  if (focused) return null;
  return (
    <div className="hud" aria-label="Latency">
      <div className="hud-row">
        <span className="hud-k">First part</span>
        <span className="hud-v mono">{view.firstPartMs !== null ? fmtMs(view.firstPartMs) : "..."}</span>
      </div>
      <div className="hud-row">
        <span className="hud-k">Total</span>
        <span className="hud-v mono">{total !== null && total !== undefined ? fmtMs(total) : "..."}</span>
      </div>
      {STAGE_IDS.map((id) => {
        const st = view.stages[id];
        const ms = view.done?.timings_ms?.[id] ?? st?.duration_ms;
        if (ms === undefined) return null;
        return (
          <div className="hud-row sub" key={id}>
            <span className="hud-k">{vlabel(vocab, "stages", id)}</span>
            <span className="hud-v mono">{fmtMs(ms)}</span>
          </div>
        );
      })}
      {models.length > 0 && (
        <div className="hud-row sub">
          <span className="hud-k">
            Model x{models.length} {models[0].model?.provider ?? ""}
          </span>
          <span className="hud-v mono">{fmtMs(modelMs)}</span>
        </div>
      )}
    </div>
  );
}

/** C18 WarningBanner: dismissible, one line per warning. */
export function WarningBanner() {
  const warnings = useApp((s) => s.build?.warnings ?? []);
  const dismissed = useApp((s) => s.dismissedWarnings);
  const vocab = useApp((s) => s.vocab);
  const shown = warnings.filter((w) => !dismissed.includes(w.warning_id));
  const ids = shown.map((w) => (w.severity === "critical" ? "" : w.warning_id)).join("|");
  // Warnings close themselves after a while; a critical one stays until dismissed.
  useEffect(() => {
    const close = ids.split("|").filter(Boolean);
    if (!close.length) return;
    const h = setTimeout(() => useApp.setState((s) => ({ dismissedWarnings: [...s.dismissedWarnings, ...close] })), AUTO_CLOSE_MS);
    return () => clearTimeout(h);
  }, [ids]);
  if (!shown.length) return null;
  return (
    <div className="warnings" role="status">
      {shown.map((w) => (
        <div key={w.warning_id} className={`warning tone-${severityTone(w.severity ?? "warning")}`}>
          <span className="warning-code mono small">{vlabel(vocab, "warning_codes", w.code)}</span>
          <span className="warning-msg">{w.message}</span>
          <button
            type="button"
            className="btn ghost sm icon"
            aria-label="Dismiss"
            onClick={() => useApp.setState((s) => ({ dismissedWarnings: [...s.dismissedWarnings, w.warning_id] }))}
          >
            <Icon name="x" />
          </button>
        </div>
      ))}
    </div>
  );
}

function runSuggestion(s: Suggestion) {
  const kind = known(s.kind, ["prompt", "edit", "design"] as const);
  if (kind === "edit" && s.ops?.length) applyEdit(s.ops, s.label);
  else if (s.prompt) startBuild(s.prompt);
}

function SuggestionButtons(props: { items: Suggestion[] }) {
  if (!props.items.length) return null;
  return (
    <div className="suggestions">
      {props.items.map((s) => {
        const kind = known(s.kind, ["prompt", "edit", "design"] as const);
        const usable = (kind === "edit" && !!s.ops?.length) || !!s.prompt;
        return (
          <button key={s.suggestion_id} type="button" className="btn sm" disabled={!usable} onClick={() => runSuggestion(s)}>
            {s.label}
          </button>
        );
      })}
    </div>
  );
}

function CheckLine(props: { c: CheckResult }) {
  const { c } = props;
  return (
    <li className={`check-line tone-${checkTone(c)}`}>
      <span className="dot" />
      <span>{c.message}</span>
      {c.measured !== undefined && c.measured !== null && (
        <span className="mono small muted">
          {fmtValue(c.measured, c.unit)}
          {c.limit !== undefined && c.limit !== null ? ` / ${fmtValue(c.limit, c.unit)}` : ""}
        </span>
      )}
    </li>
  );
}

/** C19 EditStatus. */
export function EditStatus() {
  const edit = useApp((s) => s.view.edit);
  useEffect(() => {
    if (edit?.phase !== "applied") return;
    const h = setTimeout(() => {
      const cur = useApp.getState().view.edit;
      if (cur && cur.msg_id === edit.msg_id && cur.phase === "applied") {
        useApp.setState((s) => ({ view: { ...s.view, edit: null } }));
      }
    }, 6000);
    return () => clearTimeout(h);
  }, [edit?.phase, edit?.msg_id]);
  if (!edit) return null;
  const close = () => useApp.setState((s) => ({ view: { ...s.view, edit: null } }));
  const text =
    edit.phase === "pending"
      ? "Sending edit"
      : edit.phase === "applying"
        ? "Applying edit"
        : edit.phase === "applied"
          ? `Edit applied${edit.duration_ms !== undefined ? ` in ${fmtMs(edit.duration_ms)}` : ""}`
          : "Edit rejected";
  return (
    <div className={`edit-status ph-${edit.phase}`} role="status" aria-live="polite">
      <div className="edit-head">
        {(edit.phase === "pending" || edit.phase === "applying") && <span className="spinner" aria-hidden />}
        <strong>{text}</strong>
        {edit.label && <span className="muted">{edit.label}</span>}
        {edit.edit_id && <span className="mono small muted">{edit.edit_id}</span>}
        <button type="button" className="btn ghost sm icon" aria-label="Close" onClick={close}>
          <Icon name="x" />
        </button>
      </div>
      {edit.phase === "rejected" && (
        <>
          {edit.error && <p className="edit-error">{edit.error.message}</p>}
          {(edit.failed_checks ?? []).length > 0 && (
            <ul className="check-lines">
              {edit.failed_checks?.map((c) => (
                <CheckLine key={c.check_key} c={c} />
              ))}
            </ul>
          )}
          <SuggestionButtons items={edit.suggestions ?? []} />
        </>
      )}
    </div>
  );
}

/** C25 FailureCard: shown on build.failed. */
export function FailureCard() {
  const failure = useApp((s) => s.view.failure);
  const error = useApp((s) => s.build?.error ?? null);
  const status = useApp((s) => s.build?.status);
  const vocab = useApp((s) => s.vocab);
  const slots = useApp((s) => s.build?.slots ?? []);
  if (status !== "failed" && status !== "cancelled") return null;
  const err = failure?.error ?? error;
  if (!err) return null;
  const cancelled = err.code === "E_CANCELLED" || status === "cancelled";
  const conflict = failure?.conflict;
  const slot = slots.find((s) => s.slot_id === conflict?.slot_id);
  return (
    <Panel title={cancelled ? "Build stopped" : "Build failed"} meta={<span className="mono small">{vlabel(vocab, "error_codes", err.code)}</span>} className={`failure ${cancelled ? "cancelled" : ""}`}>
      <p className="failure-msg">{err.message}</p>
      {conflict && (
        <div className="conflict">
          {slot && (
            <p className="small">
              Slot: <strong>{slot.label}</strong>
            </p>
          )}
          {(conflict.minimal_conflict ?? []).length > 0 && (
            <div className="chips">
              {conflict.minimal_conflict?.map((r) => (
                <Chip key={r.req_id} tone="fail" variant="solid" title={r.req_id}>
                  {r.label ?? `${r.facet} ${r.op} ${fmtValue(r.value, r.unit)}`}
                </Chip>
              ))}
            </div>
          )}
          {conflict.explanation && <p className="reason">{conflict.explanation}</p>}
        </div>
      )}
      <SuggestionButtons items={failure?.suggestions ?? []} />
    </Panel>
  );
}

/** C29 EventLog: toggled with L; one line per message, unknown types flagged. */
export function EventLog() {
  const open = useApp((s) => s.logOpen);
  const log = useApp((s) => s.log);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [open, log.length]);
  const rows = useMemo(() => log.slice(-400), [log]);
  if (!open) return null;
  return (
    <aside className="eventlog" aria-label="Event log">
      <header>
        <strong>Event log</strong>
        <span className="muted small">{log.length} messages, L to close</span>
        <button type="button" className="btn ghost sm icon" aria-label="Close" onClick={() => useApp.setState({ logOpen: false })}>
          <Icon name="x" />
        </button>
      </header>
      <div className="eventlog-b" ref={ref}>
        {rows.map((e) => (
          <div key={e.id} className={`log-line dir-${e.dir} ${e.unknown ? "unknown" : ""}`} title={e.raw}>
            <span className="mono muted">{new Date(e.t).toISOString().slice(11, 23)}</span>
            <span className="mono">{e.dir === "in" ? "<" : e.dir === "out" ? ">" : "x"}</span>
            <span className="mono">{e.seq ?? ""}</span>
            <span className="mono log-type">{e.type}</span>
            <span className="small muted">{e.unknown ? "unknown type, ignored" : (e.note ?? "")}</span>
          </div>
        ))}
      </div>
    </aside>
  );
}

export function Toast() {
  const toast = useApp((s) => s.toast);
  if (!toast) return null;
  return (
    <div className="toast" role="status">
      {toast}
    </div>
  );
}
