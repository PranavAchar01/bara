// The other device of a combined device, run with the one being played: the screen of the display
// the macropad drives, showing what was typed and where the knob sits. It sits in the outputs dock,
// beside the terminal, because it is one more output of the same device.
import { useEffect, useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useApp } from "../state/store";
import { switchCanvas } from "../state/canvases";
import { boardDevices, useCombinedTitle } from "../project/scenes";
import { useProject } from "../project/project";
import { planCombined, type CombinedPlan, type ComboScreen } from "./combined";
import "./combined.css";

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** How the devices on the board are linked, in words: "a USB-C cable", "Bluetooth". */
function useLinkWords(canvasIds: string[]): string | null {
  const links = useProject((s) => s.links);
  return useMemo(() => {
    const l = links.find((x) => canvasIds.includes(x.a.canvasId) && canvasIds.includes(x.b.canvasId));
    if (!l) return null;
    if (l.medium === "wireless") return /ble|bluetooth/i.test(l.type) ? "Bluetooth" : `a ${l.type} radio link`;
    return `a ${l.type.replace(/_/g, "-").replace(/^usb-?c$/i, "USB-C").replace(/^usb$/i, "USB")} cable`;
  }, [links, canvasIds]);
}

/** The combined device the open build stands in, or null when it stands alone. */
export function useCombinedPlan(buildId: string): CombinedPlan | null {
  const key = useApp(useShallow((s) => boardDevices(s).map((d) => `${d.canvasId}:${d.name}:${d.build?.build_id ?? ""}:${d.build?.parts.length ?? 0}`)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const devices = useMemo(() => boardDevices(useApp.getState()), [key.join("|")]);
  const stored = useCombinedTitle(buildId);
  const link = useLinkWords(useMemo(() => devices.map((d) => d.canvasId), [devices]));
  return useMemo(() => {
    const first = planCombined("Combined device", devices, link);
    if (!first) return null;
    const title = stored ?? cap(first.devices.map((d) => d.noun).filter((n, i, a) => a.indexOf(n) === i).join(" with "));
    return planCombined(title, devices, link);
  }, [devices, stored, link]);
}

/**
 * The simulator runs the firmware of the device the person operates; when the board was opened on
 * another of its devices (the display), the session moves to that one.
 */
export function useRunTheSource(plan: CombinedPlan | null): void {
  const active = useApp((s) => s.activeCanvas);
  const source = plan ? plan.devices[plan.source].canvasId : null;
  useEffect(() => {
    if (source && source !== active) switchCanvas(source);
  }, [source, active]);
}

export function CombinedDisplay(props: { plan: CombinedPlan; screen: ComboScreen; powered: boolean }) {
  const { plan, screen } = props;
  const [blink, setBlink] = useState(0);
  useEffect(() => setBlink((n) => n + 1), [screen.presses, screen.level]);
  if (plan.display === null || plan.display === plan.source) return null;
  const dst = plan.devices[plan.display];
  const src = plan.devices[plan.source];
  const panel = dst.displays[0];
  return (
    <div className="combo" aria-label={`${cap(dst.noun)} screen`}>
      <div className="combo-head">
        <span>{cap(dst.noun)}</span>
        <span className="play-muted small">{panel ? panel.label : "screen"}, driven by the {src.noun}</span>
      </div>
      <div className={`combo-glass ${props.powered ? "on" : ""}`} key={blink}>
        <pre className="combo-text">
          {screen.text || (
            <span className="combo-hint">
              {screen.presses ? `No text from the ${src.noun}'s keys yet` : src.keys ? `Type on the ${src.noun}` : `Use the ${src.noun}`}
            </span>
          )}
          {props.powered && <span className="play-caret" aria-hidden />}
        </pre>
        {screen.level !== null && (
          <div className="combo-level" aria-label={`${screen.levelLabel} ${screen.level}%`}>
            <span>{screen.levelLabel}</span>
            <i>
              <b style={{ width: `${screen.level}%` }} />
            </i>
            <span className="mono">{screen.level}%</span>
          </div>
        )}
        {screen.last && <div className="combo-last mono">{screen.last}</div>}
      </div>
    </div>
  );
}
