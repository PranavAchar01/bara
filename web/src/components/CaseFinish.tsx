// The case's material: what it is made of (finish chips, each a real printable
// or cut material), its tint, and how see-through and how frosted it is. Every
// change previews on the 3D case at once; chips and swatches send right away,
// sliders send when released, all as one recolor edit.
import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { applyEdit } from "../net/client";
import type { Color, Enclosure, Finish, FinishPreset } from "../spec/types";
import { FINISHES, finishInfo, finishSwatch, previewCase, resolveFinish } from "../three/caseFinish";

const TINTS = ["#F2F2EE", "#9E9E9E", "#202326", "#2F55D4", "#7FB5E6", "#C2362F", "#E9967A", "#2E7D4F", "#D9A043", "#6B4FA8"];

export function CaseFinishPicker(props: { enc: Enclosure }) {
  const { enc } = props;
  const saved = useRef<Color | null>(null);
  const [hex, setHex] = useState(enc.color?.hex ?? "#9E9E9E");
  const [finish, setFinish] = useState<Required<Finish>>(() => resolveFinish(enc.color?.finish));
  const editPhase = useApp((s) => s.view.edit?.phase);

  // A new revision from the engine (or a rejection) ends the preview.
  useEffect(() => {
    setHex(enc.color?.hex ?? "#9E9E9E");
    setFinish(resolveFinish(enc.color?.finish));
    previewCase(enc.enclosure_id, null);
  }, [enc.enclosure_id, enc.revision, enc.color?.hex, enc.color?.finish]);
  useEffect(() => {
    if (editPhase === "rejected") {
      previewCase(enc.enclosure_id, null);
      if (saved.current) {
        setHex(saved.current.hex);
        setFinish(resolveFinish(saved.current.finish));
      }
    }
  }, [editPhase, enc.enclosure_id]);
  useEffect(() => () => previewCase(enc.enclosure_id, null), [enc.enclosure_id]);

  const colorOf = (h: string, f: Required<Finish>): Color => {
    const info = finishInfo(f.preset);
    const out: Finish = { preset: f.preset, frost: round(f.frost) };
    if (info.seeThrough) out.clarity = round(f.clarity);
    return { hex: h.toUpperCase(), material: info.material, finish: out };
  };
  const show = (h: string, f: Required<Finish>) => {
    setHex(h);
    setFinish(f);
    previewCase(enc.enclosure_id, colorOf(h, f));
  };
  const send = (h: string, f: Required<Finish>, label: string) => {
    saved.current = enc.color ?? null;
    show(h, f);
    applyEdit([{ op: "recolor", enclosure_id: enc.enclosure_id, color: colorOf(h, f) }], label);
  };
  const pickFinish = (preset: FinishPreset) => {
    const info = finishInfo(preset);
    send(hex, { preset, clarity: info.clarity, frost: info.frost }, `Case ${info.label.toLowerCase()} ${info.makes}`);
  };
  const info = finishInfo(finish.preset);

  return (
    <section className="case-finish" aria-label="Case material">
      <h4 className="case-finish-h">Material</h4>
      <div className="finish-grid" role="radiogroup" aria-label="Finish">
        {FINISHES.map((f) => (
          <button
            key={f.preset}
            type="button"
            role="radio"
            aria-checked={finish.preset === f.preset}
            className={`finish-chip ${finish.preset === f.preset ? "active" : ""}`}
            onClick={() => pickFinish(f.preset)}
            title={f.makes}
          >
            <span className="finish-dot" style={{ background: finishSwatch(hex, f.preset) }} />
            <span className="finish-name">{f.label}</span>
            <span className="finish-makes">{f.makes}</span>
          </button>
        ))}
      </div>

      <h4 className="case-finish-h">Tint</h4>
      <div className="tint-row">
        {TINTS.map((t) => (
          <button
            key={t}
            type="button"
            className={`swatch ${hex.toUpperCase() === t ? "active" : ""}`}
            style={{ background: finishSwatch(t, finish.preset) }}
            aria-label={`Tint ${t}`}
            onClick={() => send(t, finish, `Case tint ${t}`)}
          />
        ))}
        <label className="tint-custom" title="Any colour">
          <input type="color" value={hex} onChange={(e) => show(e.target.value, finish)} onBlur={(e) => send(e.target.value, finish, `Case tint ${e.target.value.toUpperCase()}`)} aria-label="Custom tint" />
        </label>
      </div>

      {info.seeThrough && (
        <FinishSlider
          label="Clarity"
          hint={["Opaque", "Clear"]}
          value={finish.clarity}
          onChange={(v) => show(hex, { ...finish, clarity: v })}
          onCommit={(v) => send(hex, { ...finish, clarity: v }, `Case clarity ${Math.round(v * 100)}%`)}
        />
      )}
      <FinishSlider
        label={info.seeThrough ? "Frost" : "Roughness"}
        hint={info.seeThrough ? ["Polished", "Frosted"] : ["Shiny", "Matte"]}
        value={finish.frost}
        onChange={(v) => show(hex, { ...finish, frost: v })}
        onCommit={(v) => send(hex, { ...finish, frost: v }, `Case ${info.seeThrough ? "frost" : "roughness"} ${Math.round(v * 100)}%`)}
      />
    </section>
  );
}

function FinishSlider(props: { label: string; hint: [string, string]; value: number; onChange: (v: number) => void; onCommit: (v: number) => void }) {
  const [v, setV] = useState(props.value);
  useEffect(() => setV(props.value), [props.value]);
  return (
    <label className="slider finish-slider">
      <span>{props.label}</span>
      <input
        type="range"
        min={0}
        max={1}
        step={0.02}
        value={v}
        onChange={(e) => {
          const n = Number(e.target.value);
          setV(n);
          props.onChange(n);
        }}
        onPointerUp={() => props.onCommit(v)}
        onKeyUp={() => props.onCommit(v)}
        aria-valuetext={`${Math.round(v * 100)}%`}
      />
      <span className="mono small finish-hint">{v < 0.5 ? props.hint[0] : props.hint[1]}</span>
    </label>
  );
}

const round = (v: number) => Math.round(v * 100) / 100;
