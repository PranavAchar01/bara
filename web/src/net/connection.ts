// C26 socket owner (SPEC 8.8): wait for hello, keepalive, backoff with jitter,
// resume with last_seq, gap and duplicate detection, resend of unacked messages.
import type { ClientEnvelope, ClientPayloads, ClientType, ServerEnvelope } from "../spec/types";
import { CONNECTION_SCOPED, SPEC_VERSION } from "../spec/types";
import { newMsgId } from "./ids";

export type ConnStatus = "connecting" | "open" | "reconnecting" | "resyncing" | "offline";

/** The subset of WebSocket the connection uses; FakeSocket implements the same. */
export interface SocketLike {
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: (() => void) | null;
}

export interface Timers {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
  setInterval(fn: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
}

const realTimers: Timers = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (h) => globalThis.clearTimeout(h as ReturnType<typeof setTimeout>),
  setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
  clearInterval: (h) => globalThis.clearInterval(h as ReturnType<typeof setInterval>),
};

export const PING_INTERVAL_MS = 15_000;
export const PONG_TIMEOUT_MS = 10_000;
export const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];
export const JITTER = 0.2;
const OFFLINE_AFTER = 5;

export type DropReason = "duplicate" | "gap";

export interface ConnectionOptions {
  url: string;
  socketFactory: (url: string) => SocketLike;
  /** The open build to resume after a reconnect, if any. */
  resumeTarget: () => { build_id: string; last_seq: number } | null;
  onEnvelope: (env: ServerEnvelope) => void;
  onStatus?: (status: ConnStatus) => void;
  onSent?: (env: ClientEnvelope, resend: boolean) => void;
  onDrop?: (env: ServerEnvelope, reason: DropReason) => void;
  timers?: Timers;
  random?: () => number;
  idFactory?: () => string;
}

export function backoffDelay(attempt: number, random: () => number): number {
  const base = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
  return Math.round(base * (1 + (random() * 2 - 1) * JITTER));
}

export class Connection {
  private readonly opts: ConnectionOptions;
  private readonly timers: Timers;
  private readonly random: () => number;
  private readonly newId: () => string;
  private socket: SocketLike | null = null;
  private helloSeen = false;
  private everOpened = false;
  private disposed = false;
  private attempts = 0;
  private status: ConnStatus = "connecting";
  private pingTimer: unknown = null;
  private pongTimer: unknown = null;
  private reconnectTimer: unknown = null;
  /** Messages sent (or queued) with no ack yet, in send order. Pings are not tracked. */
  private readonly unacked = new Map<string, ClientEnvelope>();
  /** Highest seq applied per build. */
  private readonly cursor = new Map<string, number>();
  /** Builds with a resume in flight, so a burst of gapped events sends one resume. */
  private readonly resuming = new Set<string>();
  private resumeMsgId: string | null = null;
  private awaitingSnapshot = false;

  constructor(opts: ConnectionOptions) {
    this.opts = opts;
    this.timers = opts.timers ?? realTimers;
    this.random = opts.random ?? Math.random;
    this.newId = opts.idFactory ?? newMsgId;
  }

  get state(): ConnStatus {
    return this.status;
  }

  get ready(): boolean {
    return this.helloSeen;
  }

  /** Highest applied seq for a build (0 when none). */
  lastSeq(buildId: string): number {
    return this.cursor.get(buildId) ?? 0;
  }

  /** Called by the store when it creates or replaces a build. */
  setCursor(buildId: string, seq: number): void {
    this.cursor.set(buildId, seq);
  }

  connect(): void {
    if (this.disposed) return;
    const ws = this.opts.socketFactory(this.opts.url);
    this.socket = ws;
    ws.onmessage = (ev) => {
      if (this.socket === ws) this.handleText(ev.data);
    };
    ws.onclose = () => this.handleClose(ws);
    ws.onerror = () => {
      // A close event always follows an error; reconnect is handled there.
    };
  }

  dispose(): void {
    this.disposed = true;
    this.stopKeepalive();
    if (this.reconnectTimer !== null) this.timers.clearTimeout(this.reconnectTimer);
    const ws = this.socket;
    this.socket = null;
    ws?.close();
  }

  /** Send a client message. Queued until hello; resent after a reconnect until acked. */
  send<T extends ClientType>(type: T, payload: ClientPayloads[T], msgId?: string): string {
    const env: ClientEnvelope<T> = {
      spec_version: SPEC_VERSION,
      type,
      msg_id: msgId ?? this.newId(),
      ts: new Date().toISOString(),
      payload,
    };
    if (type !== "ping") this.unacked.set(env.msg_id, env as ClientEnvelope);
    if (this.helloSeen) this.transmit(env as ClientEnvelope, false);
    return env.msg_id;
  }

  private transmit(env: ClientEnvelope, resend: boolean): void {
    if (!this.socket) return;
    this.socket.send(JSON.stringify(env));
    this.opts.onSent?.(env, resend);
  }

  private setStatus(s: ConnStatus): void {
    if (s === this.status) return;
    this.status = s;
    this.opts.onStatus?.(s);
  }

  private handleText(text: string): void {
    let env: ServerEnvelope;
    try {
      env = JSON.parse(text) as ServerEnvelope;
    } catch {
      return;
    }
    if (!env || typeof env.type !== "string") return;
    if (CONNECTION_SCOPED.has(env.type)) {
      this.handleConnectionEvent(env);
      this.opts.onEnvelope(env);
      return;
    }
    const buildId = env.build_id;
    if (!buildId || typeof env.seq !== "number") {
      this.opts.onEnvelope(env);
      return;
    }
    if (env.type === "build.snapshot") {
      this.cursor.set(buildId, env.seq);
      this.resuming.delete(buildId);
      if (this.awaitingSnapshot) {
        this.awaitingSnapshot = false;
        this.setStatus("open");
      }
      this.opts.onEnvelope(env);
      return;
    }
    const last = this.cursor.get(buildId) ?? 0;
    if (env.seq <= last) {
      this.opts.onDrop?.(env, "duplicate");
      return;
    }
    if (env.seq > last + 1) {
      this.opts.onDrop?.(env, "gap");
      if (!this.resuming.has(buildId)) {
        this.resuming.add(buildId);
        this.resumeMsgId = this.send("build.resume", { build_id: buildId, last_seq: last });
      }
      return;
    }
    this.cursor.set(buildId, env.seq);
    this.resuming.delete(buildId);
    this.opts.onEnvelope(env);
  }

  private handleConnectionEvent(env: ServerEnvelope): void {
    const p = env.payload as Record<string, unknown>;
    switch (env.type) {
      case "hello":
        this.onHello();
        break;
      case "ack": {
        const id = typeof p.msg_id === "string" ? p.msg_id : "";
        this.unacked.delete(id);
        if (id && id === this.resumeMsgId) {
          this.resumeMsgId = null;
          if (!this.awaitingSnapshot) this.setStatus("open");
        }
        break;
      }
      case "pong":
        if (this.pongTimer !== null) {
          this.timers.clearTimeout(this.pongTimer);
          this.pongTimer = null;
        }
        break;
      case "error": {
        const err = p.error as { code?: string } | undefined;
        if (err?.code === "E_RESUME_GAP") {
          this.awaitingSnapshot = true;
          this.setStatus("resyncing");
        }
        // The failing message will not be acked; stop resending it.
        if (typeof p.msg_id === "string") this.unacked.delete(p.msg_id);
        break;
      }
    }
  }

  private onHello(): void {
    this.helloSeen = true;
    this.attempts = 0;
    const reconnect = this.everOpened;
    this.everOpened = true;
    this.startKeepalive();
    const target = reconnect ? this.opts.resumeTarget() : null;
    if (target) {
      this.setStatus("resyncing");
      this.cursor.set(target.build_id, Math.max(this.cursor.get(target.build_id) ?? 0, target.last_seq));
      // Drop any stale resume from the old socket; a fresh one goes first.
      for (const [id, m] of this.unacked) if (m.type === "build.resume") this.unacked.delete(id);
      this.resuming.add(target.build_id);
      this.resumeMsgId = this.send("build.resume", {
        build_id: target.build_id,
        last_seq: this.cursor.get(target.build_id) ?? 0,
      });
    } else {
      this.setStatus("open");
    }
    for (const env of [...this.unacked.values()]) {
      if (env.msg_id === this.resumeMsgId) continue;
      this.transmit(env, reconnect);
    }
  }

  private startKeepalive(): void {
    this.stopKeepalive();
    this.pingTimer = this.timers.setInterval(() => {
      if (!this.helloSeen) return;
      this.send("ping", {});
      if (this.pongTimer === null) {
        this.pongTimer = this.timers.setTimeout(() => {
          this.pongTimer = null;
          const ws = this.socket;
          if (ws) {
            ws.close();
            this.handleClose(ws);
          }
        }, PONG_TIMEOUT_MS);
      }
    }, PING_INTERVAL_MS);
  }

  private stopKeepalive(): void {
    if (this.pingTimer !== null) this.timers.clearInterval(this.pingTimer);
    if (this.pongTimer !== null) this.timers.clearTimeout(this.pongTimer);
    this.pingTimer = null;
    this.pongTimer = null;
  }

  private handleClose(ws: SocketLike): void {
    if (this.socket !== ws) return;
    this.socket = null;
    this.helloSeen = false;
    this.resumeMsgId = null;
    this.resuming.clear();
    this.awaitingSnapshot = false;
    this.stopKeepalive();
    if (this.disposed) return;
    const delay = backoffDelay(this.attempts, this.random);
    this.attempts += 1;
    this.setStatus(this.attempts >= OFFLINE_AFTER ? "offline" : this.everOpened ? "reconnecting" : "connecting");
    this.reconnectTimer = this.timers.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
}
