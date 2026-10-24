// SPEC 13 mock mode: a fake socket that replays stream fixtures. The MockServer
// persists across reconnects (like the real server) so resume works.
import type { FixtureSet } from "../spec/fixtures";
import type { ClientEnvelope, EditOp, FixtureStep, ServerEnvelope, StreamFixture } from "../spec/types";
import { CONNECTION_SCOPED, SPEC_VERSION } from "../spec/types";
import type { SocketLike } from "./connection";

export const DEFAULT_FIXTURE = "compose_wireless_split_oled";
export const MOCK_EDIT_FALLBACK = "edit_rejected_choc";
export const MOCK_EDIT_MESSAGE = "not available in mock mode";

export interface MockOptions {
  speed?: number;
  forcedFixture?: string | null;
  /** Appended to every build id this server sends, so two builds of one fixture stay apart (MockHub). */
  buildIdSuffix?: string;
}

/** What a FakeSocket talks to: one MockServer, or a MockHub of them. */
export interface MockEndpoint {
  attach(sock: FakeSocket): void;
  detach(sock: FakeSocket): void;
  receive(msg: ClientEnvelope): void;
}

export function normalizePrompt(p: string): string {
  return p.trim().toLowerCase().replace(/\s+/g, " ");
}

/** Pick the stream fixture for a prompt (SPEC 13). */
export function selectFixture(fx: FixtureSet, prompt: string, forced?: string | null): string {
  if (forced && fx.streams.has(forced)) return forced;
  const want = normalizePrompt(prompt);
  for (const f of fx.streams.values()) {
    if (f.match_prompts?.some((m) => normalizePrompt(m) === want)) return f.fixture;
  }
  return DEFAULT_FIXTURE;
}

/** Canonical JSON (sorted keys) for op-list comparison. */
function canon(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object") {
    const keys = Object.keys(v).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canon((v as Record<string, unknown>)[k])}`).join(",")}}`;
  }
  return JSON.stringify(v);
}

/** Choose the edit fixture whose edit.apply has the same op list (SPEC 13). */
export function selectEditFixture(fx: FixtureSet, ops: EditOp[]): string | null {
  const want = canon(ops);
  for (const f of fx.streams.values()) {
    const first = f.steps.find((s) => s.dir === "client");
    if (first?.msg.type !== "edit.apply") continue;
    if (canon((first.msg as ClientEnvelope<"edit.apply">).payload.ops) === want) return f.fixture;
  }
  return null;
}

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

interface Rewrite {
  seqOffset: number;
  revisionOffset: number;
  buildId: string | null;
  fromBuildId: string | null;
  editId: string | null;
  fromEditId: string | null;
  rejectMessage: string | null;
}

const NO_REWRITE: Rewrite = {
  seqOffset: 0,
  revisionOffset: 0,
  buildId: null,
  fromBuildId: null,
  editId: null,
  fromEditId: null,
  rejectMessage: null,
};

interface Replay {
  steps: FixtureStep[];
  /** Index of the first step of each fixture segment, with its rewrite. */
  segments: { start: number; rewrite: Rewrite }[];
  pos: number;
  timer: ReturnType<typeof setTimeout> | null;
  awaiting: string | null;
  buffered: ClientEnvelope[];
  /** True while the replay waits for the client to reconnect (a mid-chain hello). */
  awaitingReconnect: boolean;
  stage: string | null;
}

export class MockServer implements MockEndpoint {
  private readonly fx: FixtureSet;
  private readonly speed: number;
  private readonly forced: string | null;
  private readonly suffix: string | null;
  private socket: FakeSocket | null = null;
  private replay: Replay | null = null;
  private readonly idMap = new Map<string, string>();
  private readonly log = new Map<string, ServerEnvelope[]>();
  private lastSeq = 0;
  private revision = 0;
  private buildId: string | null = null;
  private terminal = false;
  private editCount = 0;

  constructor(fx: FixtureSet, opts: MockOptions = {}) {
    this.fx = fx;
    this.speed = opts.speed && opts.speed > 0 ? opts.speed : 1;
    this.forced = opts.forcedFixture ?? null;
    this.suffix = opts.buildIdSuffix ?? null;
  }

  /** Has this server been given a build.start yet. */
  get started(): boolean {
    return this.replay !== null || this.buildId !== null;
  }

  get awaitingReconnect(): boolean {
    return this.replay?.awaitingReconnect ?? false;
  }

  owns(buildId: string): boolean {
    return this.buildId === buildId || this.log.has(buildId);
  }

  /** `greet` false joins a socket another server already said hello on (MockHub). */
  attach(sock: FakeSocket, greet = true): void {
    this.socket = sock;
    if (this.replay?.awaitingReconnect) {
      const r = this.replay;
      r.awaitingReconnect = false;
      const step = r.steps[r.pos];
      r.pos += 1;
      this.later(step.dir === "server" ? (step.delay_ms ?? 0) : 0, () => {
        this.emit(step.msg as ServerEnvelope, NO_REWRITE);
        this.advance();
      });
      return;
    }
    if (!greet) return;
    const name = this.forced && this.fx.streams.has(this.forced) ? this.forced : DEFAULT_FIXTURE;
    const hello = this.firstHello(name);
    this.later(hello?.delay_ms ?? 20, () => {
      if (this.socket !== sock) return;
      this.emit(
        hello?.msg ?? {
          spec_version: SPEC_VERSION,
          type: "hello",
          seq: 0,
          build_id: null,
          ts: new Date().toISOString(),
          payload: { server_version: "mock", session_id: "s_mock", mock: true },
        },
        NO_REWRITE,
      );
    });
  }

  detach(sock: FakeSocket): void {
    if (this.socket === sock) this.socket = null;
  }

  private firstHello(name: string): { delay_ms?: number; msg: ServerEnvelope } | null {
    for (const f of this.chainOf(name)) {
      const s = f.steps[0];
      if (s?.dir === "server" && s.msg.type === "hello") return s;
    }
    return null;
  }

  private chainOf(name: string): StreamFixture[] {
    const f = this.fx.streams.get(name);
    if (!f) return [];
    return f.requires_fixture ? [...this.chainOf(f.requires_fixture), f] : [f];
  }

  private later(delayMs: number, fn: () => void): ReturnType<typeof setTimeout> {
    return setTimeout(fn, Math.max(0, delayMs * this.speed));
  }

  // ---- incoming ----

  receive(msg: ClientEnvelope): void {
    const r = this.replay;
    if (r && r.awaiting === msg.type) {
      this.consume(msg);
      return;
    }
    if (r && this.pendingLater(r, msg.type)) {
      r.buffered.push(msg);
      return;
    }
    switch (msg.type) {
      case "ping":
        this.reply("pong", { msg_id: msg.msg_id, server_time: new Date().toISOString() });
        break;
      case "build.start":
        this.startBuild(msg as ClientEnvelope<"build.start">);
        break;
      case "build.cancel":
        this.cancel(msg);
        break;
      case "edit.apply":
        this.startEdit(msg as ClientEnvelope<"edit.apply">);
        break;
      case "build.resume":
        this.resume(msg as ClientEnvelope<"build.resume">);
        break;
      default:
        this.ack(msg.msg_id, true);
        break;
    }
  }

  /** Is there a client step of this type later in the current fixture segment? */
  private pendingLater(r: Replay, type: string): boolean {
    const segEnd = r.segments.find((s) => s.start > r.pos)?.start ?? r.steps.length;
    for (let i = r.pos; i < segEnd; i++) {
      const s = r.steps[i];
      if (s.dir === "client" && s.msg.type === type) return true;
    }
    return false;
  }

  private consume(msg: ClientEnvelope): void {
    const r = this.replay;
    if (!r) return;
    const step = r.steps[r.pos];
    if (step.dir === "client") this.idMap.set(step.msg.msg_id, msg.msg_id);
    r.awaiting = null;
    r.pos += 1;
    this.advance();
  }

  private ack(msgId: string, accepted: boolean, error: Record<string, unknown> | null = null, editId: string | null = null): void {
    this.reply("ack", {
      msg_id: msgId,
      accepted,
      duplicate: false,
      build_id: this.buildId,
      edit_id: editId,
      error,
    });
  }

  private reply(type: string, payload: Record<string, unknown>, extra: Partial<ServerEnvelope> = {}): void {
    this.send({
      spec_version: SPEC_VERSION,
      type,
      seq: 0,
      build_id: type === "pong" ? null : this.buildId,
      ts: new Date().toISOString(),
      payload,
      ...extra,
    });
  }

  private startBuild(msg: ClientEnvelope<"build.start">): void {
    this.stopReplay();
    const name = selectFixture(this.fx, msg.payload.prompt, msg.payload.options?.mock_fixture ?? this.forced);
    const chain = this.chainOf(name);
    const steps: FixtureStep[] = [];
    const segments: Replay["segments"] = [];
    chain.forEach((f, idx) => {
      let fsteps = f.steps;
      if (idx === 0) {
        // The leading hello was sent on connect; the first build.start is this message.
        const startIdx = fsteps.findIndex((s) => s.dir === "client" && s.msg.type === "build.start");
        if (startIdx >= 0) {
          this.idMap.set((fsteps[startIdx].msg as ClientEnvelope).msg_id, msg.msg_id);
          fsteps = fsteps.slice(startIdx + 1);
        }
      }
      segments.push({ start: steps.length, rewrite: NO_REWRITE });
      steps.push(...fsteps);
    });
    this.lastSeq = 0;
    this.revision = 0;
    this.terminal = false;
    this.editCount = 0;
    this.buildId = null;
    this.replay = { steps, segments, pos: 0, timer: null, awaiting: null, buffered: [], awaitingReconnect: false, stage: null };
    this.advance();
  }

  private startEdit(msg: ClientEnvelope<"edit.apply">): void {
    if (this.replay || !this.buildId) {
      this.ack(msg.msg_id, false, {
        code: "E_BUILD_NOT_READY",
        message: "edit.apply sent before build.done.",
        retryable: true,
      });
      return;
    }
    const matched = selectEditFixture(this.fx, msg.payload.ops);
    const name = matched ?? MOCK_EDIT_FALLBACK;
    const f = this.fx.streams.get(name);
    if (!f) {
      this.ack(msg.msg_id, false, { code: "E_INVALID_EDIT", message: MOCK_EDIT_MESSAGE, retryable: false });
      return;
    }
    const firstClient = f.steps.findIndex((s) => s.dir === "client");
    const firstSeq = f.steps.find((s) => s.dir === "server" && s.msg.seq > 0)?.msg as ServerEnvelope | undefined;
    const fromBuildId = (firstSeq?.build_id ?? null) as string | null;
    const ackStep = f.steps.find((s) => s.dir === "server" && s.msg.type === "ack");
    const fromEditId = ((ackStep?.msg.payload as { edit_id?: string } | undefined)?.edit_id ?? null) as string | null;
    this.editCount += 1;
    this.idMap.set((f.steps[firstClient].msg as ClientEnvelope).msg_id, msg.msg_id);
    const rewrite: Rewrite = {
      seqOffset: this.lastSeq - ((firstSeq?.seq ?? 1) - 1),
      revisionOffset: this.revision - 1,
      buildId: this.buildId,
      fromBuildId,
      editId: `ed_${this.editCount}`,
      fromEditId,
      rejectMessage: matched ? null : MOCK_EDIT_MESSAGE,
    };
    this.replay = {
      steps: f.steps.slice(firstClient + 1),
      segments: [{ start: 0, rewrite }],
      pos: 0,
      timer: null,
      awaiting: null,
      buffered: [],
      awaitingReconnect: false,
      stage: null,
    };
    this.advance();
  }

  private cancel(msg: ClientEnvelope): void {
    const r = this.replay;
    this.ack(msg.msg_id, true);
    if (!r || this.terminal || !this.buildId) return;
    this.stopReplay();
    const base = { spec_version: SPEC_VERSION, build_id: this.buildId, ts: new Date().toISOString() };
    if (r.stage) {
      this.emit(
        {
          ...base,
          type: "stage.completed",
          seq: this.lastSeq + 1,
          stage: r.stage,
          payload: { stage: r.stage, status: "failed", duration_ms: 0, message: "Cancelled." },
        },
        NO_REWRITE,
      );
    }
    this.emit(
      {
        ...base,
        type: "build.failed",
        seq: this.lastSeq + 1,
        payload: {
          error: { code: "E_CANCELLED", message: "Build cancelled.", retryable: false },
          conflict: null,
          suggestions: [],
        },
      },
      NO_REWRITE,
    );
  }

  private resume(msg: ClientEnvelope<"build.resume">): void {
    this.reply("ack", {
      msg_id: msg.msg_id,
      accepted: true,
      duplicate: false,
      build_id: msg.payload.build_id,
      edit_id: null,
      error: null,
    });
    for (const env of this.log.get(msg.payload.build_id) ?? []) {
      if (env.seq > msg.payload.last_seq) this.send(env);
    }
  }

  private stopReplay(): void {
    if (this.replay?.timer) clearTimeout(this.replay.timer);
    this.replay = null;
  }

  private segmentOf(r: Replay): { start: number; rewrite: Rewrite } {
    let seg = r.segments[0];
    for (const s of r.segments) if (s.start <= r.pos) seg = s;
    return seg;
  }

  // ---- replay loop ----

  private advance(): void {
    const r = this.replay;
    if (!r || r.timer || r.awaiting || r.awaitingReconnect) return;
    if (r.pos >= r.steps.length) {
      this.replay = null;
      return;
    }
    const step = r.steps[r.pos];
    if (step.dir === "client") {
      r.awaiting = step.msg.type;
      const i = r.buffered.findIndex((m) => m.type === step.msg.type);
      if (i >= 0) {
        const [m] = r.buffered.splice(i, 1);
        this.consume(m);
      }
      return;
    }
    if (step.msg.type === "hello" && r.pos > 0) {
      // A hello mid-chain is a reconnect: drop the socket and wait for the client.
      r.awaitingReconnect = true;
      const sock = this.socket;
      this.socket = null;
      sock?.serverClose();
      return;
    }
    const rewrite = this.segmentOf(r).rewrite;
    r.timer = this.later(step.delay_ms ?? 0, () => {
      r.timer = null;
      if (this.replay !== r) return;
      r.pos += 1;
      this.emit(step.msg, rewrite);
      this.advance();
    });
  }

  /** Rewrite a fixture message for this session and send it. */
  private emit(src: ServerEnvelope, rw: Rewrite): void {
    const env = clone(src);
    const p = env.payload as Record<string, unknown>;
    const mapId = (id: unknown): unknown => (typeof id === "string" && this.idMap.has(id) ? this.idMap.get(id) : id);
    const mapEdit = (id: unknown): unknown => (rw.editId && id === rw.fromEditId ? rw.editId : id);
    if ("msg_id" in p) p.msg_id = mapId(p.msg_id);
    if ("edit_id" in p) p.edit_id = mapEdit(p.edit_id);
    if (env.cause) {
      if (env.cause.msg_id) env.cause.msg_id = mapId(env.cause.msg_id) as string;
      if (env.cause.edit_id) env.cause.edit_id = mapEdit(env.cause.edit_id) as string;
    }
    if (rw.buildId && env.build_id === rw.fromBuildId) env.build_id = rw.buildId;
    if ("build_id" in p && rw.buildId && p.build_id === rw.fromBuildId) p.build_id = rw.buildId;
    if (!CONNECTION_SCOPED.has(env.type) && env.seq > 0) env.seq += rw.seqOffset;
    if (typeof env.revision === "number") env.revision += rw.revisionOffset;
    if (env.type === "edit.applied" && typeof p.revision === "number") p.revision += rw.revisionOffset;
    if (env.type === "edit.rejected" && rw.rejectMessage) {
      const err = p.error as Record<string, unknown> | undefined;
      if (err) err.message = rw.rejectMessage;
    }
    if (this.suffix) {
      const sfx = this.suffix;
      const tag = (id: unknown): unknown => (typeof id === "string" && !id.endsWith(sfx) ? id + sfx : id);
      if (env.build_id) env.build_id = tag(env.build_id) as string;
      if ("build_id" in p) p.build_id = tag(p.build_id);
      const nested = p.build as { build_id?: unknown } | undefined;
      if (nested && typeof nested === "object" && "build_id" in nested) nested.build_id = tag(nested.build_id);
    }
    if (env.type === "ack" && typeof p.build_id === "string" && !this.buildId) this.buildId = p.build_id;
    if (!CONNECTION_SCOPED.has(env.type) && env.build_id) {
      this.buildId = env.build_id;
      if (env.type === "build.snapshot") {
        const b = (p.build as { revision?: number } | undefined) ?? {};
        if (typeof b.revision === "number") this.revision = b.revision;
      } else {
        const list = this.log.get(env.build_id) ?? [];
        // A fresh build of the same fixture restarts the log.
        const fresh = env.seq === 1 ? [] : list;
        fresh.push(env);
        this.log.set(env.build_id, fresh);
      }
      this.lastSeq = Math.max(env.type === "build.snapshot" ? env.seq : this.lastSeq, env.seq);
      if (typeof env.revision === "number") this.revision = Math.max(this.revision, env.revision);
      if (env.type === "stage.started") {
        if (this.replay) this.replay.stage = (p.stage as string) ?? null;
      }
      if (env.type === "stage.completed" && this.replay) this.replay.stage = null;
      if (env.type === "build.done" || env.type === "build.failed") this.terminal = true;
    }
    this.send(env);
  }

  private send(env: ServerEnvelope): void {
    this.socket?.deliver(JSON.stringify(env));
  }
}

/** Mock build ids carry `~tag` so they stay unique across canvases and reloads; REST stubs drop it. */
export function fixtureBuildPath(path: string): string {
  return path.replace(/~[a-z0-9]+/g, "");
}

/**
 * Several mock builds at once, one per canvas: each build.start after the first gets a MockServer
 * of its own, and later messages go to the server that owns their build_id. Every build id gets a
 * suffix unique to this page, so a canvas restored after a reload never shares an id with a new build.
 */
export class MockHub implements MockEndpoint {
  private readonly fx: FixtureSet;
  private readonly opts: MockOptions;
  private readonly lanes: MockServer[];
  private readonly tag = Date.now().toString(36);
  private socket: FakeSocket | null = null;

  constructor(fx: FixtureSet, opts: MockOptions = {}) {
    this.fx = fx;
    this.opts = opts;
    this.lanes = [this.lane(0)];
  }

  private lane(n: number): MockServer {
    return new MockServer(this.fx, { ...this.opts, buildIdSuffix: `~${this.tag}${n}` });
  }

  attach(sock: FakeSocket): void {
    this.socket = sock;
    // one hello per socket: from a lane picking up a mid-fixture reconnect, else from the first lane
    const resuming = this.lanes.some((l) => l.awaitingReconnect);
    this.lanes.forEach((l, i) => l.attach(sock, !resuming && i === 0));
  }

  detach(sock: FakeSocket): void {
    if (this.socket === sock) this.socket = null;
    for (const l of this.lanes) l.detach(sock);
  }

  receive(msg: ClientEnvelope): void {
    const last = this.lanes[this.lanes.length - 1];
    if (msg.type === "build.start") {
      let lane = last;
      if (lane.started) {
        lane = this.lane(this.lanes.length);
        this.lanes.push(lane);
        if (this.socket) lane.attach(this.socket, false);
      }
      lane.receive(msg);
      return;
    }
    const id = (msg.payload as { build_id?: unknown } | null)?.build_id;
    const owner = typeof id === "string" ? this.lanes.find((l) => l.owns(id)) : undefined;
    (owner ?? last).receive(msg);
  }
}

/** WebSocket stand-in that talks to a MockServer (or a MockHub). */
export class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private closed = false;
  private readonly server: MockEndpoint;

  constructor(server: MockEndpoint) {
    this.server = server;
    queueMicrotask(() => {
      if (this.closed) return;
      this.onopen?.();
      server.attach(this);
    });
  }

  send(data: string): void {
    if (this.closed) return;
    const msg = JSON.parse(data) as ClientEnvelope;
    queueMicrotask(() => this.server.receive(msg));
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.server.detach(this);
    queueMicrotask(() => this.onclose?.());
  }

  /** Server side drop. */
  serverClose(): void {
    this.close();
  }

  deliver(data: string): void {
    if (this.closed) return;
    this.onmessage?.({ data });
  }
}
