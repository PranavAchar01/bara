// Shell colours: the body, the trim around the screen, the main buttons, the action
// buttons and the screen tint. A few swatches per role plus any colour; a pick is sent
// as one palette edit and the engine redoes the finish from it, so it is saved with the build.
import { useEffect, useState } from "react";
import { useApp } from "../state/store";
import { applyEdit } from "../net/client";
import type { ShellPalette } from "../spec/types";
import { DEFAULT_SHELL, useShellView } from "../three/caseFinish";

const ROLES: { key: keyof ShellPalette; label: string; swatches: string[] }[] = [
  { key: "body", label: "Body", swatches: ["#E9E6DC", "#CFCBC0", "#8E9AA6", "#2B2D31", "#C2362F", "#2F55D4", "#E3B23C", "#3E8E63"] },
  { key: "trim", label: "Trim", swatches: ["#F2F2EE", "#9E9E9E", "#4A4D55", "#202326", "#7A4A2B", "#2F55D4"] },
  { key: "buttons", label: "Buttons", swatches: ["#F2F2EE", "#9E9E9E", "#23252A", "#2F55D4", "#3E8E63", "#E3B23C"] },
  { key: "accent", label: "Accent", swatches: ["#A8325E", "#C2362F", "#E4572E", "#E3B23C", "#2FA3C7", "#F2F2EE"] },
  { key: "screen", label: "Screen", swatches: ["#B7D39A", "#9CC7FF", "#E8EDF2", "#F2B134", "#14171A"] },
];


export function ShellColors() {
  const saved = useApp((s) => s.build?.scene?.finish?.palette);
  const clear = useShellView((s) => s.clear);
  const [draft, setDraft] = useState<Partial<ShellPalette>>({});
  useEffect(() => setDraft({}), [saved]);
  const value = (k: keyof ShellPalette) => (draft[k] ?? saved?.[k] ?? DEFAULT_SHELL[k]).toUpperCase();
  const send = (k: keyof ShellPalette, hex: string) => {
    const h = hex.toUpperCase();
    setDraft((d) => ({ ...d, [k]: h }));
    useShellView.setState({ clear: false });
    applyEdit([{ op: "palette", palette: { [k]: h } }], `Shell ${k} ${h}`);
  };
  return (
    <div className="shell-colors" role="group" aria-label="Shell colours">
      <div className="shell-colors-head">
        <span className="small">Shell</span>
        <div className="seg">
          <button type="button" className={`seg-btn ${clear ? "active" : ""}`} aria-pressed={clear} onClick={() => useShellView.setState({ clear: true })}>
            clear
          </button>
          <button type="button" className={`seg-btn ${clear ? "" : "active"}`} aria-pressed={!clear} onClick={() => useShellView.setState({ clear: false })}>
            colour
          </button>
        </div>
      </div>
      {ROLES.map((r) => (
        <div key={r.key} className="shell-colors-row">
          <span className="shell-colors-label">{r.label}</span>
          <div className="swatches">
            {r.swatches.map((hex) => (
              <button
                key={hex}
                type="button"
                className={`swatch ${value(r.key) === hex ? "active" : ""}`}
                style={{ background: hex }}
                aria-label={`${r.label} ${hex}`}
                onClick={() => send(r.key, hex)}
              />
            ))}
            <label className="tint-custom" title="Any colour">
              <input
                type="color"
                value={value(r.key).toLowerCase()}
                onChange={(e) => setDraft((d) => ({ ...d, [r.key]: e.target.value.toUpperCase() }))}
                onBlur={(e) => e.target.value.toUpperCase() !== (saved?.[r.key] ?? "").toUpperCase() && send(r.key, e.target.value)}
                aria-label={`Custom ${r.label.toLowerCase()} colour`}
              />
            </label>
          </div>
        </div>
      ))}
    </div>
  );
}
