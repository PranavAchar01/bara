// Home (Figma: Landing C2, "the product, with Bara at work"). The first screen is one plate: a recording of a real
// build (scripts/record-demo.mjs) plays behind, and Bara's Build button sits in front; pressing it turns the
// page over to Bara, who asks what to make (HeroAgent). Then four stills show what Bara does on the canvas, then the user's own builds.
import { useEffect, useRef, useState } from "react";
import { AgentIntro, HeroCta, type IntroOpen } from "./HeroAgent";
import { BaraMark } from "./Handoff";
import { GalleryCard } from "./Library";
import { openBuildDialog } from "./BuildDialog";
import { loadGallery, useGallery } from "../library/gallery";
import { useApp } from "../state/store";

// Bump V when scripts/record-demo.mjs writes a new take, so no browser plays cached bytes of the old one.
const V = "4";
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

/** The first screen: one plate, the recording playing behind, and Bara's Build button in front. */
export function LandingHero() {
  const [intro, setIntro] = useState<IntroOpen | null>(null);
  return (
    <section className="ld-hero">
      <div className="ld-plate">
        <figure className="ld-bg" aria-label="A recording of Bara building a device, start to finish">
          <DemoVideo />
        </figure>
        <div className="ld-stage">
          <h1>Describe a device. Watch Bara build it from real parts.</h1>
          <HeroCta onOpen={setIntro} hidden={intro !== null} />
        </div>
      </div>
      {intro && <AgentIntro open={intro} onClose={() => setIntro(null)} />}
    </section>
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

/* ---- Below the hero: how it works, what you get, examples, FAQ, a closing call, the footer ---- */

/** Small drawings built in code, one per step. They use the page's own ink and paper. */
function StepArt(props: { kind: "describe" | "parts" | "board" | "case" }) {
  switch (props.kind) {
    case "describe":
      return (
        <div className="sa sa-describe">
          <BaraMark className="sa-bot" />
          <span className="sa-field mono">a macropad with one big knob</span>
        </div>
      );
    case "parts":
      return (
        <ul className="sa sa-parts mono">
          {["Rotary encoder", "Key switch ×9", "Small controller board"].map((p) => (
            <li key={p}>
              <i aria-hidden />
              {p}
            </li>
          ))}
        </ul>
      );
    case "board":
      return (
        <svg className="sa sa-board" viewBox="0 0 220 120" aria-hidden>
          <rect x="6" y="6" width="208" height="108" rx="10" />
          <path className="tr" d="M30 30 H90 V60 H150 M30 60 H60 V90 H190 M120 30 H190 V50" />
          <circle cx="30" cy="30" r="4" /><circle cx="150" cy="60" r="4" /><circle cx="30" cy="60" r="4" /><circle cx="190" cy="90" r="4" /><circle cx="120" cy="30" r="4" /><circle cx="190" cy="50" r="4" />
        </svg>
      );
    case "case":
      return (
        <svg className="sa sa-case" viewBox="0 0 220 120" aria-hidden>
          <path d="M20 44 L110 14 L200 44 L200 84 L110 108 L20 84 Z" />
          <path d="M20 44 L110 70 L200 44 M110 70 V108" />
          <circle cx="170" cy="30" r="12" className="play" />
          <path d="M166 24 L176 30 L166 36 Z" className="tri" />
        </svg>
      );
  }
}

const HOW: { kind: "describe" | "parts" | "board" | "case"; title: string; text: string }[] = [
  { kind: "describe", title: "Describe it", text: "Type or say what you want in one line. Bara asks one question only if it has to." },
  { kind: "parts", title: "Real parts", text: "Bara picks a real part for every line and keeps a shopping list as it goes." },
  { kind: "board", title: "Routes the board", text: "It lays out and routes a KiCad board around those parts, then runs the design checks." },
  { kind: "case", title: "Case and simulate", text: "A case closes around the board. Run the firmware in the simulator, then export the files." },
];

const GET: { title: string; text: string }[] = [
  { title: "Real parts", text: "Every part is a real one, with a shopping list you can buy from." },
  { title: "A KiCad board", text: "A routed board that has passed the design rule check." },
  { title: "A printable case", text: "STL, 3MF and STEP files that fit that board." },
  { title: "Firmware that runs", text: "Source for the pins Bara chose, which you can run in the simulator." },
];

const FAQ: { q: string; a: string }[] = [
  { q: "What does Bara make?", a: "Small electronics you can hold: keyboards, macropads, controllers and desk gadgets. Each one gets a board, a case and firmware." },
  { q: "Does Bara order the parts?", a: "No. It gives you a shopping list with the real part for each line, and you buy them yourself." },
  { q: "Can I change a build?", a: "Yes. Swap a part, move it, resize the case or ask Bara for a change. The checks run again after each edit." },
  { q: "What files do I get?", a: "The KiCad board files, the case as STL, 3MF and STEP, the firmware source and the shopping list." },
  { q: "What if my idea is too big?", a: "Bara is best with devices made of keys, knobs, displays and a small board. If a build fails, it tells you what stopped it." },
];

function Examples() {
  const items = useGallery((s) => s.items);
  const ready = useGallery((s) => s.ready);
  useEffect(() => void loadGallery(), []);
  if (ready && items.length === 0) return null;
  return (
    <section id="examples" className="ld-sec" aria-labelledby="ld-ex-h">
      <header className="ld-sh">
        <h2 id="ld-ex-h">Finished builds</h2>
        <span className="cap">Open one to look inside</span>
      </header>
      <ul className="gal-grid ld-ex">
        {ready ? items.slice(0, 6).map((it) => <GalleryCard key={it.build_id} item={it} />) : [0, 1, 2].map((i) => <li key={i} className="gal-card is-loading" aria-hidden />)}
      </ul>
    </section>
  );
}

/** Everything under the hero. The nav in the top bar scrolls to these ids. */
export function LandingSections() {
  return (
    <>
      <section id="how" className="ld-sec" aria-labelledby="ld-how-h">
        <header className="ld-sh">
          <h2 id="ld-how-h">How it works</h2>
          <span className="cap">From one line to files you can build from</span>
        </header>
        <ol className="ld-how">
          {HOW.map((h, i) => (
            <li key={h.title}>
              <div className="ld-art">
                <StepArt kind={h.kind} />
              </div>
              <div className="ld-st">
                <span className="ld-n">{i + 1}</span>
                <b>{h.title}</b>
              </div>
              <p>{h.text}</p>
            </li>
          ))}
        </ol>
      </section>
      <section className="ld-sec" aria-labelledby="ld-get-h">
        <header className="ld-sh">
          <h2 id="ld-get-h">What you get</h2>
          <span className="cap">Everything is in the download</span>
        </header>
        <ul className="ld-get">
          {GET.map((g) => (
            <li key={g.title}>
              <b>{g.title}</b>
              <p>{g.text}</p>
            </li>
          ))}
        </ul>
      </section>
      <Examples />
      <section id="faq" className="ld-sec" aria-labelledby="ld-faq-h">
        <header className="ld-sh">
          <h2 id="ld-faq-h">Questions</h2>
        </header>
        <div className="ld-faq">
          {FAQ.map((f) => (
            <details key={f.q}>
              <summary>{f.q}</summary>
              <p>{f.a}</p>
            </details>
          ))}
        </div>
      </section>
      <section className="ld-band" aria-labelledby="ld-band-h">
        <h2 id="ld-band-h">Describe a device. Get something you can build.</h2>
        <button type="button" className="btn primary ld-band-btn" onClick={() => openBuildDialog()} aria-haspopup="dialog">
          Start building
        </button>
      </section>
      <footer className="ld-foot">
        <span className="ld-foot-brand">
          <BaraMark className="brand-mark" />
          Bara
        </span>
        <button type="button" className="ld-foot-link" onClick={() => useApp.setState({ screen: "drafts" })}>
          Library
        </button>
        <span className="ld-foot-year">© {new Date().getFullYear()}</span>
      </footer>
    </>
  );
}
