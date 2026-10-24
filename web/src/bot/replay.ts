// Replay: re-perform a finished build. The build's recorded events are fed again, in seq order and
// with their original relative timing (divided by the chosen speed, long pauses capped), through the
// same apply path live events take (net/client.ts applyServerEnvelope). The scene re-assembles, the
// panels fill in, and the on-stage bot reacts to every replayed "in" log entry. Nothing is sent to
// the server, and replayed envelopes never go through Connection, so its seq cursor is untouched.
import { create } from "zustand";
import type { Build, ServerEnvelope } from "../spec/types";
import { CONNECTION_SCOPED } from "../spec/types";
import { createBuild } from "../state/reducer";
import { emptyView, reduceView } from "../state/view";
import { showToast, useApp, type LogEntry } from "../state/store";
import { applyServerEnvelope, getRest, takeHeldDuringReplay } from "../net/client";

export const SPEEDS = [0.5, 1, 2, 4] as const;
export type ReplaySpeed = (typeof SPEEDS)[number];

/** Longest pause between two replayed events, before speed is applied. */
export const MAX_GAP_MS = 1500;
/** Step used when the source has no usable timing at all. */
export const FALLBACK_STEP_MS = 150;

export interface TimedEvent {
  env: ServerEnvelope;
  /** Original arrival time in ms (any epoch); NaN when unknown. */
  at: number;
}

export interface ScheduledEvent {
  env: ServerEnvelope;
  /** Offset from the start of the replay, in ms. */
  delay: number;
}

/** Build-scoped, replayable: snapshots would jump straight to the end, so they are left out. */
function replayable(env: ServerEnvelope | null, buildId: string): env is ServerEnvelope {
  return (
    !!env &&
    typeof env.type === "string" &&
    typeof env.seq === "number" &&
    env.build_id === buildId &&
    env.type !== "build.snapshot" &&
    !CONNECTION_SCOPED.has(env.type)
  );
}

function bySeqUnique(events: TimedEvent[]): TimedEvent[] {
  const seen = new Set<number>();
  const out: TimedEvent[] = [];
  for (const e of [...events].sort((a, b) => a.env.seq - b.env.seq)) {
    if (seen.has(e.env.seq)) continue;
    seen.add(e.env.seq);
    out.push(e);
  }
  return out;
}

/** Events of one build recovered from the event log (raw is capped, so oversized ones are lost). */
export function eventsFromLog(log: LogEntry[], buildId: string): TimedEvent[] {
  const out: TimedEvent[] = [];
  for (const entry of log) {
    if (entry.dir !== "in" || entry.note === "replay") continue;
    let env: ServerEnvelope | null = null;
    try {
      env = JSON.parse(entry.raw) as ServerEnvelope;
    } catch {
      continue;
    }
    if (replayable(env, buildId)) out.push({ env, at: entry.t });
  }
  return bySeqUnique(out);
}

/** Events of one build from GET /v1/builds/{id}/events, timed by their envelope ts. */
export function eventsFromEnvelopes(envs: ServerEnvelope[], buildId: string): TimedEvent[] {
  return bySeqUnique(envs.filter((e) => replayable(e, buildId)).map((env) => ({ env, at: Date.parse(env.ts) })));
}

/** When each event fires, relative to the start: original gaps, capped at maxGap, divided by speed. */
export function buildSchedule(events: TimedEvent[], speed: number, maxGap = MAX_GAP_MS): ScheduledEvent[] {
  const rate = speed > 0 && Number.isFinite(speed) ? speed : 1;
  const timed = events.length > 1 && events.every((e) => Number.isFinite(e.at));
  const out: ScheduledEvent[] = [];
  let t = 0;
  events.forEach((e, i) => {
    if (i > 0) {
      const raw = timed ? e.at - events[i - 1].at : FALLBACK_STEP_MS;
      t += Math.min(Math.max(raw, 0), maxGap) / rate;
    }
    out.push({ env: e.env, delay: t });
  });
  return out;
}

// ---- Runtime ----

interface ReplayUi {
  speed: ReplaySpeed;
  /** 0..1 while replaying. */
  progress: number;
  loading: boolean;
}

export const useReplay = create<ReplayUi>(() => ({ speed: 1, progress: 0, loading: false }));

export function setReplaySpeed(speed: ReplaySpeed): void {
  useReplay.setState({ speed });
}

interface Run {
  original: Build;
  schedule: ScheduledEvent[];
  index: number;
  startedAt: number;
  timer: ReturnType<typeof setTimeout> | null;
}

let run: Run | null = null;
/** Events per build, so a second replay does not depend on what the log still holds. */
const sourceCache = new Map<string, TimedEvent[]>();

interface EventsPage {
  events: ServerEnvelope[];
  next_after_seq: number;
  complete?: boolean;
}

async function fetchEvents(buildId: string): Promise<TimedEvent[]> {
  const all: ServerEnvelope[] = [];
  let after = 0;
  for (let page = 0; page < 20; page++) {
    const res = await getRest().get<EventsPage>(`/v1/builds/${encodeURIComponent(buildId)}/events?after_seq=${after}&limit=5000`);
    if (!res.ok || !Array.isArray(res.body?.events)) break;
    all.push(...res.body.events);
    const next = res.body.next_after_seq;
    if (res.body.complete || res.body.events.length === 0 || typeof next !== "number" || next <= after) break;
    after = next;
  }
  return eventsFromEnvelopes(all, buildId);
}

async function sourceEvents(build: Build): Promise<TimedEvent[]> {
  const cached = sourceCache.get(build.build_id);
  if (cached) return cached;
  const fromRest = await fetchEvents(build.build_id);
  const fromLog = eventsFromLog(useApp.getState().log, build.build_id);
  // The server keeps the whole stream; the log is capped and truncates large payloads.
  const events = fromRest.length >= fromLog.length ? fromRest : fromLog;
  if (events.length > 0) sourceCache.set(build.build_id, events);
  return events;
}

export function canReplay(build: Build | null): boolean {
  return !!build && (build.status === "done" || build.status === "failed");
}

export async function startReplay(speed: ReplaySpeed = useReplay.getState().speed): Promise<void> {
  const s = useApp.getState();
  const build = s.build;
  if (run || s.replaying || useReplay.getState().loading || !canReplay(build) || !build) return;
  useReplay.setState({ speed, loading: true });
  const events = await sourceEvents(build).catch(() => [] as TimedEvent[]);
  useReplay.setState({ loading: false });
  // The user may have moved on while the events loaded.
  if (useApp.getState().build !== build || useApp.getState().replaying) return;
  if (events.length === 0) {
    showToast("Nothing to replay for this build.");
    return;
  }
  run = { original: build, schedule: buildSchedule(events, speed), index: 0, startedAt: performance.now(), timer: null };
  useApp.setState({
    build: createBuild(build.build_id, build.prompt, build.created_at),
    view: emptyView(performance.now()),
    replaying: true,
    selection: null,
    inspectPartId: null,
    overlay: null,
    moving: null,
    dragPose: null,
    explode: 0,
  });
  useReplay.setState({ progress: 0 });
  tick();
}

function tick(): void {
  const r = run;
  if (!r) return;
  r.timer = null;
  // Another build took over (new prompt): abandon without touching it.
  if (useApp.getState().build?.build_id !== r.original.build_id) {
    end(false);
    return;
  }
  const elapsed = performance.now() - r.startedAt;
  while (r.index < r.schedule.length && r.schedule[r.index].delay <= elapsed) {
    applyServerEnvelope(r.schedule[r.index].env, { note: "replay" });
    r.index++;
  }
  useReplay.setState({ progress: r.index / r.schedule.length });
  if (r.index >= r.schedule.length) {
    end(true);
    return;
  }
  r.timer = setTimeout(tick, Math.max(0, r.schedule[r.index].delay - elapsed));
}

/** Finish: the rest of the view catches up instantly, the build is exactly the original again. */
function end(restore: boolean): void {
  const r = run;
  if (!r) {
    if (useApp.getState().replaying) useApp.setState({ replaying: false });
    return;
  }
  if (r.timer) clearTimeout(r.timer);
  run = null;
  if (restore) {
    let view = useApp.getState().view;
    const now = performance.now();
    for (let i = r.index; i < r.schedule.length; i++) view = reduceView(view, r.schedule[i].env, now);
    useApp.setState({ build: r.original, view, replaying: false });
  } else {
    useApp.setState({ replaying: false });
  }
  useReplay.setState({ progress: 0 });
  for (const env of takeHeldDuringReplay()) applyServerEnvelope(env);
}

export function stopReplay(): void {
  end(true);
}

export function toggleReplay(): void {
  if (run || useApp.getState().replaying) stopReplay();
  else void startReplay();
}

/** Test hook. */
export function _resetReplayForTests(): void {
  if (run?.timer) clearTimeout(run.timer);
  run = null;
  sourceCache.clear();
}
