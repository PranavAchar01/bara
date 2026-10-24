// BotLab (?botlab=1): the bot on its own, to judge how it moves. Every mood,
// activity and emote on a button, a line to say, the bubbles on or off, a
// scripted build that walks the eight stages, and a grid of every mood at once.
import { useEffect, useRef, useState } from "react";
import { BaraBot } from "./BaraBot";
import { STAGE_ACTIVITY, type Activity, type Emote, type Mood } from "./mood";

const MOODS: Mood[] = ["idle", "listening", "thinking", "working", "asking", "happy", "worried", "sad", "sleepy", "offline", "connecting"];
const ACTIVITIES: Activity[] = ["read", "search", "pick", "arrange", "sculpt", "route", "type", "admire"];
const EMOTES: Emote[] = ["nod", "pop", "hop", "wince", "surprise", "delight", "shake", "yawn"];

/** A build, scripted: each stage's activity, what it says, and the emotes along the way. */
const SCRIPT: { stage: string; say: string; ms: number; emotes?: Emote[] }[] = [
  { stage: "classify", say: "A wireless split keyboard, got it", ms: 3800 },
  { stage: "reuse", say: "Found the Corne, starting from that", ms: 3800, emotes: ["surprise"] },
  { stage: "compose", say: "Got Cherry MX2A Brown switches", ms: 4200, emotes: ["pop", "pop", "pop"] },
  { stage: "place", say: "Laying out 42 keys", ms: 3800, emotes: ["nod"] },
  { stage: "enclose", say: "Shaping the case around the board", ms: 3800 },
  { stage: "board", say: "Routing the left half on KiCad", ms: 4400, emotes: ["nod"] },
  { stage: "firmware", say: "Writing the ZMK keymap", ms: 3600 },
  { stage: "render", say: "Done! 76 parts, all placed", ms: 4200, emotes: ["delight"] },
];

export function BotLab() {
  const [mood, setMood] = useState<Mood>("idle");
  const [activity, setActivity] = useState<Activity | null>(null);
  const [emote, setEmote] = useState<{ kind: Emote; n: number } | null>(null);
  const [say, setSay] = useState<{ text: string; n: number } | null>(null);
  const [line, setLine] = useState("Routing the left half on KiCad");
  const [bubbles, setBubbles] = useState(true);
  const [playing, setPlaying] = useState(false);
  const n = useRef(0);
  const timers = useRef<number[]>([]);

  const fire = (kind: Emote) => setEmote({ kind, n: ++n.current });
  const speak = (text: string) => setSay({ text, n: ++n.current });
  const stop = () => {
    for (const t of timers.current) window.clearTimeout(t);
    timers.current = [];
    setPlaying(false);
  };
  useEffect(() => stop, []);

  const play = () => {
    stop();
    setPlaying(true);
    let at = 0;
    for (const step of SCRIPT) {
      const act = STAGE_ACTIVITY[step.stage];
      timers.current.push(
        window.setTimeout(() => {
          setMood(step.stage === "render" ? "happy" : act === "read" || act === "search" ? "thinking" : "working");
          setActivity(act);
          speak(step.say);
          (step.emotes ?? []).forEach((e, i) => timers.current.push(window.setTimeout(() => fire(e), 500 + i * 450)));
        }, at),
      );
      at += step.ms;
    }
    timers.current.push(
      window.setTimeout(() => {
        setMood("idle");
        setActivity(null);
        setPlaying(false);
      }, at + 1200),
    );
  };

  return (
    <div className="botlab">
      <header className="botlab-head">
        <h1>Bot</h1>
        <label className="botlab-toggle">
          <input type="checkbox" checked={bubbles} onChange={(e) => setBubbles(e.target.checked)} /> Thought and speech bubbles
        </label>
        <a href="/" className="btn ghost sm">
          Back to the app
        </a>
      </header>
      <section className="botlab-stage">
        <BaraBot size={190} mood={mood} activity={activity} emote={emote} say={say} bubbles={bubbles} />
        <p className="botlab-caption">
          {mood}
          {activity ? ` · ${activity}` : ""}
        </p>
      </section>
      <section className="botlab-controls">
        <div className="botlab-row">
          <span className="botlab-label">Build</span>
          <button type="button" className="btn primary sm" onClick={playing ? stop : play}>
            {playing ? "Stop" : "Play a build"}
          </button>
        </div>
        <div className="botlab-row">
          <span className="botlab-label">Mood</span>
          {MOODS.map((m) => (
            <button key={m} type="button" className={`seg-btn ${mood === m ? "active" : ""}`} onClick={() => setMood(m)}>
              {m}
            </button>
          ))}
        </div>
        <div className="botlab-row">
          <span className="botlab-label">Doing</span>
          <button type="button" className={`seg-btn ${activity === null ? "active" : ""}`} onClick={() => setActivity(null)}>
            nothing
          </button>
          {ACTIVITIES.map((a) => (
            <button
              key={a}
              type="button"
              className={`seg-btn ${activity === a ? "active" : ""}`}
              onClick={() => {
                setActivity(a);
                if (mood !== "working" && mood !== "thinking" && mood !== "happy") setMood(a === "read" || a === "search" ? "thinking" : "working");
              }}
            >
              {a}
            </button>
          ))}
        </div>
        <div className="botlab-row">
          <span className="botlab-label">React</span>
          {EMOTES.map((e) => (
            <button key={e} type="button" className="seg-btn" onClick={() => fire(e)}>
              {e}
            </button>
          ))}
        </div>
        <form
          className="botlab-row"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (line.trim()) speak(line.trim().slice(0, 60));
          }}
        >
          <span className="botlab-label">Say</span>
          <input className="botlab-input" value={line} maxLength={60} onChange={(e) => setLine(e.target.value)} />
          <button type="submit" className="btn sm">
            Say it
          </button>
        </form>
      </section>
      <section className="botlab-grid">
        {MOODS.map((m) => (
          <figure key={m}>
            <BaraBot size={72} mood={m} activity={m === "working" ? "route" : m === "thinking" ? "read" : m === "happy" ? "admire" : null} bubbles={false} />
            <figcaption>{m}</figcaption>
          </figure>
        ))}
      </section>
    </div>
  );
}
