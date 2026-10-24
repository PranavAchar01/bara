// Wires the socket (real or FakeSocket) and REST (real or stub) into the store.
// This is the only place that knows about mock mode.
import type { ClientEnvelope, EditOp, ServerEnvelope, ServerPayloads, Vocab, Health } from "../spec/types";
import { CONNECTION_SCOPED } from "../spec/types";
import { createBuild, isKnownEvent, reduceBuild } from "../state/reducer";
import { emptyView, editSent, reduceView } from "../state/view";
import { pushLog, showToast, useApp } from "../state/store";
import { Connection, type SocketLike } from "./connection";
import { FakeSocket, MockServer } from "./fakeSocket";
import { readMode, socketUrl, type Mode } from "./mode";
import { RestClient, httpFetcher, stubFetcher, paths } from "./rest";
import { loadFixtures } from "../spec/fixtures";

let conn: Connection | null = null;
let rest: RestClient = new RestClient(httpFetcher);

const RAW_CAP = 4000;
function rawOf(v: unknown): string {
  const s = JSON.stringify(v);
  return s.length > RAW_CAP ? `${s.slice(0, RAW_CAP)}...` : s;
}

function onSent(env: ClientEnvelope, resend: boolean): void {
  pushLog({ dir: "out", type: env.type, msgId: env.msg_id, note: resend ? "resend" : undefined, raw: rawOf(env) });
}

function onEnvelope(env: ServerEnvelope): void {
  const known = isKnownEvent(env.type);
  pushLog({
    dir: "in",
    type: env.type,
    seq: env.seq,
    msgId: (env.payload as { msg_id?: string } | null)?.msg_id ?? env.cause?.msg_id,
    unknown: !known,
    note: known ? undefined : "unknown type",
    raw: rawOf(env),
  });
  const now = performance.now();
  const s = useApp.getState();

  if (env.type === "hello") {
    useApp.setState({ hello: env.payload as ServerPayloads["hello"] });
    return;
  }
  if (env.type === "ack") {
    const p = env.payload as ServerPayloads["ack"];
    if (s.pendingStart && p.msg_id === s.pendingStart.msgId) {
      if (p.accepted && p.build_id) {
        conn?.setCursor(p.build_id, 0);
        useApp.setState({
          build: createBuild(p.build_id, s.pendingStart.prompt, s.pendingStart.ts),
          view: emptyView(s.pendingStart.at),
          pendingStart: null,
          screen: "workspace",
          selection: null,
          overlay: null,
          dismissedWarnings: [],
          explode: 0,
          dragPose: null,
        });
      } else {
        useApp.setState({ pendingStart: null });
        showToast(p.error?.message ?? "The build was not accepted.");
      }
      return;
    }
    if (s.clarifySending && p.msg_id === s.clarifySending) {
      useApp.setState({
        clarifySending: null,
        clarifyError: p.accepted ? null : (p.error?.message ?? "Answer not accepted."),
      });
      return;
    }
    useApp.setState({ view: reduceView(s.view, env, now) });
    return;
  }
  if (env.type === "error") {
    const p = env.payload as ServerPayloads["error"];
    if (p.error.code !== "E_RESUME_GAP") showToast(p.error.message);
    return;
  }
  if (CONNECTION_SCOPED.has(env.type)) return;

  // Build-scoped.
  if (env.type === "build.snapshot") {
    const b = (env.payload as ServerPayloads["build.snapshot"]).build;
    if (!s.build || s.build.build_id === b.build_id) {
      useApp.setState({
        build: b,
        view: reduceView(s.build ? s.view : emptyView(), env, now),
        screen: "workspace",
      });
    }
    return;
  }
  if (!s.build || env.build_id !== s.build.build_id) return;
  const build = reduceBuild(s.build, env);
  const view = reduceView(s.view, env, now);
  const patch: Partial<ReturnType<typeof useApp.getState>> = { build, view };
  if (env.type === "placement.updated" && s.dragPose) patch.dragPose = null;
  if (env.type === "edit.rejected" && s.dragPose) patch.dragPose = null;
  if (env.type === "part.removed" && s.selection === (env.payload as { instance_id?: string }).instance_id) {
    patch.selection = null;
    patch.overlay = null;
  }
  if (env.type === "build.failed" || env.type === "clarify.resolved") patch.clarifySending = null;
  useApp.setState(patch);
}

function onDrop(env: ServerEnvelope, reason: string): void {
  pushLog({ dir: "drop", type: env.type, seq: env.seq, note: reason, raw: rawOf(env) });
}

export async function startClient(): Promise<Mode> {
  const mode = readMode(window.location.search, import.meta.env as { VITE_MOCK?: string });
  useApp.setState({ mode });
  let factory: (url: string) => SocketLike;
  if (mode.mock) {
    const fx = await loadFixtures();
    rest = new RestClient(stubFetcher(fx.rest));
    const server = new MockServer(fx, { speed: mode.speed, forcedFixture: mode.fixture });
    factory = () => new FakeSocket(server);
  } else {
    rest = new RestClient(httpFetcher);
    factory = (url) => new WebSocket(url) as unknown as SocketLike;
  }
  conn = new Connection({
    url: socketUrl(window.location),
    socketFactory: factory,
    resumeTarget: () => {
      const b = useApp.getState().build;
      if (!b || b.status === "failed" || b.status === "cancelled") return null;
      return { build_id: b.build_id, last_seq: b.last_seq };
    },
    onEnvelope,
    onStatus: (status) => useApp.setState({ conn: status }),
    onSent,
    onDrop,
  });
  conn.connect();
  void loadReference();
  return mode;
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
  const msgId = conn.send("edit.apply", { build_id: b.build_id, base_revision: b.revision, ops });
  useApp.setState({ view: editSent(useApp.getState().view, msgId, ops, label) });
}
