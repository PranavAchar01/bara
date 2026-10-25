// Bara on the landing: the leaning arrowhead with its name chip, out on the page and showing the visitor
// around. As the page scrolls it flies to the section in view and points at its parts one after another,
// saying a line about each (the lines live on the page itself, as data-say on whatever it points at).
// It glances toward the mouse, drifts a little at rest, and clicking it opens the talk-to-Bara intro.
// One requestAnimationFrame loop writes transforms to refs; React renders only when the line changes.
// Under reduced motion it jumps instead of flying, and does not drift or type.
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { clamp, reducedMotion, Spring, wander, type SpringCfg } from "../bot/spring";

/** A stop: what it points at (as a point inside that element, 0..1 each way) and what it says there. */
interface Stop {
  el: HTMLElement;
  fx: number;
  fy: number;
  say: string;
}

export interface GuideHandle {
  /** Where the intro should grow from when it opens from Bara. */
  origin(): { from: DOMRect; eyes: DOMRect } | null;
}

const FLY: SpringCfg = { stiffness: 120, damping: 17 };
/** How long it stays on one stop before moving to the next one in the same section. */
const DWELL_MS = 4200;
const TYPE_MS = 18;
/** Room the chip needs to the right of the tip (it flips left when there is not). */
const ROOM = 170;

const ARROW = "M3 3 L17.2 8.9 L10.5 10.5 L8.9 17.2 Z";

function stopsOf(section: Element): Stop[] {
  return [...section.querySelectorAll<HTMLElement>("[data-say]")]
    .filter((el) => el.offsetParent !== null)
    .map((el) => {
      const [fx, fy] = (el.dataset.at ?? "0.5,0.5").split(",").map(Number);
      return { el, fx, fy, say: el.dataset.say ?? "" };
    });
}

export const LandingGuide = forwardRef<GuideHandle, { away: boolean; onTalk: () => void }>(function LandingGuide(props, handle) {
  const root = useRef<HTMLDivElement>(null);
  const cursor = useRef<SVGSVGElement>(null);
  const chip = useRef<HTMLSpanElement>(null);
  const eyes = useRef<HTMLSpanElement>(null);
  const ring = useRef<HTMLSpanElement>(null);
  const sayEl = useRef<HTMLSpanElement>(null);
  const [say, setSay] = useState("");
  const [typed, setTyped] = useState(0);
  const [shown, setShown] = useState(false);
  const hovered = useRef(false);
  /** Set when where it points must be worked out again: a scroll, a resize, a new line laid out. */
  const dirty = useRef(true);

  useImperativeHandle(handle, () => ({
    origin: () => (chip.current && eyes.current ? { from: chip.current.getBoundingClientRect(), eyes: eyes.current.getBoundingClientRect() } : null),
  }));

  // the line types itself out; once it is laid out, its width is known and the aim is redone
  useEffect(() => {
    dirty.current = true;
    if (reducedMotion()) return setTyped(say.length);
    setTyped(0);
    let n = 0;
    const t = window.setInterval(() => {
      n += 1;
      setTyped(n);
      if (n >= say.length) window.clearInterval(t);
    }, TYPE_MS);
    return () => window.clearInterval(t);
  }, [say]);

  useEffect(() => {
    const still = reducedMotion();
    const x = new Spring(0, FLY);
    const y = new Spring(0, FLY);
    const look = { x: new Spring(0, { stiffness: 200, damping: 20 }), y: new Spring(0, { stiffness: 200, damping: 20 }) };
    let mouse: { x: number; y: number } | null = null;
    let section: Element | null = null;
    let stops: Stop[] = [];
    let index = 0;
    let since = performance.now();
    let placed = false;
    let arrived = false;
    let flip = false;
    let tx = 0;
    let ty = 0;
    let bw = 0;
    let sayDx = NaN;
    let raf = 0;
    let last = performance.now();

    const pick = (now: number) => {
      const vh = window.innerHeight;
      const line = vh * 0.45;
      let best: Element | null = null;
      let bestD = Infinity;
      for (const s of document.querySelectorAll("[data-guide-section]")) {
        const r = s.getBoundingClientRect();
        const d = r.top <= line && r.bottom >= line ? 0 : Math.min(Math.abs(r.top - line), Math.abs(r.bottom - line));
        if (d < bestD) {
          bestD = d;
          best = s;
        }
      }
      if (best !== section) {
        section = best;
        stops = best ? stopsOf(best) : [];
        index = 0;
        since = now;
        arrived = false;
        setSay(stops[0]?.say ?? "");
      }
    };

    const aim = () => {
      const s = stops[index];
      if (!s) return;
      const r = s.el.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      tx = clamp(r.left + r.width * s.fx, 12, vw - 12);
      ty = clamp(r.top + r.height * s.fy, 60, vh - 150);
      flip = tx + ROOM > vw;
      bw = sayEl.current?.offsetWidth ?? 0;
    };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      if (dirty.current) {
        dirty.current = false;
        pick(now);
        aim();
      }
      // the next thing in this section, unless the visitor is busy with Bara
      if (stops.length > 1 && !hovered.current && now - since > DWELL_MS) {
        index = (index + 1) % stops.length;
        since = now;
        arrived = false;
        setSay(stops[index].say);
        aim();
      }
      // curious: within reach of the mouse it leans a little toward it, otherwise it drifts at rest
      let ox = 0;
      let oy = 0;
      let lx = 0;
      let ly = 0;
      if (mouse) {
        const dx = mouse.x - x.value;
        const dy = mouse.y - y.value;
        const d = Math.hypot(dx, dy) || 1;
        lx = (dx / d) * Math.min(1, d / 160);
        ly = (dy / d) * Math.min(1, d / 160);
        if (!still && d < 280 && !hovered.current) {
          const k = (1 - d / 280) * 14;
          ox = (dx / d) * k;
          oy = (dy / d) * k;
        }
      }
      const t = now / 1000;
      const drift = still || hovered.current ? 0 : 1;
      x.target = tx + ox + wander(t * 0.7, 1) * 5 * drift;
      y.target = ty + oy + wander(t * 0.6, 2) * 4 * drift;
      look.x.target = lx;
      look.y.target = ly;
      if (!placed || still) {
        for (const s of [x, y, look.x, look.y]) {
          s.value = s.target;
          s.velocity = 0;
        }
        placed = true;
      } else {
        for (const s of [x, y, look.x, look.y]) s.step(dt);
      }
      // it taps the thing it is talking about once it gets there
      if (!arrived && Math.hypot(x.value - tx, y.value - ty) < 18 && Math.hypot(x.velocity, y.velocity) < 60) {
        arrived = true;
        if (!still && ring.current) {
          ring.current.classList.remove("on");
          void ring.current.offsetWidth;
          ring.current.classList.add("on");
        }
      }
      const el = root.current;
      if (!el) return;
      el.style.transform = `translate3d(${x.value.toFixed(1)}px, ${y.value.toFixed(1)}px, 0)`;
      // the line slides along under the chip as far as it must to stay on screen (a phone is narrow),
      // worked out from where Bara is now, so it stays on screen in flight too
      const vw = window.innerWidth;
      const dx = Math.round(flip ? Math.max(0, 12 - (x.value - 16 - bw)) : Math.min(0, vw - 12 - (x.value + 16 + bw)));
      if (dx !== sayDx) {
        sayDx = dx;
        el.style.setProperty("--say-dx", `${dx}px`);
      }
      if (el.classList.contains("is-flip") !== flip) el.classList.toggle("is-flip", flip);
      // it tips into the way it is travelling and settles back when it stops
      const lean = clamp(x.velocity * 0.012 - y.velocity * 0.006, -14, 14);
      if (cursor.current) cursor.current.style.transform = `rotate(${(flip ? -lean : lean).toFixed(2)}deg)`;
      if (eyes.current) {
        eyes.current.style.setProperty("--look-x", `${(look.x.value * 1.6).toFixed(2)}px`);
        eyes.current.style.setProperty("--look-y", `${(look.y.value * 1.2).toFixed(2)}px`);
      }
    };

    const onScroll = () => (dirty.current = true);
    const onMove = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      mouse = { x: e.clientX, y: e.clientY };
    };
    const onLeave = () => (mouse = null);
    document.addEventListener("scroll", onScroll, { capture: true, passive: true });
    window.addEventListener("resize", onScroll);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    raf = requestAnimationFrame(frame);
    // it shows up once the page has settled, already in place
    const t = window.setTimeout(() => setShown(true), 500);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(t);
      document.removeEventListener("scroll", onScroll, { capture: true });
      window.removeEventListener("resize", onScroll);
      window.removeEventListener("pointermove", onMove);
      document.documentElement.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <div ref={root} className={`lg ${shown && !props.away ? "is-on" : ""}`}>
      <span ref={ring} className="lg-ring" aria-hidden />
      <button
        type="button"
        className="lg-hit"
        onClick={props.onTalk}
        onPointerEnter={() => (hovered.current = true)}
        onPointerLeave={() => (hovered.current = false)}
        aria-label="Talk to Bara"
        tabIndex={props.away ? -1 : 0}
      >
        <svg ref={cursor} className="lg-cursor" viewBox="0 0 20 20" width="22" height="22" aria-hidden>
          <defs>
            <linearGradient id="lg-cur-g" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" className="lg-cur-lit" />
              <stop offset="1" className="lg-cur-deep" />
            </linearGradient>
          </defs>
          <path className="lg-cur-rim" d={ARROW} />
          <path className="lg-cur-body" d={ARROW} />
          <path className="lg-cur-shine" d="M5.2 5.2 L11.6 7.9" />
        </svg>
        <span ref={chip} className="lg-chip">
          <span ref={eyes} className="lg-eyes" aria-hidden>
            <i />
            <i />
          </span>
          Bara
          <span className="lg-talk">talk to me</span>
        </span>
        {say && (
          <span ref={sayEl} className="lg-say" aria-hidden>
            {say.slice(0, typed)}
            <span className="lg-say-rest">{say.slice(typed)}</span>
          </span>
        )}
      </button>
    </div>
  );
});
