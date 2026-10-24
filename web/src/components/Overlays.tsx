import { useEffect, useMemo, useState } from "react";
import { useApp } from "../state/store";
import { applyEdit, getRest } from "../net/client";
import { paths } from "../net/rest";
import type { Alternatives, BuildPart, Color, EditOp, Part, PartCard, PartsPage, PortRef } from "../spec/types";
import { Badge, Chip, Empty, Icon, ProvenanceBadge, Skeleton } from "../ui/common";
import { checkTone, fmtValue, known, vlabel } from "../ui/format";
import { AskBot } from "../bot/AskBot";

type Load<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "error"; message: string };

function useRest<T>(path: string | null, pick: (body: unknown) => T): Load<T> | null {
  const [res, setRes] = useState<Load<T> | null>(null);
  useEffect(() => {
    if (!path) {
      setRes(null);
      return;
    }
    let live = true;
    setRes({ state: "loading" });
    void getRest()
      .get<unknown>(path)
      .then((r) => {
        if (!live) return;
        setRes(r.ok ? { state: "ok", data: pick(r.body) } : { state: "error", message: r.error.message });
      });
    return () => {
      live = false;
    };
    // pick is a stable projection supplied inline by callers
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);
  return res;
}

const partCache = new Map<string, Promise<Part | null>>();
export function fetchPart(partId: string): Promise<Part | null> {
  let p = partCache.get(partId);
  if (!p) {
    p = getRest()
      .get<{ part: Part }>(paths.part(partId))
      .then((r) => (r.ok ? ((r.body as { part?: Part }).part ?? null) : null));
    partCache.set(partId, p);
  }
  return p;
}

function usePart(partId: string | null): Part | null | "loading" {
  const [part, setPart] = useState<Part | null | "loading">(partId ? "loading" : null);
  useEffect(() => {
    if (!partId) {
      setPart(null);
      return;
    }
    let live = true;
    setPart("loading");
    void fetchPart(partId).then((p) => {
      if (live) setPart(p);
    });
    return () => {
      live = false;
    };
  }, [partId]);
  return part;
}

function closeOverlay() {
  useApp.setState({ overlay: null, inspectPartId: null });
}

function SideHead(props: { title: string; sub?: string; onBack?: () => void }) {
  return (
    <header className="side-h">
      {props.onBack && (
        <button type="button" className="btn ghost sm" onClick={props.onBack}>
          Back
        </button>
      )}
      <div className="side-title">
        <h2>{props.title}</h2>
        {props.sub && <span className="muted small mono">{props.sub}</span>}
      </div>
      <button type="button" className="btn ghost sm icon" aria-label="Close" onClick={closeOverlay}>
        <Icon name="x" />
      </button>
    </header>
  );
}

function KeySpecs(props: { card: PartCard }) {
  if (!props.card.key_specs?.length) return null;
  return (
    <div className="kv">
      {props.card.key_specs.map((k) => (
        <FragmentKV key={k.label} k={k.label} v={fmtValue(k.value, k.unit)} />
      ))}
    </div>
  );
}

function FragmentKV(props: { k: string; v: string }) {
  return (
    <>
      <span>{props.k}</span>
      <span>{props.v}</span>
    </>
  );
}

/** C12 PartInspector. */
export function PartInspector() {
  const build = useApp((s) => s.build);
  const selection = useApp((s) => s.selection);
  const inspectPartId = useApp((s) => s.inspectPartId);
  const vocab = useApp((s) => s.vocab);
  const instance = build?.parts.find((p) => p.instance_id === selection) ?? null;
  const partId = instance?.part_id ?? inspectPartId;
  const part = usePart(partId);
  const [colorOpen, setColorOpen] = useState(false);
  useEffect(() => setColorOpen(false), [selection]);
  // S swap, R recolour, M move: the same actions as the buttons, only on a finished build.
  const keyTarget = build?.status === "done" ? instance : null;
  useEffect(() => {
    if (!keyTarget) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "s" && keyTarget.slot_id) useApp.setState({ overlay: "swap" });
      else if (k === "r") setColorOpen((o) => !o);
      else if (k === "m") useApp.setState((s) => ({ moving: s.moving === keyTarget.instance_id ? null : keyTarget.instance_id }));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keyTarget]);
  if (!partId) return null;
  const card = instance?.card;
  const decision = [...(build?.decisions ?? [])].reverse().find((d) => d.slot_id === instance?.slot_id && d.chosen_part_id === partId);
  const checks = (build?.checks ?? []).filter((c) => (c.subjects ?? []).some((s) => s.instance_id === instance?.instance_id));
  const done = build?.status === "done";
  const full = part !== "loading" ? part : null;
  return (
    <aside className="side-overlay" aria-label="Part inspector">
      <SideHead title={card?.display_name ?? full?.display_name ?? partId} sub={instance ? `${instance.label ?? instance.instance_id}  ${partId}` : partId} />
      <div className="side-b">
        {card && (
          <section className="insp-part">
            {card.summary && <p className="insp-summary">{card.summary}</p>}
            <KeySpecs card={card} />
            {instance && (
              <div className="insp-facts">
                <span className="insp-fact">
                  <b>{instance.quantity}</b>
                  <span>qty</span>
                </span>
                <span className="insp-fact">
                  <b>{instance.placement.source ?? "—"}</b>
                  <span>placed by</span>
                </span>
                <span className="insp-fact">
                  <b>{instance.placement.locked ? "locked" : "free"}</b>
                  <span>position</span>
                </span>
              </div>
            )}
          </section>
        )}
        {done && instance && (
          <div className="insp-actions">
            <button type="button" className="btn sm" disabled={!instance.slot_id} onClick={() => useApp.setState({ overlay: "swap" })} title="Swap (S)">
              Swap <kbd>S</kbd>
            </button>
            <button type="button" className="btn sm" onClick={() => setColorOpen((o) => !o)} aria-expanded={colorOpen} title="Recolour (R)">
              Recolour <kbd>R</kbd>
            </button>
            <button
              type="button"
              className="btn sm"
              title="Move (M)"
              onClick={() => useApp.setState((s) => ({ moving: s.moving === instance.instance_id ? null : instance.instance_id }))}
            >
              Move <kbd>M</kbd>
            </button>
            <button
              type="button"
              className="btn sm ghost danger"
              onClick={() => {
                applyEdit([{ op: "remove_part", instance_id: instance.instance_id }], `Remove ${instance.card.display_name}`);
                closeOverlay();
              }}
            >
              Remove
            </button>
          </div>
        )}
        {colorOpen && instance && <ColorPicker target={{ instance_id: instance.instance_id }} current={instance.color ?? null} onClose={() => setColorOpen(false)} />}
        {instance && <AskBot instance={instance} />}
        {instance && (
          <section>
            <h3>Position</h3>
            <div className="insp-fields">
              {["X", "Y", "Z"].map((axis, i) => (
                <span className="insp-field" key={axis}>
                  <span>{axis}</span>
                  {instance.placement.position_mm[i]?.toFixed(1)}
                </span>
              ))}
              <span className="insp-field">
                <span>⟲</span>
                {instance.placement.rotation_deg.map((n) => n.toFixed(0)).join(", ")}°
              </span>
            </div>
          </section>
        )}
        {decision && (
          <section className="insp-why">
            <h3>Why this part</h3>
            <p className="reason">{decision.reason}</p>
          </section>
        )}
        {checks.length > 0 && (
          <section>
            <h3>Checks</h3>
            <ul className="check-lines">
              {checks.map((c) => (
                <li key={c.check_key} className={`check-line tone-${checkTone(c)}`}>
                  <span className="dot" />
                  <span>{c.message}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
        <section className="insp-meta">
          <h3>Source</h3>
          {card && <ProvenanceBadge card={card} />}
          {part === "loading" ? (
            <Skeleton lines={3} />
          ) : full ? (
            <>
              {full.interfaces.length > 0 && (
                <ul className="ifaces small">
                  {full.interfaces.map((i) => (
                    <li key={i.id}>
                      <span className="mono">{i.id}</span> <Badge tone={i.role === "provides" ? "accent" : "muted"}>{i.role}</Badge>{" "}
                      <span className="muted">{vlabel(vocab, "interface_types", i.type)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="kv">
                <span>Licence</span>
                <span>
                  {full.licence.spdx} {known(full.licence.commercial_ok, ["yes", "no"] as const) === "yes" ? "" : "(check commercial use)"}
                </span>
                {full.licence.attribution && <FragmentKV k="Attribution" v={full.licence.attribution} />}
                {full.provenance.extractor && <FragmentKV k="Extractor" v={String(full.provenance.extractor)} />}
                {full.provenance.verified && <FragmentKV k="Verified" v={String(full.provenance.verified)} />}
              </div>
              {full.datasheet && (
                <a className="small" href={full.datasheet} target="_blank" rel="noreferrer noopener">
                  Datasheet
                </a>
              )}
              {full.provenance.source_url && (
                <a className="small" href={full.provenance.source_url} target="_blank" rel="noreferrer noopener">
                  Source
                </a>
              )}
            </>
          ) : (
            <p className="muted small">Catalog details are not available for this part.</p>
          )}
        </section>
      </div>
    </aside>
  );
}

/** C13 SwapDrawer: swap every instance in the slot that carries the same part. */
export function SwapDrawer() {
  const build = useApp((s) => s.build);
  const selection = useApp((s) => s.selection);
  const edit = useApp((s) => s.view.edit);
  const instance = build?.parts.find((p) => p.instance_id === selection) ?? null;
  const path = build && instance?.slot_id ? paths.alternatives(build.build_id, instance.slot_id, instance.instance_id) : null;
  const res = useRest<Alternatives>(path, (b) => b as Alternatives);
  const siblings = useMemo(
    () => (build?.parts ?? []).filter((p) => instance && p.slot_id === instance.slot_id && p.part_id === instance.part_id),
    [build?.parts, instance],
  );
  const [all, setAll] = useState(true);
  const [sentFor, setSentFor] = useState<string | null>(null);
  if (!instance) return null;
  const targets = all ? siblings : [instance];
  const busy = edit !== null && (edit.phase === "pending" || edit.phase === "applying");
  const swap = (card: PartCard) => {
    const ops: EditOp[] = targets.map((t: BuildPart) => ({ op: "swap_part", instance_id: t.instance_id, part_id: card.part_id }));
    setSentFor(card.part_id);
    applyEdit(ops, `Swap to ${card.display_name}`);
  };
  return (
    <aside className="side-overlay" aria-label="Swap part">
      <SideHead title="Swap" sub={instance.card.display_name} onBack={() => useApp.setState({ overlay: "inspector" })} />
      <div className="side-b">
        {siblings.length > 1 && (
          <label className="check small">
            <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Apply to all {siblings.length} in this slot
            {siblings.some((s) => s.side && s.side !== "none") ? " (both halves)" : ""}
          </label>
        )}
        {res === null || res.state === "loading" ? (
          <Skeleton lines={4} />
        ) : res.state === "error" ? (
          <Empty>{res.message}</Empty>
        ) : res.data.items.length === 0 ? (
          <Empty>No alternatives in the catalog.</Empty>
        ) : (
          <ul className="alts">
            {res.data.items.map((it) => {
              const current = it.card.part_id === instance.part_id;
              const disabled = !it.compatible || current || busy;
              return (
                <li key={it.card.part_id} className={`alt ${it.compatible ? "" : "incompatible"} ${current ? "current" : ""}`}>
                  <button type="button" className="alt-btn" disabled={disabled} onClick={() => swap(it.card)}>
                    <span className="alt-name">
                      <strong>{it.card.display_name}</strong>
                      {current && <Badge tone="muted">current</Badge>}
                      {sentFor === it.card.part_id && busy && <span className="spinner" aria-hidden />}
                    </span>
                    <ProvenanceBadge card={it.card} />
                    {(it.deltas ?? []).length > 0 && (
                      <span className="chips">
                        {it.deltas?.map((d, i) => (
                          <Chip key={i} tone="muted">
                            {d.label ?? ""}: {fmtValue(d.from)} to {fmtValue(d.to)}
                          </Chip>
                        ))}
                      </span>
                    )}
                    {(it.failed_checks ?? []).map((c) => (
                      <span key={c.check_key} className="alt-fail small">
                        {c.message}
                      </span>
                    ))}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

const SWATCHES = ["#9E9E9E", "#202326", "#F2F2EE", "#2F55D4", "#C2362F", "#2E7D4F", "#D9A043", "#6B4FA8"];
const MATERIALS = ["plastic", "metal", "rubber", "wood", "glass", "fabric"];

/** C22 ColorPicker: swatches, hex input, material select. */
export function ColorPicker(props: { target: { instance_id?: string; enclosure_id?: string }; current: Color | null; onClose: () => void }) {
  const [hex, setHex] = useState(props.current?.hex ?? "#9E9E9E");
  const [material, setMaterial] = useState<string>(props.current?.material ?? "plastic");
  const valid = /^#[0-9a-fA-F]{6}$/.test(hex);
  const send = (h: string) => {
    if (!/^#[0-9a-fA-F]{6}$/.test(h)) return;
    applyEdit([{ op: "recolor", ...props.target, color: { hex: h.toUpperCase(), material } }], `Recolor to ${h.toUpperCase()}`);
    props.onClose();
  };
  return (
    <div className="popover color-picker" role="dialog" aria-label="Color">
      <div className="swatches">
        {SWATCHES.map((s) => (
          <button key={s} type="button" className={`swatch ${hex.toUpperCase() === s ? "active" : ""}`} style={{ background: s }} aria-label={s} onClick={() => setHex(s)} />
        ))}
      </div>
      <div className="row">
        <input className="mono" value={hex} onChange={(e) => setHex(e.target.value.trim())} aria-label="Hex" maxLength={7} />
        <select value={material} onChange={(e) => setMaterial(e.target.value)} aria-label="Material">
          {MATERIALS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <button type="button" className="btn primary sm" disabled={!valid} onClick={() => send(hex)}>
          Apply
        </button>
      </div>
    </div>
  );
}

/** C21 ResizePanel: enclosure params, sends on release. */
export function ResizePanel() {
  const build = useApp((s) => s.build);
  const target = useApp((s) => s.resizeTarget);
  const enc = build?.enclosures.find((e) => e.enclosure_id === target?.enclosure_id) ?? build?.enclosures.find((e) => e.kind !== "none");
  const [vals, setVals] = useState<Record<string, number>>({});
  const [split, setSplit] = useState<string>(enc?.params.split ?? "lid_top");
  const [colorOpen, setColorOpen] = useState(false);
  useEffect(() => {
    setVals({});
    setSplit(enc?.params.split ?? "lid_top");
  }, [enc?.enclosure_id, enc?.revision, enc?.params.split]);
  if (!enc) {
    return (
      <aside className="side-overlay" aria-label="Resize">
        <SideHead title="Case" />
        <div className="side-b">
          <Empty>No generated case in this build.</Empty>
        </div>
      </aside>
    );
  }
  const sliders: { key: string; label: string; min: number; max: number; step: number; value: number }[] = [
    { key: "wall_mm", label: "Wall", min: 1.2, max: 5, step: 0.1, value: enc.params.wall_mm ?? 2 },
    { key: "fillet_mm", label: "Fillet", min: 0, max: 8, step: 0.5, value: enc.params.fillet_mm ?? 1 },
    { key: "clearance_mm", label: "Clearance", min: 0.2, max: 3, step: 0.1, value: enc.params.clearance_mm ?? 0.5 },
    { key: "height_mm", label: "Height", min: 5, max: 60, step: 0.5, value: enc.params.height_mm ?? enc.outer_size_mm?.[2] ?? 12 },
  ];
  const send = (params: Record<string, unknown>, label: string) => applyEdit([{ op: "resize", target: { enclosure_id: enc.enclosure_id }, params }], label);
  return (
    <aside className="side-overlay" aria-label="Resize">
      <SideHead title="Case" sub={enc.enclosure_id} />
      <div className="side-b">
        {sliders.map((s) => {
          const v = vals[s.key] ?? s.value;
          return (
            <label key={s.key} className="slider">
              <span>{s.label}</span>
              <input
                type="range"
                min={s.min}
                max={s.max}
                step={s.step}
                value={v}
                onChange={(e) => setVals((o) => ({ ...o, [s.key]: Number(e.target.value) }))}
                onPointerUp={() => vals[s.key] !== undefined && send({ [s.key]: vals[s.key] }, `${s.label} ${vals[s.key]} mm`)}
                onKeyUp={() => vals[s.key] !== undefined && send({ [s.key]: vals[s.key] }, `${s.label} ${vals[s.key]} mm`)}
              />
              <span className="mono small">{v.toFixed(1)} mm</span>
            </label>
          );
        })}
        <label className="slider">
          <span>Split</span>
          <select
            value={split}
            onChange={(e) => {
              setSplit(e.target.value);
              send({ split: e.target.value }, `Split ${e.target.value}`);
            }}
          >
            {["none", "lid_top", "tray", "halves"].map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn sm" onClick={() => setColorOpen((o) => !o)}>
          Case color
        </button>
        {colorOpen && <ColorPicker target={{ enclosure_id: enc.enclosure_id }} current={enc.color ?? null} onClose={() => setColorOpen(false)} />}
      </div>
    </aside>
  );
}

function Modal(props: { title: string; children: React.ReactNode }) {
  return (
    <div className="modal-scrim" onMouseDown={(e) => e.target === e.currentTarget && closeOverlay()}>
      <div className="modal" role="dialog" aria-label={props.title}>
        <header className="side-h">
          <div className="side-title">
            <h2>{props.title}</h2>
          </div>
          <button type="button" className="btn ghost sm icon" aria-label="Close" onClick={closeOverlay}>
            <Icon name="x" />
          </button>
        </header>
        <div className="side-b">{props.children}</div>
      </div>
    </div>
  );
}

function PortPicker(props: { label: string; value: PortRef | null; onChange: (p: PortRef | null) => void }) {
  const parts = useApp((s) => s.build?.parts ?? []);
  const [inst, setInst] = useState<string>(props.value?.instance_id ?? "");
  const part = usePart(parts.find((p) => p.instance_id === inst)?.part_id ?? null);
  const ifaces = part && part !== "loading" ? part.interfaces : [];
  return (
    <fieldset className="port-picker">
      <legend>{props.label}</legend>
      <select
        value={inst}
        onChange={(e) => {
          setInst(e.target.value);
          props.onChange(null);
        }}
        aria-label={`${props.label} part`}
      >
        <option value="">Choose a part</option>
        {parts.map((p) => (
          <option key={p.instance_id} value={p.instance_id}>
            {p.label ?? p.card.display_name} ({p.instance_id})
          </option>
        ))}
      </select>
      {inst &&
        (part === "loading" ? (
          <Skeleton lines={1} />
        ) : ifaces.length ? (
          <select
            value={props.value?.interface_id ?? ""}
            onChange={(e) => props.onChange(e.target.value ? { instance_id: inst, interface_id: e.target.value } : null)}
            aria-label={`${props.label} port`}
          >
            <option value="">Choose a port</option>
            {ifaces.map((i) => (
              <option key={i.id} value={i.id}>
                {i.id} ({i.type}, {i.role})
              </option>
            ))}
          </select>
        ) : (
          <input
            placeholder="interface id"
            value={props.value?.interface_id ?? ""}
            onChange={(e) => props.onChange(e.target.value ? { instance_id: inst, interface_id: e.target.value } : null)}
            aria-label={`${props.label} port`}
          />
        ))}
    </fieldset>
  );
}

/** C23 ConnectDialog. */
export function ConnectDialog() {
  const selection = useApp((s) => s.selection);
  const edit = useApp((s) => s.view.edit);
  const [from, setFrom] = useState<PortRef | null>(selection ? null : null);
  const [to, setTo] = useState<PortRef | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const mine = edit && sent === edit.msg_id ? edit : null;
  useEffect(() => {
    if (mine?.phase === "applied") closeOverlay();
  }, [mine?.phase]);
  return (
    <Modal title="Connect">
      <PortPicker label="From" value={from} onChange={setFrom} />
      <PortPicker label="To" value={to} onChange={setTo} />
      {mine?.phase === "rejected" && <p className="tone-text-fail small">{mine.error?.message ?? "Rejected"}</p>}
      <div className="modal-actions">
        <button type="button" className="btn ghost sm" onClick={closeOverlay}>
          Cancel
        </button>
        <button
          type="button"
          className="btn primary sm"
          disabled={!from || !to || mine?.phase === "pending" || mine?.phase === "applying"}
          onClick={() => {
            if (!from || !to) return;
            applyEdit([{ op: "connect", from, to }], `Connect ${from.instance_id} to ${to.instance_id}`);
            setSent(useApp.getState().view.edit?.msg_id ?? null);
          }}
        >
          Connect
        </button>
      </div>
    </Modal>
  );
}

/** C28 AddPartPicker. */
export function AddPartPicker() {
  const slots = useApp((s) => s.build?.slots ?? []);
  const edit = useApp((s) => s.view.edit);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [slot, setSlot] = useState<string>("");
  const [sent, setSent] = useState<string | null>(null);
  useEffect(() => {
    const h = setTimeout(() => setQuery(q.trim()), 250);
    return () => clearTimeout(h);
  }, [q]);
  const res = useRest<PartsPage>(paths.parts(query), (b) => b as PartsPage);
  const mine = edit && sent === edit.msg_id ? edit : null;
  useEffect(() => {
    if (mine?.phase === "applied") closeOverlay();
  }, [mine?.phase]);
  return (
    <Modal title="Add part">
      <input className="search" autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the catalog" aria-label="Search parts" />
      <label className="slider">
        <span>Slot</span>
        <select value={slot} onChange={(e) => setSlot(e.target.value)}>
          <option value="">New slot</option>
          {slots.map((s) => (
            <option key={s.slot_id} value={s.slot_id}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      {mine?.phase === "rejected" && <p className="tone-text-fail small">{mine.error?.message ?? "Rejected"}</p>}
      {res === null || res.state === "loading" ? (
        <Skeleton lines={4} />
      ) : res.state === "error" ? (
        <Empty>{res.message}</Empty>
      ) : res.data.items.length === 0 ? (
        <Empty>No parts match.</Empty>
      ) : (
        <ul className="alts">
          {res.data.items.map((c) => (
            <li key={c.part_id} className="alt">
              <button
                type="button"
                className="alt-btn"
                disabled={mine?.phase === "pending" || mine?.phase === "applying"}
                onClick={() => {
                  applyEdit([{ op: "add_part", part_id: c.part_id, slot_id: slot || null, quantity: 1 }], `Add ${c.display_name}`);
                  setSent(useApp.getState().view.edit?.msg_id ?? null);
                }}
              >
                <span className="alt-name">
                  <strong>{c.display_name}</strong>
                  <span className="muted small mono">{c.part_id}</span>
                </span>
                <ProvenanceBadge card={c} />
                {c.summary && <span className="small muted">{c.summary}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
