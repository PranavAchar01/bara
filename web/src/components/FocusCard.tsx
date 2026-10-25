// Focus card (Figma 17 Focus · isolated part): the part pulled out of the build, and Bara asking
// what to do with it. Three plain options (ask, change, something else) and a few questions to
// start from. Answers come from the engine's /ask route, or from the build itself when it can't.
import { useEffect, useMemo, useState } from "react";
import { focusPart, select, showToast, useApp } from "../state/store";
import { applyEdit, getRest } from "../net/client";
import { partLabel } from "../three/explode";
import { labelRows } from "../three/Viewport3D";
import { BaraBot } from "../bot/BaraBot";
import { speak } from "../voice/voice";
import { stage } from "../three/stage";
import type { Build, BuildPart } from "../spec/types";

type Mode = "choose" | "ask" | "else";
interface Turn {
  q: string;
  a: string | null;
  from: "model" | "build" | null;
}
interface AskReply {
  answer: string;
  follow_ups: string[];
}

const START_QUESTIONS = ["Why this one?", "What does it connect to?", "Is there a quieter one?"];
const CASE_QUESTIONS = ["How thick are the walls?", "Can I print it?", "Can it be smaller?"];

function partsFor(build: Build | null, key: string): BuildPart[] {
  return (build?.parts ?? []).filter((p) => partLabel(p).key === key);
}

/** What the build alone can say about a part, when no model answers. */
function localAnswer(build: Build | null, parts: BuildPart[]): string {
  const p = parts[0];
  if (!p) return "I can only answer about parts right now; ask me about one of them.";
  const why = build?.decisions?.find((d) => d.chosen_part_id === p.part_id)?.reason;
  const sentence = (t: string) => (/[.!?]$/.test(t.trim()) ? t.trim() : `${t.trim()}.`);
  const bits = [p.card.summary ? sentence(`It's a ${p.card.summary.charAt(0).toLowerCase()}${p.card.summary.slice(1)}`) : null, why ? sentence(`I picked it because ${why.charAt(0).toLowerCase()}${why.slice(1)}`) : null].filter(Boolean);
  return bits.length ? bits.join(" ") : `It's the ${p.card.display_name}. I can't reach the model for more detail right now.`;
}

export function FocusCard() {
  const key = useApp((s) => s.focusKey);
  const build = useApp((s) => s.build);
  const rows = useMemo(() => labelRows(build), [build]);
  const row = rows.find((r) => r.key === key) ?? null;
  const parts = useMemo(() => (key ? partsFor(build, key) : []), [build, key]);
  const [mode, setMode] = useState<Mode>("choose");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [followUps, setFollowUps] = useState<string[] | null>(null);
  const done = build?.status === "done";
  const isCase = key?.startsWith("e:") ?? false;
  const isBoard = key === "b:board";
  const first = parts[0] ?? null;
  const thinking = turns.some((t) => t.a === null);

  useEffect(() => {
    setMode("choose");
    setTurns([]);
    setFollowUps(null);
  }, [key]);
  useEffect(() => {
    // one place to type: "Ask about it" puts the cursor in the Ask pill under the canvas
    if (mode === "ask") window.dispatchEvent(new Event("bara:focus-ask"));
  }, [mode]);

  const ask = async (q: string) => {
    const question = q.trim();
    if (!question || !build || thinking) return;
    setMode("ask");
    setTurns((t) => [...t, { q: question, a: null, from: null }]);
    const partId = first?.part_id ?? (isBoard ? build.parts.find((p) => String(p.card.kind) === "pcb")?.part_id : undefined);
    let reply: AskReply | null = null;
    if (partId) {
      const res = await getRest().request<AskReply>("POST", `/v1/builds/${encodeURIComponent(build.build_id)}/ask`, { part_id: partId, question });
      if (res.ok) reply = res.body;
    }
    const answer = reply?.answer ?? localAnswer(build, parts);
    setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, a: answer, from: reply ? "model" : "build" } : x)));
    setFollowUps(reply?.follow_ups?.length ? reply.follow_ups : null);
    speak(answer);
  };

  const change = () => {
    if (isCase) {
      const enc = build?.enclosures?.find((e) => e.kind !== "none");
      if (enc) useApp.setState({ resizeTarget: { enclosure_id: enc.enclosure_id }, overlay: "resize" });
      return;
    }
    if (isBoard) {
      const b = build?.boards?.[0];
      if (b) useApp.setState({ resizeTarget: { board_id: b.board_id }, overlay: "resize" });
      return;
    }
    if (!first?.slot_id) {
      showToast("This part has no alternatives to swap in.");
      return;
    }
    useApp.setState({ selection: first.instance_id, overlay: "swap" });
  };
  const details = () => {
    if (first) select(first.instance_id);
  };
  const move = () => {
    if (first) useApp.setState((s) => ({ moving: s.moving === first.instance_id ? null : first.instance_id }));
  };
  const remove = () => {
    if (!parts.length) return;
    applyEdit(
      parts.map((p) => ({ op: "remove_part" as const, instance_id: p.instance_id })),
      `Remove ${first?.card.display_name ?? "part"}`,
    );
    focusPart(null);
  };
  const step = (dir: 1 | -1) => {
    // the order of the Layers list, then the board and case; only parts the 3D view draws
    const drawn = new Set(stage.focusGroups.values());
    const order: string[] = [];
    for (const el of document.querySelectorAll<HTMLElement>(".leftcol .part-row[data-focus-key]")) {
      const k = el.dataset.focusKey!;
      if (drawn.has(k) && !order.includes(k)) order.push(k);
    }
    for (const k of ["b:board", "e:case_top", "e:case"]) if (drawn.has(k) && !order.includes(k)) order.push(k);
    if (!order.length) return;
    const i = order.indexOf(key ?? "");
    focusPart(order[(i + dir + order.length) % order.length]);
  };

  // Spoken questions come here while a part is in focus.
  useEffect(() => {
    const onAsk = (e: Event) => void ask((e as CustomEvent<string>).detail);
    window.addEventListener("bara:ask", onAsk);
    return () => window.removeEventListener("bara:ask", onAsk);
  });

  // A ask, S change, O something else, ← → next part. Typing in the ask field never triggers them.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "a") {
        e.preventDefault();
        setMode("ask");
      } else if (k === "s" && done) change();
      else if (k === "o") setMode((m) => (m === "else" ? "choose" : "else"));
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!key || !row) return null;
  const qty = row.quantity;
  // a sourced part is named by its model; the board's and case's detail is a note ("routed, KiCad"), not a name
  const name = (key.startsWith("p:") && row.detail) || row.title;
  const them = qty > 1 || /s$/i.test(row.title) ? "them" : "it";
  const suggestions = followUps ?? (isCase ? CASE_QUESTIONS : START_QUESTIONS);
  const lastAnswer = [...turns].reverse().find((t) => t.a !== null);

  return (
    <aside className="side-overlay focus-card" aria-label={`${name} in focus`}>
      <header className="fc-head">
        <BaraBot size={40} mood={thinking ? "thinking" : mode === "ask" ? "listening" : "asking"} bubbles={false} />
        <div className="fc-title">
          <span className="fc-kicker">
            {row.title} · {qty} in this build
          </span>
          <h2>{name}</h2>
        </div>
        <button type="button" className="btn sm fc-back" onClick={() => focusPart(null)} title="Put it back in the build (Esc)">
          Put back <kbd>Esc</kbd>
        </button>
      </header>
      <div className="fc-body">
        <p className="fc-say">
          {lastAnswer?.a ?? `Pulled the ${row.title.toLowerCase()} out for you. What do you want to do with ${them}?`}
          {lastAnswer?.from === "build" && <span className="fc-src"> From the build; the model didn't answer.</span>}
        </p>
        {thinking && <p className="fc-thinking">Thinking about “{turns[turns.length - 1].q}”…</p>}

        <div className="fc-options" role="group" aria-label="What to do">
          <button type="button" className={`fc-opt ${mode === "ask" ? "active" : ""}`} onClick={() => setMode("ask")}>
            <span>
              <b>Ask about it</b>
              <small>Why {them === "it" ? "this one" : "these"}, what {them === "it" ? "it touches" : "they touch"}, how {them} work</small>
            </span>
            <kbd>A</kbd>
          </button>
          <button type="button" className="fc-opt" onClick={change} disabled={!done} title={done ? undefined : "Changes unlock when the build is done"}>
            <span>
              <b>Change it</b>
              <small>{isCase ? "Resize or recolour the case" : isBoard ? "Resize the board" : "Swap for another part that fits"}</small>
            </span>
            <kbd>S</kbd>
          </button>
          <button type="button" className={`fc-opt ${mode === "else" ? "active" : ""}`} onClick={() => setMode((m) => (m === "else" ? "choose" : "else"))}>
            <span>
              <b>Something else</b>
              <small>Recolour, move, take it out, or see every detail</small>
            </span>
            <kbd>O</kbd>
          </button>
        </div>

        {mode === "else" && (
          <div className="fc-more">
            <button type="button" className="btn sm" onClick={details} disabled={!first}>
              Details
            </button>
            <button type="button" className="btn sm" onClick={details} disabled={!first || !done} title="Recolour from the details panel">
              Recolour
            </button>
            <button type="button" className="btn sm" onClick={move} disabled={!first || !done}>
              Move
            </button>
            <button type="button" className="btn sm ghost danger" onClick={remove} disabled={!parts.length || !done}>
              Take it out
            </button>
          </div>
        )}


        <div className="fc-suggest">
          <span className="fc-kicker">{followUps ? "Ask next" : "Or just ask"}</span>
          <div className="chips">
            {suggestions.map((q) => (
              <button key={q} type="button" className="chip" onClick={() => void ask(q)} disabled={thinking}>
                {q}
              </button>
            ))}
          </div>
        </div>

        {turns.length > 1 && (
          <details className="fc-history">
            <summary>Earlier in this chat ({turns.length - 1})</summary>
            {turns.slice(0, -1).map((t, i) => (
              <p key={i}>
                <b>{t.q}</b> {t.a}
              </p>
            ))}
          </details>
        )}
      </div>
      <footer className="fc-keys">
        <kbd>←</kbd>
        <kbd>→</kbd>
        <span>other parts</span>
        <span className="spacer" />
        <span>Ask in the bar below, or hold Space</span>
      </footer>
    </aside>
  );
}

/** On the canvas while a part is in focus: the one obvious way back to the whole build. */
export function FocusExit() {
  const key = useApp((s) => s.focusKey);
  const build = useApp((s) => s.build);
  if (!key) return null;
  const row = labelRows(build).find((r) => r.key === key);
  return (
    <div className="focus-exit">
      <button type="button" className="focus-exit-btn" onClick={() => focusPart(null)} title="Back to the whole build (Esc, or click empty space)">
        <span aria-hidden>←</span> Whole build <kbd>Esc</kbd>
      </button>
      {row && (
        <span className="focus-crumb">
          <span className="sep">/</span> {row.title}
        </span>
      )}
    </div>
  );
}
