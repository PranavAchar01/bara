// The project around the open device: its devices, adding another one, and the links that make
// them one bigger build (a cable between two connectors, a radio pairing), with one BOM for all.
import { useMemo, useState } from "react";
import { useApp } from "../state/store";
import { addCompanionCanvas, canvasStatus, switchCanvas } from "../state/canvases";
import { startBuild } from "../net/client";
import { compatibility, makeLink, portKey, projectBomCsv, suggestLinks, type DevicePort, type ProjectLink } from "./links";
import { addLink, removeLink, setProjectOpen, useProject, useProjectDevices, useProjectPorts, type ProjectDevice } from "./project";
import "./project.css";

/** The pill in the canvas tab strip that opens the panel. */
export function ProjectButton() {
  const devices = useProjectDevices();
  const links = useProject((s) => s.links);
  const open = useProject((s) => s.open);
  const ids = new Set(devices.map((d) => d.canvasId));
  const mine = links.filter((l) => ids.has(l.a.canvasId) && ids.has(l.b.canvasId)).length;
  return (
    <button type="button" className={`pj-pill ${open ? "on" : ""}`} onClick={() => setProjectOpen(!open)} aria-expanded={open} title="Devices in this project and how they connect">
      <ProjectGlyph />
      <span>Project</span>
      <span className="pj-count">
        {devices.length} {devices.length === 1 ? "device" : "devices"}
        {mine ? ` · ${mine} ${mine === 1 ? "link" : "links"}` : ""}
      </span>
    </button>
  );
}

export function ProjectPanel() {
  const open = useProject((s) => s.open);
  if (!open) return null;
  return <Panel />;
}

function Panel() {
  const devices = useProjectDevices();
  const ports = useProjectPorts(devices);
  const allLinks = useProject((s) => s.links);
  const ids = useMemo(() => new Set(devices.map((d) => d.canvasId)), [devices]);
  const links = useMemo(() => allLinks.filter((l) => ids.has(l.a.canvasId) && ids.has(l.b.canvasId)), [allLinks, ids]);
  const suggestions = useMemo(() => suggestLinks(ports, links), [ports, links]);
  const byKey = useMemo(() => new Map(ports.map((p) => [portKey(p), p])), [ports]);
  const nameOf = (canvasId: string) => devices.find((d) => d.canvasId === canvasId)?.name ?? "Device";

  return (
    <aside className="pj-panel" aria-label="Project">
      <header className="pj-head">
        <h3>Project</h3>
        <button type="button" className="pj-x" onClick={() => setProjectOpen(false)} aria-label="Close project">
          ×
        </button>
      </header>

      <section className="pj-sec">
        <h4>Devices</h4>
        <ul className="pj-devices">
          {devices.map((d) => (
            <DeviceRow key={d.canvasId} d={d} links={links.filter((l) => l.a.canvasId === d.canvasId || l.b.canvasId === d.canvasId).length} />
          ))}
        </ul>
        <AddDevice firstName={devices[0]?.name ?? ""} />
      </section>

      <section className="pj-sec">
        <h4>Connections</h4>
        {devices.length < 2 && <p className="pj-empty">Add a second device, then connect them here.</p>}
        {links.map((l) => (
          <LinkRow key={l.link_id} l={l} a={byKey.get(portKey(l.a))} b={byKey.get(portKey(l.b))} nameOf={nameOf} />
        ))}
        {suggestions.map((s) => (
          <div key={`${portKey(s.a)}>${portKey(s.b)}`} className="pj-suggest">
            <LinkIcon medium={s.a.medium} />
            <div className="pj-ends">
              <span>
                <b>{nameOf(s.a.canvasId)}</b> {s.a.label}
              </span>
              <span>
                <b>{nameOf(s.b.canvasId)}</b> {s.b.label}
              </span>
              <span className={`pj-note ${s.fit.status}`}>{s.fit.note}</span>
            </div>
            <button type="button" className="btn primary sm" onClick={() => addLink(makeLink(s.a, s.b, s.fit))}>
              Connect
            </button>
          </div>
        ))}
        {devices.length >= 2 && <ManualConnect ports={ports} links={links} nameOf={nameOf} />}
      </section>

      <ProjectParts devices={devices} links={links} />
    </aside>
  );
}

function DeviceRow(props: { d: ProjectDevice; links: number }) {
  const { d } = props;
  const status = useApp((s) => canvasStatus(s, d.canvasId));
  const parts = d.build?.parts.reduce((n, p) => n + (p.quantity || 1), 0) ?? 0;
  return (
    <li>
      <button type="button" className={`pj-device ${d.active ? "active" : ""}`} onClick={() => switchCanvas(d.canvasId)} title={d.active ? "On screen" : `Open ${d.name}`}>
        <span className={`ct-dot st-${status}`} />
        <span className="pj-dname">{d.name}</span>
        <span className="pj-dmeta">
          {parts ? `${parts} parts` : status === "empty" ? "empty" : status}
          {props.links ? ` · ${props.links} ${props.links === 1 ? "link" : "links"}` : ""}
        </span>
      </button>
    </li>
  );
}

function AddDevice(props: { firstName: string }) {
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim();
    if (!t) return;
    addCompanionCanvas();
    startBuild(t);
    setText("");
  };
  return (
    <form
      className="pj-add"
      onSubmit={(e) => {
        e.preventDefault();
        add();
      }}
    >
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={props.firstName ? `Another device for ${short(props.firstName)}: a dongle, a dock…` : "Another device: a dongle, a dock…"}
        aria-label="Describe another device"
        maxLength={400}
      />
      <button type="submit" className="btn sm" disabled={!text.trim()}>
        Add device
      </button>
    </form>
  );
}

function LinkRow(props: { l: ProjectLink; a?: DevicePort; b?: DevicePort; nameOf: (id: string) => string }) {
  const { l } = props;
  return (
    <div className={`pj-link ${l.status}`}>
      <LinkIcon medium={l.medium} />
      <div className="pj-ends">
        <span>
          <b>{props.nameOf(l.a.canvasId)}</b> {props.a?.label ?? l.a.interfaceId}
        </span>
        <span>
          <b>{props.nameOf(l.b.canvasId)}</b> {props.b?.label ?? l.b.interfaceId}
        </span>
        <span className={`pj-note ${l.status}`}>{l.note}</span>
      </div>
      <button type="button" className="pj-x" onClick={() => removeLink(l.link_id)} aria-label="Disconnect">
        ×
      </button>
    </div>
  );
}

function ManualConnect(props: { ports: DevicePort[]; links: ProjectLink[]; nameOf: (id: string) => string }) {
  const used = new Set(props.links.flatMap((l) => [portKey(l.a), portKey(l.b)]));
  const free = props.ports.filter((p) => !used.has(portKey(p)));
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const pa = free.find((p) => portKey(p) === a);
  const pb = free.find((p) => portKey(p) === b);
  const fit = pa && pb ? compatibility(pa, pb) : null;
  if (free.length < 2) return null;
  const option = (p: DevicePort) => (
    <option key={portKey(p)} value={portKey(p)}>
      {props.nameOf(p.canvasId)}: {p.label}
    </option>
  );
  return (
    <details className="pj-manual">
      <summary>Connect other ports</summary>
      <select value={a} onChange={(e) => setA(e.target.value)} aria-label="From port">
        <option value="">From…</option>
        {free.map(option)}
      </select>
      <select value={b} onChange={(e) => setB(e.target.value)} aria-label="To port">
        <option value="">To…</option>
        {free.filter((p) => !pa || p.canvasId !== pa.canvasId).map(option)}
      </select>
      {fit && <span className={`pj-note ${fit.ok ? fit.status : "bad"}`}>{fit.note}</span>}
      <button
        type="button"
        className="btn sm"
        disabled={!fit?.ok}
        onClick={() => {
          if (pa && pb && fit?.ok) {
            addLink(makeLink(pa, pb, fit));
            setA("");
            setB("");
          }
        }}
      >
        Connect
      </button>
    </details>
  );
}

function ProjectParts(props: { devices: ProjectDevice[]; links: ProjectLink[] }) {
  const total = props.devices.reduce((n, d) => n + (d.build?.parts.reduce((m, p) => m + (p.quantity || 1), 0) ?? 0), 0);
  const cables = props.links.filter((l) => l.medium === "cable").length;
  const download = () => {
    const csv = projectBomCsv(props.devices, props.links);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "project-bom.csv";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <section className="pj-sec">
      <h4>Parts</h4>
      <p className="pj-total">
        <b>{total}</b> parts across {props.devices.length} {props.devices.length === 1 ? "device" : "devices"}
        {cables ? `, plus ${cables} ${cables === 1 ? "cable" : "cables"} between them` : ""}
      </p>
      <button type="button" className="btn sm" onClick={download} disabled={!total}>
        Download project BOM
      </button>
    </section>
  );
}

function LinkIcon(props: { medium: "cable" | "wireless" }) {
  return props.medium === "wireless" ? (
    <svg className="pj-ico" viewBox="0 0 16 16" width="16" height="16" aria-label="Wireless">
      <path d="M3 6.5a7 7 0 0 1 10 0M5 9a4 4 0 0 1 6 0" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="8" cy="11.5" r="1.2" fill="currentColor" />
    </svg>
  ) : (
    <svg className="pj-ico" viewBox="0 0 16 16" width="16" height="16" aria-label="Cable">
      <path d="M2 5h3v6H2M14 5h-3v6h3M5 8h6" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ProjectGlyph() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden>
      <rect x="1.5" y="4" width="5" height="8" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <rect x="9.5" y="6" width="5" height="5" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
      <path d="M6.5 8h3" stroke="currentColor" strokeWidth="1.3" strokeDasharray="1.2 1.2" />
    </svg>
  );
}

function short(name: string): string {
  const t = name.replace(/^(?:an?|the)\s+/i, "").split(/\s+(?:with|that|for)\s+/i)[0];
  return t.length > 28 ? `${t.slice(0, 27)}…` : t;
}
