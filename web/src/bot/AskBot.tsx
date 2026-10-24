// "Ask the bot" in the part inspector: type a change or a question about the
// selected part. ask.ts reads it; edits go through applyEdit and the stage bot
// acts them out, answers come back as a line the bot says plus a reply here.
import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { applyEdit, getRest } from "../net/client";
import { paths } from "../net/rest";
import type { Alternatives, BuildPart } from "../spec/types";
import { agentDo } from "./agentBus";
import { parseAsk, resolveAsk, type SwapOption } from "./ask";
import "./askBot.css";

interface Exchange {
  id: number;
  q: string;
  reply: string;
  /** msg_id of the edit this ask sent, to show how it went. */
  msgId: string | null;
}

let nextId = 0;

async function loadOptions(buildId: string, inst: BuildPart): Promise<SwapOption[]> {
  if (!inst.slot_id) return [];
  // Survivors of the last narrowing step for this slot, then the catalog's alternatives on top.
  const steps = useApp.getState().view.candidates[inst.slot_id] ?? [];
  const last = steps.reduce<(typeof steps)[number] | null>((a, b) => (!a || b.step > a.step ? b : a), null);
  const out: SwapOption[] = (last?.survivors ?? []).map((c) => ({ card: c.card, score: c.score }));
  const r = await getRest().get<unknown>(paths.alternatives(buildId, inst.slot_id, inst.instance_id));
  if (r.ok) {
    const alts = r.body as Alternatives;
    // The REST answer knows compatibility, so it goes first and wins the dedupe.
    return [...(alts.items ?? []).map((it) => ({ card: it.card, compatible: it.compatible })), ...out];
  }
  return out;
}

export function AskBot(props: { instance: BuildPart }) {
  const inst = props.instance;
  const build = useApp((s) => s.build);
  const edit = useApp((s) => s.view.edit);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<Exchange[]>([]);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => setHistory([]), [inst.instance_id]);

  const running = !build || build.status === "running" || build.status === "awaiting_input";
  const hint = !build ? "No build yet" : running ? "I'll take requests once the build finishes" : null;

  const push = (q: string, reply: string, msgId: string | null = null) =>
    setHistory((h) => [{ id: ++nextId, q, reply, msgId }, ...h].slice(0, 3));

  const submit = async () => {
    const q = text.trim();
    const b = useApp.getState().build;
    if (!q || !b || running || busy) return;
    setText("");
    const intent = parseAsk(q);
    let options: SwapOption[] = [];
    if (intent.kind === "swap" || (intent.kind === "question" && intent.topic === "options")) {
      setBusy(true);
      options = await loadOptions(b.build_id, inst).catch(() => []);
      if (!live.current) return;
      setBusy(false);
    }
    const cur = useApp.getState().build;
    const now = cur?.parts.find((p) => p.instance_id === inst.instance_id);
    if (!cur || !now) {
      push(q, "That part is gone from the build.");
      return;
    }
    const out = resolveAsk(intent, { build: cur, instance: now, options });
    const target = { kind: "part" as const, id: now.instance_id };
    if (out.kind === "answer") {
      agentDo({ source: "ask", say: out.say, beats: [{ id: `ask-${nextId + 1}`, target, action: "look", label: now.card.display_name.slice(0, 32), dwellMs: 1600 }] });
      push(q, out.reply);
      return;
    }
    if (cur.status !== "done") {
      push(q, "I can only change parts on a finished build.");
      return;
    }
    const e = useApp.getState().view.edit;
    if (e && (e.phase === "pending" || e.phase === "applying")) {
      push(q, "Hang on, I'm still applying the last change.");
      return;
    }
    // The director adds the beats for edit.applied; this is the bot going to pick the part up.
    agentDo({ source: "ask", say: `On it — ${out.short}`.slice(0, 60), beats: [{ id: `ask-${nextId + 1}`, target, action: "pick", label: out.label.slice(0, 32), dwellMs: 900 }] });
    applyEdit(out.ops, out.label);
    push(q, out.reply, useApp.getState().view.edit?.msg_id ?? null);
  };

  return (
    <section className="ask-bot" aria-label="Ask the bot">
      <h3>Ask the bot</h3>
      <form
        className="ask-bot-row"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <input
          className="ask-bot-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={hint ?? "Ask about or change this part…"}
          aria-label="Ask the bot about this part"
          disabled={running}
          maxLength={200}
        />
        {busy && <span className="spinner" aria-hidden />}
      </form>
      {hint ? (
        <p className="ask-bot-hint">{hint}</p>
      ) : (
        history.length === 0 && <p className="ask-bot-hint">Try "swap for a smaller one", "move it 5mm left", "make it red" or "why this one?"</p>
      )}
      {history.length > 0 && (
        <ul className="ask-bot-log">
          {history.map((x) => {
            const st = x.msgId && edit?.msg_id === x.msgId ? edit : null;
            return (
              <li key={x.id}>
                <span className="ask-bot-q">{x.q}</span>
                <span className="ask-bot-a">
                  {x.reply}
                  {st?.phase === "applied" && <span className="ask-bot-st ok"> Done.</span>}
                  {st?.phase === "rejected" && <span className="ask-bot-st fail"> {st.error?.message ?? "That edit was rejected."}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
