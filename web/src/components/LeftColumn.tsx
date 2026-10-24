import { useEffect, useMemo, useState } from "react";
import { useApp } from "../state/store";
import { answerClarify, cancelBuild, getRest } from "../net/client";
import { paths } from "../net/rest";
import { STAGE_IDS } from "../spec/types";
import type { Candidate, ClarifyResolution, DesignCard, Requirement, Slot, Spec } from "../spec/types";
import { Badge, Chip, Empty, Panel, ProvenanceBadge, Skeleton, useNow } from "../ui/common";
import { fmtMs, fmtValue, known, vlabel, vocabEntry, type Tone } from "../ui/format";
import type { StageView } from "../state/view";

/** C04 StageTimeline. */
export function StageTimeline() {
  const stages = useApp((s) => s.view.stages);
  const vocab = useApp((s) => s.vocab);
  const anyActive = Object.values(stages).some((s) => s.status === "active");
  const now = useNow(anyActive, 50);
  const total = useApp((s) => s.view.done?.total_ms ?? s.view.doneMs);
  return (
    <Panel title="Pipeline" meta={total !== null && total !== undefined ? fmtMs(total) : undefined} className="timeline">
      <ol className="stages">
        {STAGE_IDS.map((id) => (
          <StageRow key={id} stage={stages[id] ?? { id, status: "pending" }} now={now} label={vlabel(vocab, "stages", id)} vocabBudget={vocabEntry(vocab, "stages", id)?.budget_ms} />
        ))}
      </ol>
    </Panel>
  );
}

/** Compact C04 for the left panel header (Figma step player): one dot per stage, the active one stretched into a bar. */
export function StepPlayer() {
  const stages = useApp((s) => s.view.stages);
  const vocab = useApp((s) => s.vocab);
  const done = useApp((s) => s.build?.status === "done");
  const active = STAGE_IDS.find((id) => stages[id]?.status === "active" || stages[id]?.status === "needs_input");
  const failed = STAGE_IDS.find((id) => stages[id]?.status === "failed");
  const label = failed
    ? `${vlabel(vocab, "stages", failed)} failed`
    : active
      ? vlabel(vocab, "stages", active)
      : done
        ? "Done"
        : "";
  return (
    <div className="step-player" aria-label="Build progress">
      <span className="step-dots">
        {STAGE_IDS.map((id) => {
          const st = stages[id]?.status ?? "pending";
          return <span key={id} className={`step-dot st-${st}`} title={`${vlabel(vocab, "stages", id)}: ${st}`} />;
        })}
      </span>
      {label && <span className={`step-label ${failed ? "tone-text-fail" : ""}`}>{label}</span>}
    </div>
  );
}

const STAGE_TONE: Record<string, Tone> = {
  ok: "ok",
  skipped: "muted",
  degraded: "warn",
  failed: "fail",
  needs_input: "accent",
  active: "accent",
  pending: "muted",
  unknown: "info",
};

function StageRow(props: { stage: StageView; now: number; label: string; vocabBudget?: number }) {
  const { stage } = props;
  const budget = stage.budget_ms ?? props.vocabBudget;
  const elapsed =
    stage.status === "active" && stage.startedAt !== undefined ? props.now - stage.startedAt : (stage.duration_ms ?? null);
  const over = budget !== undefined && elapsed !== null && elapsed > budget;
  const frac = budget && elapsed !== null ? Math.min(1, elapsed / budget) : 0;
  const statusText = stage.status === "needs_input" ? "needs input" : stage.status;
  return (
    <li data-agent={`stage:${stage.id}`} className={`stage st-${stage.status} ${over ? "over" : ""}`}>
      <span className={`stage-dot tone-${STAGE_TONE[stage.status] ?? "info"}`} />
      <span className="stage-label">{props.label}</span>
      <span className="stage-time mono">
        {elapsed !== null && stage.status !== "skipped" ? `${Math.round(elapsed)}` : ""}
        {budget !== undefined && <span className="muted"> / {budget} ms</span>}
      </span>
      <span className="stage-status">{statusText}</span>
      {(stage.status === "active" || stage.duration_ms !== undefined) && stage.status !== "skipped" && (
        <span className="stage-bar">
          <span style={{ width: `${Math.max(2, frac * 100)}%` }} />
        </span>
      )}
      {stage.message && <span className="stage-msg">{stage.message}</span>}
    </li>
  );
}

/** C30 ClarifyCard. */
export function ClarifyCard() {
  const build = useApp((s) => s.build);
  const sending = useApp((s) => s.clarifySending);
  const error = useApp((s) => s.clarifyError);
  const q = build?.clarify ?? null;
  const [text, setText] = useState("");
  const [sentFor, setSentFor] = useState<string | null>(null);
  const [askedAt, setAskedAt] = useState<number>(() => performance.now());
  useEffect(() => {
    setAskedAt(performance.now());
    setText("");
    setSentFor(null);
  }, [q?.question_id, q?.round]);
  useEffect(() => {
    if (error) setSentFor(null);
  }, [error]);
  const now = useNow(q !== null, 250);
  const resolved = build?.clarifications ?? [];
  if (!q) {
    if (!resolved.length || build?.status === "failed" || build?.status === "cancelled") return null;
    return (
      <Panel title="Clarified" className="clarify resolved">
        {resolved.map((r) => (
          <ResolvedRow key={`${r.question_id}`} r={r} />
        ))}
      </Panel>
    );
  }
  const timeout = q.timeout_ms ?? 60_000;
  const left = Math.max(0, Math.ceil((timeout - (now - askedAt)) / 1000));
  const locked = sending !== null || sentFor === q.question_id;
  const send = (a: { option_id?: string; free_text?: string; skip?: true }) => {
    if (locked) return;
    setSentFor(q.question_id);
    answerClarify(a);
  };
  return (
    <Panel title={`Question ${q.round > 1 ? q.round : ""}`.trim()} meta={<span className="mono">{left}s</span>} className="clarify asking">
      <p className="clarify-q">{q.question}</p>
      {q.reason && <p className="muted small">{q.reason}</p>}
      <div className="clarify-options">
        {q.options.map((o) => (
          <button
            key={o.option_id}
            type="button"
            className={`btn option ${o.option_id === q.default_option_id ? "default" : ""}`}
            disabled={locked}
            onClick={() => send({ option_id: o.option_id })}
          >
            <span>{o.label}</span>
            {o.description && <span className="muted small">{o.description}</span>}
          </button>
        ))}
      </div>
      {q.allow_free_text && (
        <form
          className="clarify-free"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) send({ free_text: text.trim() });
          }}
        >
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Or say it in your words" disabled={locked} aria-label="Answer" />
          <button type="submit" className="btn sm" disabled={locked || !text.trim()}>
            Send
          </button>
        </form>
      )}
      <div className="clarify-foot">
        {q.allow_skip && (
          <button type="button" className="btn ghost sm" disabled={locked} onClick={() => send({ skip: true })}>
            Just pick
          </button>
        )}
        <button type="button" className="btn ghost sm" onClick={cancelBuild}>
          Cancel build
        </button>
        {locked && <span className="muted small">Sending</span>}
        {error && <span className="tone-text-fail small">{error}</span>}
      </div>
      {left === 0 && <p className="muted small">Time is up; the server will pick the default.</p>}
    </Panel>
  );
}

function ResolvedRow(props: { r: ClarifyResolution }) {
  const { r } = props;
  const res = known(r.resolution, ["answered_option", "answered_text", "skipped", "timeout"] as const);
  return (
    <div className="resolved-row">
      <span className="muted small">{r.question_id}</span>
      {res === "answered_option" && <Chip tone="accent" variant="solid">{r.option_id ?? ""}</Chip>}
      {res === "answered_text" && <Chip tone="accent">{r.free_text ?? ""}</Chip>}
      {(res === "skipped" || res === "timeout" || res === "unknown") && <Chip tone="muted">{res === "timeout" ? "timed out" : "picked for you"}</Chip>}
      {r.assumptions.map((a) => (
        <Chip key={a.assumption_id} tone="info" title={a.reason ?? undefined}>
          {a.label}
        </Chip>
      ))}
    </div>
  );
}

function reqLabel(r: Requirement): string {
  return r.label ?? `${r.facet} ${r.op} ${fmtValue(r.value, r.unit)}`;
}

/** C07 SpecCard. */
export function SpecCard() {
  const spec = useApp((s) => s.build?.spec ?? null);
  const prompt = useApp((s) => s.build?.prompt ?? "");
  const vocab = useApp((s) => s.vocab);
  const running = useApp((s) => s.build?.status === "running");
  const [hover, setHover] = useState<number[] | null>(null);
  if (!spec) {
    return (
      <Panel title="Spec">
        {running ? <Skeleton lines={3} /> : <Empty>The spec appears once the request is understood.</Empty>}
      </Panel>
    );
  }
  return (
    <Panel title="Spec" meta={<ClassifierMeta spec={spec} />}>
      <p className="spec-prompt">
        <Highlighted text={spec.prompt || prompt} span={hover} />
      </p>
      <div className="kv">
        <span>Device</span>
        <span>{vlabel(vocab, "device_classes", spec.device_class)}</span>
        <span>Path</span>
        <span className="muted">{spec.taxonomy_path.join(" / ")}</span>
      </div>
      <div className="chips">
        {spec.hard_requirements.map((r) => (
          <Chip key={r.req_id} tone="accent" variant="solid" title={`${r.req_id} hard, ${r.source ?? ""}`} onMouseEnter={() => setHover(r.text_span ?? null)} onMouseLeave={() => setHover(null)}>
            {reqLabel(r)}
          </Chip>
        ))}
        {spec.soft_requirements.map((r) => (
          <Chip key={r.req_id} tone="accent" variant="outline" title={`${r.req_id} soft, ${r.source ?? ""}`} onMouseEnter={() => setHover(r.text_span ?? null)} onMouseLeave={() => setHover(null)}>
            {reqLabel(r)}
          </Chip>
        ))}
      </div>
      {spec.functions.length > 0 && (
        <div className="chips">
          {spec.functions.map((f) => (
            <Chip key={f.function_id} tone={f.required ? "muted" : "info"} title={f.source}>
              {vlabel(vocab, "functions", f.function_id)}
              {f.count && f.count > 1 ? ` x${f.count}` : ""}
              {!f.required ? " (optional)" : ""}
            </Chip>
          ))}
        </div>
      )}
      {(spec.assumptions ?? []).length > 0 && (
        <div className="chips">
          {(spec.assumptions ?? []).map((a) => (
            <Chip key={a.assumption_id} tone="info" title={a.reason ?? undefined}>
              Assumed: {a.label}
            </Chip>
          ))}
        </div>
      )}
    </Panel>
  );
}

function ClassifierMeta(props: { spec: Spec }) {
  const c = props.spec.classifier;
  return (
    <span className="mono small">
      {c.stage} {Math.round(c.confidence * 100)}%{c.provider ? ` ${c.provider}` : ""}
      {c.fallback ? " fallback" : ""}
    </span>
  );
}

function Highlighted(props: { text: string; span: number[] | null }) {
  const { text, span } = props;
  if (!span || span.length < 2 || span[0] >= span[1]) return <>{text}</>;
  return (
    <>
      {text.slice(0, span[0])}
      <mark>{text.slice(span[0], span[1])}</mark>
      {text.slice(span[1])}
    </>
  );
}

const TIER_TONE: Record<string, Tone> = { exact: "ok", substitute: "accent", compose: "accent", unknown: "muted" };

/** C08 ReuseCard. */
export function ReuseCard() {
  const reuse = useApp((s) => s.view.reuse);
  const tierRaw = useApp((s) => s.build?.tier);
  const designId = useApp((s) => s.build?.design_id ?? null);
  const spec = useApp((s) => s.build?.spec ?? null);
  const running = useApp((s) => s.build?.status === "running");
  const [design, setDesign] = useState<DesignCard | null>(null);
  useEffect(() => {
    setDesign(null);
    if (!designId || reuse?.design) return;
    let live = true;
    void getRest()
      .get<{ design: DesignCard }>(paths.design(designId))
      .then((r) => {
        if (live && r.ok) setDesign((r.body as { design?: DesignCard }).design ?? null);
      });
    return () => {
      live = false;
    };
  }, [designId, reuse?.design]);
  const tier = known(tierRaw, ["exact", "substitute", "compose"] as const);
  const reqs = new Map([...(spec?.hard_requirements ?? []), ...(spec?.soft_requirements ?? [])].map((r) => [r.req_id, r]));
  if (!reuse && tier === "unknown") {
    return <Panel title="Design reuse">{running && spec ? <Skeleton /> : <Empty>Waiting for the spec.</Empty>}</Panel>;
  }
  const card = reuse?.design ?? design;
  return (
    <Panel title="Design reuse" meta={<Badge tone={TIER_TONE[tier]}>{tier}</Badge>}>
      {card && (
        <div className="design-card">
          <div>
            <strong>{card.name}</strong>
            {card.licence_spdx && <span className="muted small"> {card.licence_spdx}</span>}
          </div>
          {card.summary && <p className="muted small">{card.summary}</p>}
          {card.repo_url && (
            <a className="small" href={card.repo_url} target="_blank" rel="noreferrer noopener">
              {card.repo_url.replace(/^https?:\/\//, "")}
            </a>
          )}
        </div>
      )}
      {reuse?.reason && <p className="reason">{reuse.reason}</p>}
      {(reuse?.considered ?? []).length > 0 && (
        <ul className="considered">
          {reuse?.considered.map((c) => (
            <li key={c.design_id} className={c.design_id === reuse.design_id ? "chosen" : ""}>
              <span>{c.name}</span>
              <span className="mono muted small">{c.score !== null && c.score !== undefined ? c.score.toFixed(2) : ""}</span>
              <span className="chips">
                {(c.unmet ?? []).map((u) => (
                  <Chip key={u} tone="warn" title="Unmet requirement">
                    {reqs.get(u) ? reqLabel(reqs.get(u) as Requirement) : u}
                  </Chip>
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

const SLOT_TONE: Record<string, Tone> = {
  pending: "muted",
  narrowing: "accent",
  decided: "ok",
  none: "info",
  dead_end: "fail",
  unknown: "info",
};

/** C06 DecisionTrace. */
export function DecisionTrace() {
  const slots = useApp((s) => s.build?.slots ?? []);
  const sorted = useMemo(() => [...slots].sort((a, b) => (a.order ?? 999) - (b.order ?? 999)), [slots]);
  return (
    <Panel title="Decisions" meta={slots.length ? `${slots.filter((s) => s.state === "decided").length}/${slots.length}` : undefined} className="decisions">
      {sorted.length === 0 ? <Empty>Slots appear after the design step.</Empty> : sorted.map((s) => <SlotRow key={s.slot_id} slot={s} />)}
    </Panel>
  );
}

function SlotRow(props: { slot: Slot }) {
  const { slot } = props;
  const decisions = useApp((s) => s.build?.decisions ?? []);
  const candidates = useApp((s) => s.view.candidates[slot.slot_id]);
  const parts = useApp((s) => s.build?.parts ?? []);
  const vocab = useApp((s) => s.vocab);
  const selection = useApp((s) => s.selection);
  const decision = [...decisions].reverse().find((d) => d.slot_id === slot.slot_id);
  const last = candidates?.[candidates.length - 1];
  const state = known(slot.state, ["pending", "narrowing", "decided", "none", "dead_end"] as const);
  const instances = slot.instance_ids ?? parts.filter((p) => p.slot_id === slot.slot_id).map((p) => p.instance_id);
  const selected = selection !== null && instances.includes(selection);
  const chosenCard =
    parts.find((p) => p.part_id === (decision?.chosen_part_id ?? slot.chosen_part_id))?.card ??
    last?.survivors.find((c) => c.card.part_id === decision?.chosen_part_id)?.card;
  const pickCandidate = (c: Candidate) => {
    const inst = parts.find((p) => p.slot_id === slot.slot_id && p.part_id === c.card.part_id);
    if (inst) useApp.setState({ selection: inst.instance_id, overlay: "inspector", inspectPartId: null });
    else useApp.setState({ selection: null, overlay: "inspector", inspectPartId: c.card.part_id });
  };
  return (
    <div data-agent={`slot:${slot.slot_id}`} className={`slot st-${state} ${selected ? "selected" : ""}`}>
      <button
        type="button"
        className="slot-head"
        onClick={() => instances[0] && useApp.setState({ selection: instances[0], overlay: "inspector", inspectPartId: null })}
      >
        <span className={`dot tone-${SLOT_TONE[state]}`} />
        <span className="slot-label">{slot.label}</span>
        {known(slot.criticality, ["critical", "optional"] as const) === "optional" && <span className="muted small">optional</span>}
        <span className="slot-count mono small">
          {slot.candidates_total ?? ""}
          {slot.candidates_left !== null && slot.candidates_left !== undefined ? ` → ${slot.candidates_left}` : ""}
        </span>
        <span className="slot-state small">{state.replace("_", " ")}</span>
      </button>
      {last && last.filters.length > 0 && (state === "narrowing" || state === "dead_end" || state === "decided" || state === "none") && (
        <div className="filters">
          {last.filters.map((f, i) => (
            <Chip key={i} tone={f.count_after === 0 ? "fail" : "muted"} title={`${f.facet} ${f.op} ${fmtValue(f.value)} (${f.reason})`}>
              {f.label ?? f.facet}{" "}
              <span className="mono">
                {f.count_before ?? ""} → {f.count_after ?? ""}
              </span>
            </Chip>
          ))}
        </div>
      )}
      {decision && (
        <div className="decision" data-agent={`decision:${decision.decision_id}`}>
          {chosenCard ? (
            <div className="chosen">
              <strong>{chosenCard.display_name}</strong> <ProvenanceBadge card={chosenCard} />
            </div>
          ) : decision.chosen_part_id === null ? (
            <div className="chosen muted">Nothing chosen</div>
          ) : null}
          <p className="reason">{decision.reason}</p>
          <div className="decision-meta small muted">
            <span>{decision.method.replace("_", " ")}</span>
            {decision.model && (
              <span className="mono">
                {decision.model.provider} {decision.model.model} {fmtMs(decision.model.latency_ms)}
                {decision.model.cached ? " cached" : ""}
                {decision.model.fallback ? " fallback" : ""}
              </span>
            )}
          </div>
          {decision.method === "model_pick" && last && last.survivors.length > 0 && (
            <ol className="survivors">
              {last.survivors.slice(0, 8).map((c) => (
                <li key={c.short_id} className={c.card.part_id === decision.chosen_part_id ? "winner" : ""}>
                  <button type="button" onClick={() => pickCandidate(c)}>
                    <span className="mono">{c.short_id}</span>
                    <span>{c.card.display_name}</span>
                    <span className="mono muted small">{c.score !== null && c.score !== undefined ? c.score.toFixed(2) : ""}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
          {(decision.propagated ?? []).length > 0 && (
            <div className="propagated small muted">
              {decision.propagated?.map((p) => (
                <span key={p.slot_id}>
                  {p.slot_id}: <span className="mono">{p.count_before} → {p.count_after}</span>
                  {p.constraint ? ` (${p.constraint})` : ""}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {!decision && state === "narrowing" && <Skeleton lines={1} />}
      {state === "dead_end" && <p className="reason tone-text-fail">{vlabel(vocab, "functions", slot.function_id)}: no part meets every requirement.</p>}
    </div>
  );
}
