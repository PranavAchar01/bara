// The thinking trace: click the bot and a speech bubble unfolds beside it with
// what the build did, stage by stage (bot/trace.ts builds the rows from the store).
// The stage still working is open and followed; finished stages fold to one line
// that opens on a click, and the whole bubble folds to the step it is on now. It
// rides along with the bot, on stage or at home, and hides itself once idle.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/store";
import { vlabel } from "../ui/format";
import type { Rect } from "./agent";
import { agentPos } from "./agentBus";
import { buildTrace, nowLine, type TraceGroup, type TraceKind, type TraceRow, type TraceTarget } from "./trace";
import { closeTrace, useTrace } from "./traceState";
import { clamp } from "./spring";
import "./thoughtTrace.css";

const WIDTH = 344;
const GAP = 12;
const EDGE = 8;

const ICON: Record<TraceKind, string> = {
  step: "M8 5.4a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2Z",
  search: "M7 3.1a3.9 3.9 0 1 0 0 7.8 3.9 3.9 0 0 0 0-7.8Zm3 7 3.4 3.4",
  decision: "M8 2.2c.5 2.6 1.4 3.6 4 4.1-2.6.5-3.5 1.5-4 4.1-.5-2.6-1.4-3.6-4-4.1 2.6-.5 3.5-1.5 4-4.1Z",
  check: "M5 5l6 6M11 5l-6 6",
  note: "M3.5 5h9M3.5 8h9M3.5 11h5.5",
};

function RowIcon(props: { kind: TraceKind }) {
  const fill = props.kind === "step" || props.kind === "decision";
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
      <path d={ICON[props.kind]} fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function StatusIcon(props: { group: TraceGroup }) {
  const { group } = props;
  if (group.live) return <span className="tt-spin" aria-label="Working" />;
  const bad = group.status === "failed" || group.rows.some((r) => r.kind === "check");
  return (
    <svg className={`tt-status ${bad ? "bad" : "ok"}`} viewBox="0 0 16 16" width="16" height="16" aria-hidden>
      <path d={bad ? "M5 5l6 6M11 5l-6 6" : "M4.2 8.4l2.5 2.5 5.1-5.6"} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Same as a click on the part's row in the left column: select it and open the inspector. */
function pick(t: TraceTarget): void {
  if (t.instanceId) useApp.setState({ selection: t.instanceId, overlay: "inspector", inspectPartId: null });
  else if (t.partId) useApp.setState({ selection: null, overlay: "inspector", inspectPartId: t.partId });
}

function Row(props: { row: TraceRow; index: number }) {
  const { row } = props;
  const body = (
    <>
      <span className={`tt-ic tone-${row.tone}`}>
        <RowIcon kind={row.kind} />
      </span>
      <span className="tt-txt">
        <span className="tt-t">{row.title}</span>
        {row.detail && <span className="tt-d">{row.detail}</span>}
        {row.chips && row.chips.length > 0 && (
          <span className="tt-chips">
            {row.chips.slice(0, 6).map((c, i) => (
              <span key={i} className={`tt-chip tone-${c.tone}`}>
                {c.text}
                {c.counts && <span className="mono"> {c.counts}</span>}
              </span>
            ))}
          </span>
        )}
        {(row.meta || row.at !== undefined) && (
          <span className="tt-m">
            {row.meta}
            {row.meta && row.at !== undefined ? " · " : ""}
            {row.at !== undefined ? `+${row.at.toFixed(1)} s` : ""}
          </span>
        )}
      </span>
    </>
  );
  const style = { animationDelay: `${Math.min(props.index * 45, 360)}ms` };
  const target = row.target;
  return (
    <li className="tt-row" data-kind={row.kind} style={style}>
      {target ? (
        <button type="button" className="tt-hit" onClick={() => pick(target)} title="Show this part">
          {body}
        </button>
      ) : (
        <div className="tt-hit">{body}</div>
      )}
    </li>
  );
}

function Group(props: { group: TraceGroup; open: boolean; onToggle: () => void }) {
  const { group, open } = props;
  return (
    <section className={`tt-group ${open ? "open" : ""}`} data-live={group.live ? "1" : "0"} data-status={group.status}>
      <button type="button" className="tt-head" aria-expanded={open} onClick={props.onToggle}>
        <StatusIcon group={group} />
        <span className="tt-sum">{group.summary}</span>
        <svg className="tt-chev" viewBox="0 0 16 16" width="14" height="14" aria-hidden>
          <path d="M4.5 6.5L8 10l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <ol className="tt-list">
          {group.rows.length === 0 ? (
            <li className="tt-row tt-quiet">
              <div className="tt-hit">
                <span className="tt-t">{group.live ? "Working on it" : "Nothing to report"}</span>
              </div>
            </li>
          ) : (
            group.rows.map((r, i) => <Row key={r.id} row={r} index={i} />)
          )}
        </ol>
      )}
    </section>
  );
}

function homeRect(): Rect | null {
  const el = document.querySelector(".promptbar.docked .prompt-bot") ?? document.querySelector(".prompt-bot");
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}

/** The bot's thoughts: a speech bubble anchored to the bot, the one place they show. Renders
 *  nothing while closed. */
export function ThoughtTrace() {
  const open = useTrace((s) => s.open);
  const screen = useApp((s) => s.screen);
  if (!open || screen !== "workspace") return null;
  return <Panel />;
}

/** How long the bubble stays up once the build has nothing more to say and nobody is reading it. */
export const IDLE_HIDE_MS = 9000;

function Panel() {
  const root = useRef<HTMLDivElement>(null);
  const [folded, setFolded] = useState(false);
  const running = useApp((s) => s.build?.status === "running" || s.build?.status === "awaiting_input");
  const hovered = useRef(false);

  // Idle (nothing building) and nobody pointing at it: it hides itself after a while.
  useEffect(() => {
    if (running) return;
    let timer = 0;
    const arm = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (hovered.current) arm();
        else closeTrace();
      }, IDLE_HIDE_MS);
    };
    arm();
    const el = root.current;
    el?.addEventListener("pointermove", arm);
    el?.addEventListener("wheel", arm, { passive: true });
    return () => {
      window.clearTimeout(timer);
      el?.removeEventListener("pointermove", arm);
      el?.removeEventListener("wheel", arm);
    };
  }, [running]);

  // Esc and a press anywhere else close it; the bots toggle it themselves.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeTrace();
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Element | null;
      if (t?.closest(".thought-trace, .as-bot, .bot-mic")) return;
      closeTrace();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("pointerdown", onDown, true);
    };
  }, []);
  // Ride along with the bot: beside it on stage, above it at home.
  useEffect(() => {
    let raf = 0;
    const place = () => {
      raf = requestAnimationFrame(place);
      const el = root.current;
      if (!el) return;
      const stage = agentPos();
      const r = stage ?? homeRect();
      if (!r) return;
      const W = window.innerWidth;
      const H = window.innerHeight;
      const h = el.offsetHeight;
      let x: number;
      let y: number;
      let side: "right" | "left" | "top";
      if (stage) {
        const right = r.x + r.w + GAP;
        side = right + WIDTH <= W - EDGE ? "right" : "left";
        x = side === "right" ? right : r.x - GAP - WIDTH;
        y = clamp(r.y + r.h / 2 - 30, EDGE, Math.max(EDGE, H - h - EDGE));
      } else {
        side = "top";
        x = clamp(r.x - 6, EDGE, Math.max(EDGE, W - WIDTH - EDGE));
        y = Math.max(EDGE, r.y - h - GAP);
      }
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
      el.style.maxHeight = `${Math.max(160, Math.min(480, stage ? H - 2 * EDGE : r.y - GAP - EDGE))}px`;
      el.dataset.side = side;
      el.style.setProperty("--tt-tail-x", `${clamp(r.x + r.w / 2 - x, 18, WIDTH - 18).toFixed(0)}px`);
      el.style.setProperty("--tt-tail-y", `${clamp(r.y + r.h / 2 - y, 18, Math.max(18, h - 18)).toFixed(0)}px`);
      el.style.visibility = "visible";
    };
    raf = requestAnimationFrame(place);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div
      ref={root}
      className={`thought-trace ${folded ? "folded" : ""}`}
      role="dialog"
      aria-label="What the agent is thinking"
      style={{ width: WIDTH, visibility: "hidden" }}
      onPointerEnter={() => (hovered.current = true)}
      onPointerLeave={() => (hovered.current = false)}
    >
      <TraceBody folded={folded} onFold={() => setFolded((f) => !f)} />
    </div>
  );
}

/** The header, the line it is on now and the stage list; folded, only the header and that line. */
function TraceBody(props: { folded: boolean; onFold: () => void }) {
  const build = useApp((s) => s.build);
  const view = useApp((s) => s.view);
  const log = useApp((s) => s.log);
  const vocab = useApp((s) => s.vocab);
  const running = useApp((s) => s.build?.status === "running" || s.build?.status === "awaiting_input");
  const trace = useMemo(() => buildTrace({ build, view, log, label: (id) => vlabel(vocab, "stages", id) }), [build, view, log, vocab]);
  // The reader's own folds win over the defaults (the working stage open, the rest folded).
  const [folds, setFolds] = useState<Record<string, boolean>>({});
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const isOpen = (g: TraceGroup) => folds[g.id] ?? (g.live || g.status === "failed" || g.status === "needs_input" || g.rows.some((r) => r.kind === "check" && r.tone === "fail"));
  const rowCount = trace.groups.reduce((n, g) => n + (isOpen(g) ? g.rows.length : 0), 0) + trace.groups.length;

  // Follow the working stage unless the reader has scrolled up.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [rowCount, trace.final, props.folded]);

  const live = running && trace.groups.some((g) => g.live);
  const now = nowLine(trace);
  return (
    <>
      <header className="tt-top">
        <span className="tt-title">{live ? "Thinking" : "How it was built"}</span>
        <button
          type="button"
          className="tt-x tt-fold"
          onClick={props.onFold}
          aria-expanded={!props.folded}
          aria-label={props.folded ? "Show every step" : "Fold to the current step"}
          title={props.folded ? "Show every step" : "Fold to the current step"}
        >
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
            <path d={props.folded ? "M4.5 6.5L8 10l3.5-3.5" : "M4.5 9.5L8 6l3.5 3.5"} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <button type="button" className="tt-x" onClick={closeTrace} aria-label="Close">
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
            <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </header>
      <div
        ref={scroller}
        className="tt-scroll"
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
      >
        {now && (
          <div className={`tt-now tone-${now.tone}`} data-live={live ? "1" : "0"} aria-live="polite">
            <span className="tt-now-k">{now.stage ? (live ? `Now · ${now.stage}` : now.stage) : "Finished"}</span>
            <span className="tt-now-t">{now.text}</span>
            {now.detail && <span className="tt-now-d">{now.detail}</span>}
          </div>
        )}
        {!props.folded && (
          <>
            {trace.groups.length === 0 && <p className="tt-empty">Nothing yet. Thoughts show up as the build runs.</p>}
            {trace.groups.map((g) => (
              <Group key={g.id} group={g} open={isOpen(g)} onToggle={() => setFolds((f) => ({ ...f, [g.id]: !isOpen(g) }))} />
            ))}
            {trace.final && <p className={`tt-final tone-${trace.final.tone}`}>{trace.final.text}</p>}
          </>
        )}
      </div>
    </>
  );
}
