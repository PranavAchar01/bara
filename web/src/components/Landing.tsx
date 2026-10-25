// Home (Figma: Landing C2, "the product, with Bara at work"). One short story, with Bara showing the way:
// the first screen is one plate, a recording of a real build (scripts/record-hero.mjs) behind and Bara's
// Build button in front; pressing it turns the page over to Bara, who asks what to make (HeroAgent). Then
// what a build gives you, the library as it stands, and a call to try it. Bara itself (LandingGuide) is out
// on the page the whole way down, pointing at each part and saying what it is; click it to talk.
import { useEffect, useRef, useState } from "react";
import { AgentIntro, HeroCta, type IntroOpen } from "./HeroAgent";
import { LandingGuide, type GuideHandle } from "./LandingGuide";
import { BaraMark } from "./Handoff";
import { openBuildDialog } from "./buildDialogStore";
import { GalleryCard } from "./Library";
import { loadGallery, useGallery } from "../library/gallery";
import { loadOpenSource, scrubMakers, thumbUrl, useOpenSource } from "../library/openSource";
import { useApp } from "../state/store";
import "../styles/landing.css";

// Bump V when scripts/record-hero.mjs writes a new take, so no browser plays cached bytes of the old one.
const V = "6";
// AV1 at 2560 wide for the 2x screens that can play it, H.264 High at 1920 for the rest; both 60 fps.
const VIDEO = { av1: `/landing/bara-demo.av1.mp4?v=${V}`, mp4: `/landing/bara-demo.mp4?v=${V}`, poster: `/landing/bara-demo.jpg?v=${V}` };
const FALLBACK_POSTER = "/landing/hero-poster.jpg";

/** Muted, never interactive. Plays the build once and rests on the finished device. It starts loading only
 *  after the page has painted and gone idle, and plays only while on screen; a still under reduced motion. */
function DemoVideo() {
  const ref = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  useEffect(() => {
    const v = ref.current;
    if (!v || reduced) return;
    let io: IntersectionObserver | null = null;
    const start = () => {
      v.preload = "auto";
      io = new IntersectionObserver(
        ([e]) => {
          if (e.isIntersecting && !v.ended) void v.play().catch(() => undefined);
          else v.pause();
        },
        { threshold: 0.2 },
      );
      io.observe(v);
    };
    const idle = window.requestIdleCallback ?? ((f: () => void) => window.setTimeout(f, 200));
    const cancelIdle = window.cancelIdleCallback ?? window.clearTimeout;
    let handle = 0;
    const afterLoad = () => (handle = idle(start, { timeout: 1200 }));
    if (document.readyState === "complete") afterLoad();
    else window.addEventListener("load", afterLoad, { once: true });
    return () => {
      window.removeEventListener("load", afterLoad);
      cancelIdle(handle);
      io?.disconnect();
    };
  }, [reduced]);
  if (failed || reduced) return <img className="demo-media" src={failed ? FALLBACK_POSTER : VIDEO.poster} onError={(e) => ((e.currentTarget.src = FALLBACK_POSTER))} alt="" />;
  return (
    <video
      ref={ref}
      className="demo-media"
      poster={VIDEO.poster}
      muted
      playsInline
      preload="none"
      disablePictureInPicture
      disableRemotePlayback
      tabIndex={-1}
      aria-hidden
      onError={() => setFailed(true)}
    >
      <source src={VIDEO.av1} type={'video/mp4; codecs="av01.0.12M.08"'} />
      {/* a source can report an error for an aborted load; fall back only when no source is left to play */}
      <source src={VIDEO.mp4} type="video/mp4" onError={() => ref.current?.networkState === HTMLMediaElement.NETWORK_NO_SOURCE && setFailed(true)} />
    </video>
  );
}

/** The whole landing. It owns the intro, so both the hero's button and Bara on the page can open it. */
export function Landing() {
  const [intro, setIntro] = useState<IntroOpen | null>(null);
  const guide = useRef<GuideHandle>(null);
  const fromBara = (seed = ""): IntroOpen | null => {
    const o = guide.current?.origin();
    return o ? { from: o.from, eyes: o.eyes, seed, label: "Bara" } : null;
  };
  // the hero button opens it from itself while it is on screen; scrolled away, typing opens it from Bara
  const open = (o: IntroOpen) => {
    const seen = o.from.bottom > 0 && o.from.top < window.innerHeight;
    setIntro(seen ? o : (fromBara(o.seed) ?? o));
  };
  const talk = () => {
    const o = fromBara();
    if (o) setIntro(o);
  };
  return (
    <main className="home landing">
      <LandingHero onOpen={open} away={intro !== null} />
      <HowBand />
      <LiveLibrary />
      <TryIt onTalk={talk} />
      <LandingFoot />
      <LandingGuide ref={guide} away={intro !== null} onTalk={talk} />
      {intro && <AgentIntro open={intro} onClose={() => setIntro(null)} />}
    </main>
  );
}

/** The first screen: one plate, the recording playing behind, and Bara's Build button in front. */
function LandingHero(props: { onOpen: (o: IntroOpen) => void; away: boolean }) {
  return (
    <section className="ld-hero" data-guide-section="hero">
      <div className="ld-plate">
        <figure className="ld-bg" aria-label="A recording of Bara building a device, start to finish" data-say="That's me at work. A real build, recorded start to finish." data-at="0.42,0.74">
          <DemoVideo />
        </figure>
        <div className="ld-stage">
          <h1>Describe a device. Watch Bara build it from real parts.</h1>
          <span className="ld-cta-wrap" data-say="Press this and tell me what to make. Or just click me." data-at="0.92,0.7">
            <HeroCta onOpen={props.onOpen} hidden={props.away} />
          </span>
        </div>
      </div>
    </section>
  );
}

/* ---- What a build gives you ---- */

type ArtKind = "parts" | "board" | "case" | "firmware";

/** Small drawings built in code, one per card. They use the page's own ink and paper. */
function StepArt(props: { kind: ArtKind }) {
  switch (props.kind) {
    case "parts":
      return (
        <ul className="sa sa-parts mono">
          {["Rotary encoder", "Key switch ×9", "Controller board"].map((p) => (
            <li key={p}>
              <i aria-hidden />
              <span className="sa-name">{p}</span>
              <span className="sa-src">KiCad lib</span>
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
        </svg>
      );
    case "firmware":
      return (
        <div className="sa sa-fw mono" aria-hidden>
          <span className="sa-fw-bar">
            <i />
            Simulator
          </span>
          <span>&gt; boot</span>
          <span>&gt; keys 9/9 ok</span>
          <span>&gt; knob turned +1</span>
        </div>
      );
  }
}

const HOW: { kind: ArtKind; title: string; text: string; say: string }[] = [
  {
    kind: "parts",
    title: "Real parts",
    text: "Every part comes from an open-source library, with its source and licence beside it.",
    say: "Every part I pick is a real one. Hover it in the build to see where it came from and its licence.",
  },
  {
    kind: "board",
    title: "A routed board",
    text: "A KiCad board laid out and routed around those parts, then checked.",
    say: "Then I lay out a KiCad board and route every trace, live, and run the checks.",
  },
  {
    kind: "case",
    title: "A case that fits",
    text: "A printable case closes around the board. STL, 3MF and STEP.",
    say: "A case closes around that board. You can print it.",
  },
  {
    kind: "firmware",
    title: "Firmware, running",
    text: "Firmware for the pins it chose, running in a simulator before you build anything.",
    say: "And the firmware runs in a simulator, so you see it work before you build it.",
  },
];

function HowBand() {
  return (
    <section id="how" className="ld-sec" aria-labelledby="ld-how-h" data-guide-section="how">
      <header className="ld-sh">
        <h2 id="ld-how-h">One line in, a device out</h2>
        <span className="cap">What every build gives you</span>
      </header>
      <ol className="ld-how">
        {HOW.map((h) => (
          <li key={h.title}>
            <div className="ld-art" data-say={h.say} data-at="0.78,0.32">
              <StepArt kind={h.kind} />
            </div>
            <b>{h.title}</b>
            <p>{h.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ---- The library, as it stands ---- */

/** Calls load once the section is near, so the first screen never waits on the library. */
function useNear<T extends Element>(load: () => void) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return;
        load();
        io.disconnect();
      },
      { rootMargin: "600px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
    // load is a stable module function
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return ref;
}

const loadLibrary = () => {
  void loadGallery();
  void loadOpenSource();
};

function LiveLibrary() {
  const ref = useNear<HTMLElement>(loadLibrary);
  const items = useGallery((s) => s.items);
  const ready = useGallery((s) => s.ready);
  const boards = useOpenSource((s) => s.boards);
  const osReady = useOpenSource((s) => s.ready);
  const toLibrary = () => useApp.setState({ screen: "drafts" });
  const shown = items.slice(0, 4);
  const firstBoards = boards.slice(0, 4);
  return (
    <section ref={ref} id="library" className="ld-sec ld-lib" aria-labelledby="ld-lib-h" data-guide-section="library">
      <header className="ld-sh">
        <h2 id="ld-lib-h">The library, live</h2>
        <button type="button" className="ld-more" onClick={toLibrary}>
          Open the library
        </button>
      </header>
      <h3 className="ld-sub">Built by Bara</h3>
      <ul className="gal-grid ld-gal" data-say="These are builds I finished, every check passed. Open one to look inside." data-at="0.12,0.22">
        {ready && shown.length > 0
          ? shown.map((it, i) => <GalleryCard key={it.build_id} item={it} index={i} />)
          : [0, 1, 2, 3].map((i) => <li key={i} className="gal-card is-loading" aria-hidden />)}
      </ul>
      <h3 className="ld-sub">
        Open-source boards to start from
        {boards.length > 0 && <span className="ld-count mono">{boards.length}</span>}
      </h3>
      <ul className="ld-os" data-say="These are open-source KiCad boards from GitHub, each with its maker and licence." data-at="0.12,0.25">
        {osReady && firstBoards.length > 0
          ? firstBoards.map((b) => (
              <li key={b.slug}>
                <button type="button" className="ld-os-card" onClick={toLibrary} aria-label={`${scrubMakers(b.title)}, in the library`}>
                  <span className="ld-os-thumb">{b.thumb && <img src={thumbUrl(b)} alt="" loading="lazy" decoding="async" />}</span>
                  <span className="ld-os-title">{scrubMakers(b.title)}</span>
                  <span className="ld-os-sub mono">
                    {b.parts} parts · {b.license ?? "No licence"}
                  </span>
                </button>
              </li>
            ))
          : [0, 1, 2, 3].map((i) => <li key={i} className="ld-os-wait" aria-hidden />)}
      </ul>
    </section>
  );
}

/* ---- Try it ---- */

function TryIt(props: { onTalk: () => void }) {
  return (
    <section id="try" className="ld-band" aria-labelledby="ld-band-h" data-guide-section="try">
      <h2 id="ld-band-h">Your turn. What should Bara build?</h2>
      <p className="ld-band-p">One line is enough. Type it, or say it.</p>
      <div className="ld-band-row">
        <button
          type="button"
          className="btn primary ld-band-btn"
          onClick={() => openBuildDialog()}
          aria-haspopup="dialog"
          data-say="Your turn. Tell me what to make, in one line."
          data-at="0.9,0.75"
        >
          Start building
        </button>
        <button type="button" className="btn ld-band-talk" onClick={props.onTalk} aria-haspopup="dialog">
          Talk to Bara
        </button>
      </div>
    </section>
  );
}

function LandingFoot() {
  return (
    <footer className="ld-foot">
      <span className="ld-foot-brand">
        <BaraMark className="brand-mark" />
        Bara
        <span className="brand-by">by Tangible Parts</span>
      </span>
      <button type="button" className="ld-foot-link" onClick={() => useApp.setState({ screen: "drafts" })}>
        Library
      </button>
      <span className="ld-foot-year">© {new Date().getFullYear()}</span>
    </footer>
  );
}
