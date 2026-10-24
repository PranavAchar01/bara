import { useEffect, useState, type ReactNode } from "react";
import type { PartCard } from "../spec/types";
import { known, type Tone } from "./format";

export function Panel(props: {
  title: string;
  meta?: ReactNode;
  children?: ReactNode;
  className?: string;
  id?: string;
  actions?: ReactNode;
}) {
  return (
    <section className={`panel ${props.className ?? ""}`} id={props.id} aria-label={props.title}>
      <header className="panel-h">
        <h2>{props.title}</h2>
        {props.meta !== undefined && <span className="panel-meta">{props.meta}</span>}
        {props.actions && <span className="panel-actions">{props.actions}</span>}
      </header>
      <div className="panel-b">{props.children}</div>
    </section>
  );
}

export function Chip(props: {
  children: ReactNode;
  tone?: Tone;
  variant?: "solid" | "outline";
  title?: string;
  onClick?: () => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}) {
  const cls = `chip tone-${props.tone ?? "muted"} ${props.variant ?? "outline"}`;
  if (props.onClick) {
    return (
      <button type="button" className={cls} title={props.title} onClick={props.onClick} onMouseEnter={props.onMouseEnter} onMouseLeave={props.onMouseLeave}>
        {props.children}
      </button>
    );
  }
  return (
    <span className={cls} title={props.title} onMouseEnter={props.onMouseEnter} onMouseLeave={props.onMouseLeave}>
      {props.children}
    </span>
  );
}

export function Badge(props: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span className={`badge tone-${props.tone ?? "muted"}`} title={props.title}>
      {props.children}
    </span>
  );
}

export function Dot(props: { tone: Tone | null; title?: string }) {
  return <span className={`dot tone-${props.tone ?? "muted"}`} title={props.title} aria-label={props.title} />;
}

export function Empty(props: { children: ReactNode }) {
  return <p className="empty">{props.children}</p>;
}

export function Skeleton(props: { lines?: number }) {
  return (
    <div className="skeleton" aria-hidden>
      {Array.from({ length: props.lines ?? 2 }, (_, i) => (
        <span key={i} style={{ width: `${70 - i * 18}%` }} />
      ))}
    </div>
  );
}

/** C27 ProvenanceBadge: pure view of verified, licence_spdx and commercial_ok. */
export function ProvenanceBadge(props: { card: Pick<PartCard, "verified" | "licence_spdx" | "commercial_ok"> }) {
  const v = known(props.card.verified, ["geometry", "human", "datasheet", "third_party", "none"] as const);
  const commercial = known(props.card.commercial_ok, ["yes", "no"] as const);
  const verified = v === "geometry" || v === "human" || v === "datasheet";
  return (
    <span className="prov">
      {verified && (
        <span className="prov-mark tone-ok" title={`Verified (${v})`}>
          <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden>
            <path d="M2.5 6.2l2.3 2.3 4.7-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </span>
      )}
      {v === "third_party" && <span className="prov-dashed" title="Dimensions from a third party">3rd party</span>}
      {!verified && v !== "third_party" && <span className="prov-unverified" title="Not verified">unverified</span>}
      {props.card.licence_spdx && (
        <span className={`prov-lic ${commercial !== "yes" ? "warn" : ""}`} title={commercial !== "yes" ? `Commercial use: ${commercial}` : "Commercial use OK"}>
          {props.card.licence_spdx}
        </span>
      )}
    </span>
  );
}

/** Re-render on an interval while `active`; returns performance.now(). */
export function useNow(active: boolean, ms = 100): number {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return;
    const h = setInterval(() => setNow(performance.now()), ms);
    return () => clearInterval(h);
  }, [active, ms]);
  return now;
}

export function Icon(props: { name: "x" | "stop" | "send" | "chevron" | "export" | "home" | "play"; size?: number }) {
  const s = props.size ?? 14;
  const common = { width: s, height: s, viewBox: "0 0 16 16", "aria-hidden": true } as const;
  switch (props.name) {
    case "x":
      return (
        <svg {...common}>
          <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      );
    case "stop":
      return (
        <svg {...common}>
          <rect x="4" y="4" width="8" height="8" rx="1.5" fill="currentColor" />
        </svg>
      );
    case "send":
      return (
        <svg {...common}>
          <path d="M3 8h9M8.5 4.5L12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "chevron":
      return (
        <svg {...common}>
          <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      );
    case "export":
      return (
        <svg {...common}>
          <path d="M8 2.5v7M5 6.5l3 3 3-3M3 11.5v2h10v-2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "home":
      return (
        <svg {...common}>
          <path d="M2.5 7.5L8 3l5.5 4.5M4 6.5V13h8V6.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      );
    case "play":
      return (
        <svg {...common}>
          <path d="M5 3.5v9l7-4.5z" fill="currentColor" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
        </svg>
      );
  }
}
