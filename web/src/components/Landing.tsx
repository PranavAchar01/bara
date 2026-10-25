// Home (Figma: Landing C2, "the product, with Bara at work"). Bara itself roams the page (LandingAgent). Under the prompt a
// recording of a real build (scripts/record-demo.mjs) plays in a product window on a plate, all on the first screen,
// then four stills show what Bara does on the canvas, then the user's own builds.
import { useEffect, useRef, useState } from "react";
import { LandingAgent } from "./LandingAgent";
import { ExampleChips, PromptBar } from "./PromptBar";

// Bump V when scripts/record-demo.mjs writes a new take, so no browser plays cached bytes of the old one.
const V = "2";
const VIDEO = { mp4: `/landing/bara-demo.mp4?v=${V}`, webm: `/landing/bara-demo.webm?v=${V}`, poster: `/landing/bara-demo.jpg?v=${V}` };
const FALLBACK_POSTER = "/landing/hero-poster.jpg";

/** Muted, looping, never interactive. Plays only while on screen; a still under reduced motion. */
function DemoVideo() {
  const ref = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  useEffect(() => {
    const v = ref.current;
    if (!v || reduced) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) void v.play().catch(() => undefined);
        else v.pause();
      },
      { threshold: 0.2 },
    );
    io.observe(v);
    return () => io.disconnect();
  }, [reduced]);
  if (failed || reduced) return <img className="demo-media" src={failed ? FALLBACK_POSTER : VIDEO.poster} onError={(e) => ((e.currentTarget.src = FALLBACK_POSTER))} alt="" />;
  return (
    <video
      ref={ref}
      className="demo-media"
      poster={VIDEO.poster}
      muted
      loop
      playsInline
      autoPlay
      preload="metadata"
      disablePictureInPicture
      disableRemotePlayback
      tabIndex={-1}
      aria-hidden
      onError={() => setFailed(true)}
    >
      <source src={VIDEO.webm} type="video/webm" />
      {/* a source can report an error for an aborted load; fall back only when no source is left to play */}
      <source src={VIDEO.mp4} type="video/mp4" onError={() => ref.current?.networkState === HTMLMediaElement.NETWORK_NO_SOURCE && setFailed(true)} />
    </video>
  );
}

/** The first screen: a short head, then the recording on a plate that fills the rest of the viewport, so it plays without a scroll. */
export function LandingHero() {
  return (
    <div className="ld-hero">
      <LandingAgent />
      <section className="ld-head">
        <div className="ld-copy">
          <h1>Describe a device. Watch Bara build it from real parts.</h1>
          <p>Open parts, a routed board, a case and firmware, built where you can see it.</p>
          <div className="ld-home ld-home-narrow" aria-hidden />
        </div>
        <div className="ld-ask">
          <div className="ld-field">
            <PromptBar autoFocus />
            <div className="ld-foot">
              <span>Type it, or hold Space and say it</span>
              <span className="mono">then watch</span>
            </div>
            <ExampleChips />
          </div>
        </div>
      </section>
      <figure className="ld-plate" aria-label="A recording of Bara building a device, start to finish">
        {/* On a wide screen the bot rests in the plate's gutter, beside the recording */}
        <div className="ld-home ld-home-plate" aria-hidden />
        <div className="ld-frame">
          <DemoVideo />
        </div>
      </figure>
    </div>
  );
}

type Box = { x: number; y: number; w: number; h: number };
/** Boxes in the still's own pixels (700 × 460), turned into percentages so they scale with it. */
const pct = (b: Box) => ({ left: `${(b.x / 700) * 100}%`, top: `${(b.y / 460) * 100}%`, width: `${(b.w / 700) * 100}%`, height: `${(b.h / 460) * 100}%` });

function Selection(props: { box: Box; label: string; below?: boolean; children?: React.ReactNode }) {
  return (
    <span className="ld-sel" style={pct(props.box)}>
      <i className="h tl" />
      <i className="h tr" />
      <i className="h bl" />
      <i className="h br" />
      <span className={`ld-chip ${props.below ? "below" : ""}`}>{props.label}</span>
      {props.children}
    </span>
  );
}

const CURSOR = (
  <svg width="16" height="20" viewBox="0 0 16 20" aria-hidden>
    <path d="M1.5 1.5v15.2l4.1-3.9 2.7 6.1 2.6-1.1-2.7-6h5.7z" fill="#161616" stroke="#fff" strokeWidth="1.2" strokeLinejoin="round" />
  </svg>
);

const STEPS: { title: string; text: string; overlay: React.ReactNode }[] = [
  {
    title: "Reads what you want",
    text: "Turns one line into a spec, and asks one question if it has to.",
    overlay: (
      <Selection box={{ x: 70, y: 35, w: 590, h: 395 }} label="Reading “one big knob”" below>
        <i className="ld-scan" />
      </Selection>
    ),
  },
  {
    title: "Picks each part",
    text: "Flies to each part, picks it from tens of thousands of real ones and drops it in place.",
    overlay: (
      <>
        <Selection box={{ x: 105, y: 110, w: 345, h: 300 }} label="Picking Gateron Yellow ×9" />
        <span className="ld-cursor" style={{ left: `${(210 / 700) * 100}%`, top: `${(160 / 460) * 100}%` }}>
          {CURSOR}
        </span>
      </>
    ),
  },
  {
    title: "Routes the board",
    text: "Draws the traces across a real KiCad board, live.",
    overlay: (
      <Selection box={{ x: 200, y: 70, w: 230, h: 110 }} label="Routing PCB" below>
        <svg className="ld-trace" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          <path d="M5 70 H35 V25 H70 V60 H95" />
        </svg>
      </Selection>
    ),
  },
  {
    title: "Writes the firmware",
    text: "Types the firmware for the exact pins it chose, then runs the checks.",
    overlay: (
      <Selection box={{ x: 260, y: 75, w: 100, h: 70 }} label="Writing firmware" below>
        <span className="ld-code mono">
          Wire.begin(6, 7);<i />
        </span>
      </Selection>
    ),
  },
];

export function AgentSteps() {
  return (
    <section className="ld-steps" aria-labelledby="ld-steps-h">
      <header className="ld-sh">
        <h2 id="ld-steps-h">Bara works where you can see it</h2>
        <span className="cap">Every step is an action on the canvas</span>
      </header>
      <ol>
        {STEPS.map((s, i) => (
          <li key={s.title}>
            <div className="ld-still">
              <img src="/landing/agent-steps.jpg" alt="" loading="lazy" />
              <span aria-hidden>{s.overlay}</span>
            </div>
            <div className="ld-st">
              <span className="ld-n">{i + 1}</span>
              <b>{s.title}</b>
            </div>
            <p>{s.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
