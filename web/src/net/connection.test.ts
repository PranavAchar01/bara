import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BACKOFF_MS, Connection, backoffDelay, type SocketLike } from "./connection";
import type { ClientEnvelope, ServerEnvelope } from "../spec/types";

class TestSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: ClientEnvelope[] = [];
  closed = false;
  send(data: string): void {
    this.sent.push(JSON.parse(data) as ClientEnvelope);
  }
  close(): void {
    this.closed = true;
  }
  serverMsg(env: Partial<ServerEnvelope> & { type: string }): void {
    this.onmessage?.({
      data: JSON.stringify({ spec_version: "1.1.0", seq: 0, build_id: null, ts: "t", payload: {}, ...env }),
    });
  }
  hello(): void {
    this.serverMsg({ type: "hello", payload: { server_version: "x", session_id: "s" } });
  }
  drop(): void {
    this.onclose?.();
  }
}

function setup(resume: { build_id: string; last_seq: number } | null = null) {
  const sockets: TestSocket[] = [];
  const seen: ServerEnvelope[] = [];
  const drops: string[] = [];
  const statuses: string[] = [];
  let n = 0;
  const target = { value: resume };
  const conn = new Connection({
    url: "ws://test/v1/ws",
    socketFactory: () => {
      const s = new TestSocket();
      sockets.push(s);
      return s;
    },
    resumeTarget: () => target.value,
    onEnvelope: (e) => seen.push(e),
    onDrop: (e, r) => drops.push(`${r}:${e.seq}`),
    onStatus: (s) => statuses.push(s),
    random: () => 0.5,
    idFactory: () => `m_test_${String(++n).padStart(4, "0")}`,
  });
  conn.connect();
  return { conn, sockets, seen, drops, statuses, target, last: () => sockets[sockets.length - 1] };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("C26 connection", () => {
  it("waits for hello before sending", () => {
    const t = setup();
    t.conn.send("build.start", { prompt: "a keyboard" });
    expect(t.last().sent).toHaveLength(0);
    t.last().hello();
    expect(t.last().sent.map((m) => m.type)).toEqual(["build.start"]);
    expect(t.conn.state).toBe("open");
  });

  it("uses UUID-style msg ids by default", async () => {
    const { newMsgId } = await import("./ids");
    const id = newMsgId();
    expect(id).toMatch(/^m_[0-9a-f]{32}$/);
    expect(newMsgId()).not.toBe(id);
  });

  it("pings every 15 s and reconnects when no pong arrives within 10 s", () => {
    const t = setup();
    t.last().hello();
    vi.advanceTimersByTime(14_999);
    expect(t.last().sent).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(t.last().sent.map((m) => m.type)).toEqual(["ping"]);
    // pong arrives: no reconnect
    t.last().serverMsg({ type: "pong", payload: { msg_id: t.last().sent[0].msg_id } });
    vi.advanceTimersByTime(15_000);
    expect(t.sockets).toHaveLength(1);
    // second ping unanswered: dead after 10 s
    vi.advanceTimersByTime(9_999);
    expect(t.sockets[0].closed).toBe(false);
    vi.advanceTimersByTime(1);
    expect(t.sockets[0].closed).toBe(true);
    expect(t.conn.state).toBe("reconnecting");
    vi.advanceTimersByTime(BACKOFF_MS[0]);
    expect(t.sockets).toHaveLength(2);
  });

  it("backs off 0.5, 1, 2, 4, 8, then 8 s, and resets after hello", () => {
    const t = setup();
    t.last().hello();
    const waits: number[] = [];
    for (let i = 0; i < 7; i++) {
      const before = t.sockets.length;
      t.last().drop();
      let waited = 0;
      while (t.sockets.length === before) {
        vi.advanceTimersByTime(50);
        waited += 50;
      }
      waits.push(waited);
    }
    expect(waits).toEqual([500, 1000, 2000, 4000, 8000, 8000, 8000]);
    expect(t.statuses).toContain("offline");
    t.last().hello();
    t.last().drop();
    vi.advanceTimersByTime(499);
    const n = t.sockets.length;
    vi.advanceTimersByTime(1);
    expect(t.sockets.length).toBe(n + 1);
  });

  it("applies at most 20 percent jitter", () => {
    expect(backoffDelay(0, () => 0)).toBe(400);
    expect(backoffDelay(0, () => 1)).toBe(600);
    expect(backoffDelay(9, () => 0)).toBe(6400);
    expect(backoffDelay(9, () => 1)).toBe(9600);
  });

  it("resumes with last_seq and resends unacked messages with the same msg_id", () => {
    const t = setup();
    t.last().hello();
    t.conn.setCursor("b_test0001", 0);
    for (let seq = 1; seq <= 3; seq++) t.last().serverMsg({ type: "stage.progress", seq, build_id: "b_test0001" });
    const editId = t.conn.send("edit.apply", { build_id: "b_test0001", ops: [] });
    const acked = t.conn.send("build.cancel", { build_id: "b_test0001" });
    t.last().serverMsg({ type: "ack", payload: { msg_id: acked, accepted: true, duplicate: false } });
    t.target.value = { build_id: "b_test0001", last_seq: 3 };
    t.last().drop();
    vi.advanceTimersByTime(600);
    t.last().hello();
    const sent = t.last().sent;
    expect(sent[0].type).toBe("build.resume");
    expect(sent[0].payload).toEqual({ build_id: "b_test0001", last_seq: 3 });
    expect(sent.slice(1).map((m) => m.msg_id)).toEqual([editId]);
    expect(t.conn.state).toBe("resyncing");
    t.last().serverMsg({ type: "ack", payload: { msg_id: sent[0].msg_id, accepted: true, duplicate: false } });
    expect(t.conn.state).toBe("open");
  });

  it("drops duplicates and resumes on a gap", () => {
    const t = setup();
    t.last().hello();
    t.conn.setCursor("b_test0001", 0);
    t.last().serverMsg({ type: "stage.progress", seq: 1, build_id: "b_test0001" });
    t.last().serverMsg({ type: "stage.progress", seq: 1, build_id: "b_test0001" });
    t.last().serverMsg({ type: "stage.progress", seq: 3, build_id: "b_test0001" });
    t.last().serverMsg({ type: "stage.progress", seq: 4, build_id: "b_test0001" });
    expect(t.drops).toEqual(["duplicate:1", "gap:3", "gap:4"]);
    const resumes = t.last().sent.filter((m) => m.type === "build.resume");
    expect(resumes).toHaveLength(1);
    expect(resumes[0].payload).toEqual({ build_id: "b_test0001", last_seq: 1 });
    // replay fills the gap
    for (const seq of [2, 3, 4]) t.last().serverMsg({ type: "stage.progress", seq, build_id: "b_test0001" });
    expect(t.seen.filter((e) => e.type === "stage.progress").map((e) => e.seq)).toEqual([1, 2, 3, 4]);
  });

  it("waits for build.snapshot after E_RESUME_GAP and replaces state from it", () => {
    const t = setup();
    t.last().hello();
    t.target.value = { build_id: "b_test0001", last_seq: 3 };
    t.last().drop();
    vi.advanceTimersByTime(600);
    t.last().hello();
    const resume = t.last().sent[0];
    t.last().serverMsg({ type: "ack", payload: { msg_id: resume.msg_id, accepted: true, duplicate: false } });
    t.last().serverMsg({ type: "error", payload: { error: { code: "E_RESUME_GAP" }, msg_id: resume.msg_id } });
    expect(t.conn.state).not.toBe("open");
    t.last().serverMsg({ type: "build.snapshot", seq: 62, build_id: "b_test0001", payload: { build: {} } });
    expect(t.conn.state).toBe("open");
    expect(t.conn.lastSeq("b_test0001")).toBe(62);
    t.last().serverMsg({ type: "stage.progress", seq: 62, build_id: "b_test0001" });
    expect(t.drops).toEqual(["duplicate:62"]);
  });

  it("advances past unknown event types so they do not look like gaps", () => {
    const t = setup();
    t.last().hello();
    t.last().serverMsg({ type: "future.thing", seq: 1, build_id: "b_test0001" });
    t.last().serverMsg({ type: "stage.progress", seq: 2, build_id: "b_test0001" });
    expect(t.drops).toEqual([]);
    expect(t.seen.map((e) => e.type)).toEqual(["hello", "future.thing", "stage.progress"]);
  });

  it("drops the socket at once when the browser goes offline, and resumes from the last event", () => {
    const t = setup({ build_id: "b_test0001", last_seq: 0 });
    t.last().hello();
    t.last().serverMsg({ type: "stage.progress", seq: 1, build_id: "b_test0001" });
    t.last().serverMsg({ type: "stage.progress", seq: 2, build_id: "b_test0001" });
    const first = t.last();
    t.conn.drop();
    expect(first.closed).toBe(true);
    expect(t.conn.state).toBe("reconnecting");
    // the late close event of the old socket changes nothing
    first.drop();
    expect(t.sockets).toHaveLength(1);
    vi.advanceTimersByTime(BACKOFF_MS[0]);
    expect(t.sockets).toHaveLength(2);
    t.last().hello();
    const resume = t.last().sent.find((m) => m.type === "build.resume");
    expect(resume?.payload).toEqual({ build_id: "b_test0001", last_seq: 2 });
  });

  it("reconnects at once when nudged instead of waiting out the backoff", () => {
    const t = setup();
    t.last().hello();
    for (let i = 0; i < 4; i++) {
      t.last().drop();
      vi.advanceTimersByTime(BACKOFF_MS[Math.min(i, BACKOFF_MS.length - 1)] * 1.3);
    }
    t.last().drop();
    const before = t.sockets.length;
    t.conn.nudge();
    expect(t.sockets).toHaveLength(before + 1);
    // a socket is already opening: a second nudge does not open another
    t.conn.nudge();
    expect(t.sockets).toHaveLength(before + 1);
    t.last().hello();
    expect(t.conn.state).toBe("open");
    // the backoff starts over after a nudge
    t.last().drop();
    vi.advanceTimersByTime(BACKOFF_MS[0] * 1.3);
    expect(t.sockets).toHaveLength(before + 2);
  });
});
