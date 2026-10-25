// Wires the socket (real or FakeSocket) and REST (real or stub) into the store.
// This is the only place that knows about mock mode.
import type { Build, ClientEnvelope, EditOp, ServerEnvelope, ServerPayloads, Vocab, Health } from "../spec/types";
import { CONNECTION_SCOPED } from "../spec/types";
import { createBuild, isKnownEvent, reduceAll } from "../state/reducer";
import { emptyView, editSent, reduceView, type ViewState } from "../state/view";
import { pushLog, showToast, useApp, type CanvasSnapshot } from "../state/store";
import {
  addCompanionCanvas,
  applyStoredCanvases,
  CANVAS_STORE,
  canvasForOpening,
  canvasOfBuild,
  canvasOfStart,
  canvasState,
  closeCanvas,
  foldBuildEvent,
  parseCanvases,
  patchCanvas,
  startedCanvas,
} from "../state/canvases";
import { loadEntry } from "../library/library";
import { Connection, type SocketLike } from "./connection";
import { FakeSocket, MockHub } from "./fakeSocket";
import { readMode, readStoredKey, serverUrl, setAccessToken, setServer, socketUrl, splitKey, storeKey, type Mode } from "./mode";
import { discoverEngine } from "./engine";
import { DefaultLoadingManager } from "three";
import { RestClient, httpFetcher, stubFetcher, paths } from "./rest";
import { linkWhenBuilt } from "../project/awaiting";
import { loadFixtures } from "../spec/fixtures";

let conn: Connection | null = null;
let hellos = 0;
let rest: RestClient = new RestClient(httpFetcher(null));

const RAW_CAP = 4000;
function rawOf(v: unknown): string {
  const s = JSON.stringify(v);
  return s.length > RAW_CAP ? `${s.slice(0, RAW_CAP)}...` : s;
}

function onSent(env: ClientEnvelope, resend: boolean): void {
  pushLog({ dir: "out", type: env.type, msgId: env.msg_id, note: resend ? "resend" : undefined, raw: rawOf(env) });
}

/** Live build events that arrive while a replay is re-performing the same build (bot/replay.ts).
 *  They are held back so they do not land on the half-replayed state, and applied once it ends. */
let heldDuringReplay: ServerEnvelope[] = [];

function onLiveEnvelope(env: ServerEnvelope): void {
  const s = useApp.getState();
  if (s.replaying && env.build_id && s.build && env.build_id === s.build.build_id) {
    heldDuringReplay.push(env);
    return;
  }
  applyServerEnvelope(env);
}

/** Hand back (and forget) the live events held during a replay. */
export function takeHeldDuringReplay(): ServerEnvelope[] {
  const held = heldDuringReplay;
  heldDuringReplay = [];
  return held;
}

/** Apply one incoming server envelope to the store and the event log. Replay feeds recorded
 *  envelopes through here too (note "replay"); it never goes through Connection, so the
 *  connection's per-build seq cursor (gap and duplicate detection) never sees replayed seqs. */
export function applyServerEnvelope(env: ServerEnvelope, opts?: { note?: string }): void {
  const known = isKnownEvent(env.type);
  pushLog({
    dir: "in",
    type: env.type,
    seq: env.seq,
    buildId: env.build_id ?? undefined,
    msgId: (env.payload as { msg_id?: string } | null)?.msg_id ?? env.cause?.msg_id,
    unknown: !known,
    note: known ? opts?.note : "unknown type",
    raw: rawOf(env),
  });
  const now = performance.now();
  const s = useApp.getState();

  if (env.type === "hello") {
    useApp.setState({ hello: env.payload as ServerPayloads["hello"] });
    // after a reconnect the connection resumes the active canvas; builds on the other canvases resume here
    if (++hellos > 1) resumeBackground();
    return;
  }
  if (env.type === "ack") {
    const p = env.payload as ServerPayloads["ack"];
    const starter = canvasOfStart(s, p.msg_id);
    const pending = starter ? canvasState(s, starter)?.pendingStart : null;
    if (starter && pending) {
      if (p.accepted && p.build_id) {
        conn?.setCursor(p.build_id, 0);
        patchCanvas(starter, startedCanvas(pending, p.build_id));
        if (starter === s.activeCanvas) useApp.setState({ screen: "workspace" });
      } else {
        patchCanvas(starter, { pendingStart: null });
        showToast(p.error?.message ?? "The build was not accepted.");
      }
      return;
    }
    const answered = canvasWhere(s, (c) => c.clarifySending === p.msg_id);
    if (answered) {
      patchCanvas(answered, {
        clarifySending: null,
        clarifyError: p.accepted ? null : (p.error?.message ?? "Answer not accepted."),
      });
      return;
    }
    const edited = canvasWhere(s, (c) => c.view.edit?.msg_id === p.msg_id) ?? s.activeCanvas;
    patchCanvas(edited, (c) => ({ view: reduceView(c.view, env, now) }));
    return;
  }
  if (env.type === "error") {
    const p = env.payload as ServerPayloads["error"];
    if (p.error.code === "E_UNKNOWN_BUILD" && canvasWhere(s, (c) => !!c.openedFromLibrary && c.build?.build_id === c.openedFromLibrary)) {
      // A library copy the engine no longer knows still opens for looking; an edit says why it can't apply.
      return;
    }
    if (p.error.code !== "E_RESUME_GAP") showToast(p.error.message);
    return;
  }
  if (CONNECTION_SCOPED.has(env.type)) return;

  // Build-scoped: folded into whichever canvas shows the build, in the background or not.
  if (env.type === "build.snapshot") {
    const b = (env.payload as ServerPayloads["build.snapshot"]).build;
    const target = canvasOfBuild(s, b.build_id) ?? (s.build ? null : s.activeCanvas);
    if (!target) return;
    patchCanvas(target, (c) => foldBuildEvent(c, env, now));
    if (target === s.activeCanvas) useApp.setState({ screen: "workspace" });
    return;
  }
  const target = canvasOfBuild(s, env.build_id);
  if (target) patchCanvas(target, (c) => foldBuildEvent(c, env, now));
}

function canvasWhere(s: ReturnType<typeof useApp.getState>, test: (c: CanvasSnapshot) => boolean): string | null {
  for (const m of s.canvases) {
    const c = canvasState(s, m.id);
    if (c && test(c)) return m.id;
  }
  return null;
}

function isLive(b: Build | null | undefined): b is Build {
  return !!b && (b.status === "running" || b.status === "awaiting_input");
}

function resumeBackground(): void {
  if (!conn) return;
  for (const c of Object.values(useApp.getState().canvasStash)) {
    if (isLive(c.build)) conn.send("build.resume", { build_id: c.build.build_id, last_seq: c.build.last_seq ?? 0 });
  }
}

function onDrop(env: ServerEnvelope, reason: string): void {
  pushLog({ dir: "drop", type: env.type, seq: env.seq, note: reason, raw: rawOf(env) });
}

type Env = { VITE_MOCK?: string; VITE_SERVER_URL?: string; VITE_ENGINE_DISCOVERY?: string };

/** Mode for this page. The deployed site (VITE_ENGINE_DISCOVERY=1) looks up the live engine and
 *  only falls back to the mock when it is offline or the key is missing, and says so on screen. */
async function resolveMode(env: Env): Promise<Mode> {
  const { key: urlKey, search } = splitKey(window.location.search);
  if (urlKey) {
    storeKey(urlKey);
    window.history.replaceState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
  }
  const key = urlKey ?? readStoredKey();
  setAccessToken(key);
  const mode = readMode(search, env);
  if (env.VITE_ENGINE_DISCOVERY !== "1" || mode.mock || mode.server) return mode;
  useApp.setState({ engine: "checking", engineDetail: null });
  const found = await discoverEngine(key);
  if (found.state === "live") {
    useApp.setState({ engine: "live", engineDetail: null });
    return { ...mode, server: found.url };
  }
  useApp.setState({ engine: found.state, engineDetail: found.detail });
  return { ...mode, mock: true };
}

export async function startClient(): Promise<Mode> {
  const mode = await resolveMode(import.meta.env as Env);
  setServer(mode.server);
  useApp.setState({ mode });
  let factory: (url: string) => SocketLike;
  if (mode.mock) {
    const fx = await loadFixtures();
    rest = new RestClient(stubFetcher(fx.rest));
    const server = new MockHub(fx, { speed: mode.speed, forcedFixture: mode.fixture });
    factory = () => new FakeSocket(server);
  } else {
    rest = new RestClient(httpFetcher(mode.server));
    // GLB loaders resolve /assets/... against the page; send them to the remote server instead.
    if (mode.server || readStoredKey()) DefaultLoadingManager.setURLModifier((u) => serverUrl(u));
    factory = (url) => new WebSocket(url) as unknown as SocketLike;
  }
  conn = new Connection({
    url: socketUrl(mode.server ? new URL(mode.server) : window.location),
    socketFactory: factory,
    resumeTarget: () => {
      const b = useApp.getState().build;
      if (!b || b.status === "failed" || b.status === "cancelled") return null;
      return { build_id: b.build_id, last_seq: b.last_seq };
    },
    onEnvelope: onLiveEnvelope,
    onStatus: (status) => useApp.setState({ conn: status }),
    onSent,
    onDrop,
  });
  conn.connect();
  void loadReference();
  void restoreCanvases();
  return mode;
}

function readStoredCanvases(): string | null {
  try {
    return localStorage.getItem(CANVAS_STORE);
  } catch {
    return null;
  }
}

/** A build put back together from its recorded events: the engine's, then the shared library's, then this browser's copy. */
async function fetchBuild(buildId: string, prompt: string): Promise<{ build: Build; view: ViewState; saved: boolean } | null> {
  const fold = (events: ServerEnvelope[], p: string, createdAt?: string) => {
    const now = performance.now();
    return {
      build: reduceAll(createBuild(buildId, p, createdAt), events),
      view: events.reduce((v, e) => reduceView(v, e, now), emptyView()),
    };
  };
  const events: ServerEnvelope[] = [];
  for (let after = 0; ; ) {
    const res = await rest.get<{ events: ServerEnvelope[]; next_after_seq: number; complete: boolean }>(paths.events(buildId, after));
    if (!res.ok) break;
    events.push(...res.body.events);
    if (res.body.complete || res.body.events.length === 0 || res.body.next_after_seq <= after) return { ...fold(events, prompt), saved: false };
    after = res.body.next_after_seq;
  }
  const lib = await rest.get<StoredBuild & { events: ServerEnvelope[] }>(paths.libraryBuild(buildId));
  if (lib.ok && Array.isArray(lib.body.events)) return { ...fold(lib.body.events, lib.body.prompt ?? prompt, lib.body.created_at ?? undefined), saved: true };
  const local = await loadEntry(buildId).catch(() => null);
  if (local) return { build: local.build, view: { ...emptyView(), ...local.view, startAt: null, edit: null }, saved: true };
  return null;
}

/** After a reload: the stored canvas tabs come back, each refetching its build. Running builds pick up their live events again. */
async function restoreCanvases(): Promise<void> {
  const stored = parseCanvases(readStoredCanvases());
  if (!stored) return;
  applyStoredCanvases(stored);
  if (stored.canvases.some((c) => c.id === stored.active && c.build_id)) useApp.setState({ screen: "workspace" });
  let lost = 0;
  await Promise.all(
    stored.canvases.map(async (c) => {
      if (!c.build_id) return;
      const got = await fetchBuild(c.build_id, c.prompt ?? "");
      useApp.setState((s) => ({ canvasRestoring: s.canvasRestoring.filter((id) => id !== c.id) }));
      const now = canvasState(useApp.getState(), c.id);
      // closed, or given a new build, while this one was on its way
      if (!now || now.build || now.pendingStart) return;
      if (!got) {
        lost += 1;
        return;
      }
      patchCanvas(c.id, { build: got.build, view: got.view, openedFromLibrary: got.saved ? got.build.build_id : null });
      if (isLive(got.build) && conn) {
        const seq = got.build.last_seq ?? 0;
        conn.setCursor(got.build.build_id, seq);
        conn.send("build.resume", { build_id: got.build.build_id, last_seq: seq });
      }
    }),
  );
  if (lost) showToast(lost === 1 ? "A canvas couldn't be restored" : `${lost} canvases couldn't be restored`);
}

/** Closes a canvas tab; a build still running on it is stopped. */
export function closeCanvasTab(id: string): void {
  const closed = closeCanvas(id);
  if (isLive(closed?.build) && conn) conn.send("build.cancel", { build_id: closed.build.build_id });
}

async function loadReference(): Promise<void> {
  const [vocab, health] = await Promise.all([rest.get<Vocab>(paths.vocab()), rest.get<Health>(paths.health())]);
  useApp.setState({
    vocab: vocab.ok ? vocab.body : null,
    health: health.ok ? health.body : null,
  });
}

export function getRest(): RestClient {
  return rest;
}

export function isReady(): boolean {
  return conn?.ready ?? false;
}

/**
 * A prompt typed over a finished build may ask for a second device beside it ("add a mouse to the
 * keyboard"): that one is built on a new canvas linked to this one, so both stand in one scene.
 * Anything else starts a build as before. With no engine answer it falls back to that too.
 */
export async function routePrompt(prompt: string): Promise<void> {
  const s = useApp.getState();
  if (s.build?.status === "done" && !s.mode.mock) {
    // The engine's language model reads the request with the open device in view: a second
    // device beside it (told what it pairs with), a change to it, or something else entirely.
    const res = await getRest().request<{ kind: string; prompt: string }>("POST", "/v1/intent", {
      prompt,
      has_build: true,
      build_prompt: s.build.prompt,
      part_names: s.build.parts.map((p) => p.label ?? p.card.display_name),
    });
    if (res.ok && res.body.kind === "companion") {
      linkWhenBuilt(addCompanionCanvas());
      startBuild(res.body.prompt);
      return;
    }
  }
  startBuild(prompt);
}

export function startBuild(prompt: string): void {
  const text = prompt.trim();
  if (!text || !conn) return;
  const s = useApp.getState();
  if (s.build && (s.build.status === "running" || s.build.status === "awaiting_input")) cancelBuild();
  const ts = new Date().toISOString();
  const msgId = conn.send("build.start", {
    prompt: text,
    options: { force_tier: null, commercial_only: false, seed: null },
  });
  useApp.setState({ pendingStart: { msgId, prompt: text, ts, at: performance.now() } });
}

/**
 * Opens a build from the library: shown at once from the saved copy, then the engine is asked to
 * carry on from the last event it sent. If the engine no longer has it (restarted), the saved copy
 * stays on screen to look at.
 */
/** A build already open on a canvas: switch to it rather than load it again. */
function showOpen(buildId: string): boolean {
  if (!canvasOfBuild(useApp.getState(), buildId)) return false;
  canvasForOpening(buildId);
  useApp.setState({ screen: "workspace" });
  return true;
}

export function openSaved(entry: { build: Build; view: ViewState }): void {
  const { build } = entry;
  if (showOpen(build.build_id)) return;
  canvasForOpening(build.build_id);
  useApp.setState({
    build,
    // a build saved by an older version of the app lacks newer view fields (history): fresh ones fill in
    view: { ...emptyView(), ...entry.view, startAt: null, edit: null },
    screen: "workspace",
    selection: null,
    overlay: null,
    focusKey: null,
    moving: null,
    explode: 0,
    dragPose: null,
    dismissedWarnings: [],
    openedFromLibrary: build.build_id,
  });
  if (!conn) return;
  const seq = build.last_seq ?? 0;
  conn.setCursor(build.build_id, seq);
  conn.send("build.resume", { build_id: build.build_id, last_seq: seq });
}

export function cancelBuild(): void {
  const b = useApp.getState().build;
  if (!b || !conn) return;
  conn.send("build.cancel", { build_id: b.build_id });
}

export function answerClarify(answer: { option_id?: string; free_text?: string; skip?: true }): void {
  const b = useApp.getState().build;
  const q = b?.clarify;
  if (!b || !q || !conn) return;
  const msgId = conn.send("clarify.answer", { build_id: b.build_id, question_id: q.question_id, ...answer });
  useApp.setState({ clarifySending: msgId, clarifyError: null });
}

export function applyEdit(ops: EditOp[], label?: string): void {
  const s = useApp.getState();
  const b = s.build;
  if (!b || !conn || ops.length === 0) return;
  // A replay shows an old revision; editing it would be rejected or worse.
  if (s.replaying) {
    showToast("Stop the replay to edit");
    return;
  }
  const msgId = conn.send("edit.apply", { build_id: b.build_id, base_revision: b.revision, ops });
  useApp.setState({ view: editSent(useApp.getState().view, msgId, ops, label) });
}

/** One row of the engine's shared build library (GET /v1/library): the same list for every visitor. */
export interface StoredBuild {
  build_id: string;
  prompt: string;
  device: string | null;
  created_at: string | null;
  status: "done" | "failed";
  hero_url: string | null;
  /** The finished device alone, rendered by scripts/render-shots.mjs; null until it has been. */
  shot_url?: string | null;
}

/** Stored builds, newest first. Mock mode and an engine without a library both give an empty list. */
export async function fetchLibrary(): Promise<StoredBuild[]> {
  const res = await rest.get<{ builds: StoredBuild[] }>(paths.library());
  return res.ok && Array.isArray(res.body.builds) ? res.body.builds : [];
}

/** Shows a stored build by feeding its recorded events through the same handler as a live socket. */
export async function openLibraryBuild(buildId: string): Promise<boolean> {
  if (showOpen(buildId)) return true;
  const res = await rest.get<StoredBuild & { events: ServerEnvelope[] }>(paths.libraryBuild(buildId));
  if (!res.ok) {
    showToast(res.error.message);
    return false;
  }
  const { events, prompt, created_at } = res.body;
  canvasForOpening(buildId);
  useApp.setState({
    build: createBuild(buildId, prompt, created_at ?? undefined),
    view: emptyView(performance.now()),
    openedFromLibrary: buildId,
    pendingStart: null,
    screen: "workspace",
    selection: null,
    overlay: null,
    focusKey: null,
    dismissedWarnings: [],
    explode: 0,
    dragPose: null,
  });
  for (const env of events) applyServerEnvelope(env);
  // follow it from here on: the engine brings a stored build back to life, so edits, undo and
  // history work on it like on one just built
  const last = events.reduce((m, e) => Math.max(m, e.seq ?? 0), 0);
  if (conn && last) {
    conn.setCursor(buildId, last);
    conn.send("build.resume", { build_id: buildId, last_seq: last });
  }
  return true;
}

/** Put the open build back the way it was at an earlier version (undo, redo, history). */
export async function restoreRevision(revision: number): Promise<boolean> {
  const b = useApp.getState().build;
  if (!b) return false;
  const res = await rest.request<{ revision: number }>("POST", `/v1/builds/${encodeURIComponent(b.build_id)}/restore`, { revision });
  if (!res.ok) showToast(res.error.message);
  return res.ok;
}

export async function deleteLibraryBuild(buildId: string): Promise<boolean> {
  const res = await rest.delete<{ deleted: string }>(paths.libraryBuild(buildId));
  if (!res.ok && res.status !== 404) {
    showToast(res.error.message);
    return false;
  }
  return true;
}
