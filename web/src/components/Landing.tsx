// Home (Figma: Landing C2, "the product, with Bara at work"). Bara itself roams the page (LandingAgent). One view: the
// prompt beside a recording of a real build in a product window, and the four steps Bara takes
// under both. The user's own builds live on the Drafts page.
import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { LandingAgent } from "./LandingAgent";
import { ExampleChips, PromptBar } from "./PromptBar";

const VIDEO = { mp4: "/landing/bara-demo.mp4", webm: "/landing/bara-demo.webm", poster: "/landing/bara-demo.jpg" };
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
  // the video's own poster frame first; the older still if that is missing too
  if (failed || reduced)
    return <img className="demo-media" src={VIDEO.poster} onError={(e) => e.currentTarget.src.endsWith(FALLBACK_POSTER) || (e.currentTarget.src = FALLBACK_POSTER)} alt="" />;
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
      <source src={VIDEO.webm} type="video/webm" onError={() => undefined} />
      <source src={VIDEO.mp4} type="video/mp4" onError={() => setFailed(true)} />
    </video>
  );
}

/** What Bara does, in order: each step is labelled the way the agent labels its work on the canvas. */
const STEPS: { title: string; text: string; chip: string }[] = [
  { title: "Reads what you want", text: "Turns one line into a spec, and asks one question if it has to.", chip: "Understanding the request" },
  { title: "Picks each part", text: "Picks every part from tens of thousands of real ones and drops it in place.", chip: "Picking nice!nano v2" },
  { title: "Routes the board", text: "Draws the traces across a real KiCad board, live.", chip: "Routing PCB" },
  { title: "Writes the firmware", text: "Types the firmware for the exact pins it chose, then runs the checks.", chip: "Writing firmware" },
];

function AgentSteps() {
  return (
    <ol className="ld-steps" aria-label="What Bara does">
      {STEPS.map((s, i) => (
        <li key={s.title}>
          <div className="ld-st">
            <span className="ld-n">{i + 1}</span>
            <b>{s.title}</b>
          </div>
          <p>{s.text}</p>
          <span className="ld-chip" aria-hidden>
            {s.chip}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function LandingHero() {
  const health = useApp((s) => s.health);
  return (
    <>
      <LandingAgent />
      <section className="ld-hero">
        <div className="ld-head">
          <div className="ld-copy">
            <h1>Describe a device. Watch Bara build it from real parts.</h1>
            <p>It picks open parts, routes the board, shapes the case and writes the firmware, out on the canvas where you can see every move.</p>
          </div>
          <div className="ld-home" aria-hidden />
          <div className="ld-field">
            <PromptBar autoFocus />
            <div className="ld-foot">
              <span>Type it, or hold Space and say it</span>
              <span className="mono">then watch</span>
            </div>
            <ExampleChips />
          </div>
        </div>
        <figure className="ld-window" aria-label="A recording of Bara building a device">
          <div className="ld-frame">
            <DemoVideo />
          </div>
          <figcaption>
            <span>A real build, start to finish, played back.</span>
            {health && <span className="mono">{(health.part_count ?? 0).toLocaleString()} parts in the catalog</span>}
          </figcaption>
        </figure>
        <AgentSteps />
      </section>
    </>
  );
}
