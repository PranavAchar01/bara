// Operating view and display geometry for the simulation, both read from the build's geometry
// and part records.
import type { Build, BuildPart } from "../spec/types";

export interface OperatingView {
  /** Face of the case the controls are on: "pos_z" (up), "neg_y" (front), ... */
  face: string;
  /** Unit direction from the device toward the camera, build space (Z up, -Y is the front). */
  dir: [number, number, number];
}

const FACE_DIRS: Record<string, [number, number, number]> = {
  pos_z: [0, -0.0001, 1],
  neg_z: [0, -0.0001, -1],
  neg_y: [0, -1, 0.0001],
  pos_y: [0, 1, 0.0001],
  pos_x: [1, 0, 0.0001],
  neg_x: [-1, 0, 0.0001],
};

/** Case openings for things the user operates or reads; edge ports and vents say nothing about the control face. */
const CONTROL_FEATURES = /button|dpad|d_pad|key|switch|screen|display|window|knob|encoder|trackball|joystick/i;

/**
 * The face a person operates the device from, by the case's own cutouts: the face with the most
 * button, key, screen and knob openings. Without cutouts (a key plate has none) the controls face
 * up. A device whose controls face up is shown from straight above; one whose controls face the
 * front is shown straight on.
 */
export function operatingView(build: Build | null): OperatingView {
  const votes = new Map<string, number>();
  for (const enc of build?.enclosures ?? []) {
    for (const c of enc.cutouts ?? []) {
      if (!CONTROL_FEATURES.test(c.feature ?? "")) continue;
      votes.set(c.face, (votes.get(c.face) ?? 0) + 1);
    }
  }
  let face = "pos_z";
  let top = 0;
  for (const [f, n] of votes) {
    if (n > top && FACE_DIRS[f]) {
      face = f;
      top = n;
    }
  }
  return { face, dir: FACE_DIRS[face] };
}

export interface DisplaySpec {
  /** Pixel grid of the panel. */
  w: number;
  h: number;
  /** Diagonal in mm when the part names a size ("2.8 in"); null otherwise. */
  diagMm: number | null;
  mono: boolean;
}

/**
 * What a display part says about itself: its resolution ("128x32"), its size in inches ("2.8 in")
 * and whether it is monochrome (an OLED). Anything unstated is a 4:3 colour panel.
 */
export function displaySpec(part: BuildPart): DisplaySpec {
  const text = `${part.label ?? ""} ${part.card.display_name} ${part.card.summary ?? ""}`;
  const res = /(\d{2,4})\s*[x×]\s*(\d{2,4})/i.exec(text);
  const inch = /(\d+(?:\.\d+)?)\s*(?:in\b|inch|")/i.exec(text);
  const mono = /oled/i.test(part.card.primary_function ?? "") || /oled|monochrome|mono\b/i.test(text);
  const w = res ? Number(res[1]) : 160;
  const h = res ? Number(res[2]) : 120;
  return { w, h, diagMm: inch ? Number(inch[1]) * 25.4 : null, mono };
}

/**
 * Size in mm of the live picture on a display part whose top face is `face` (mm). A part that is
 * far smaller than the size it names (a driver chip named for the 2.8 in panel it drives) shows
 * the picture at the named size; otherwise the panel's aspect is fitted inside the face.
 */
export function screenSizeMm(spec: DisplaySpec, face: [number, number]): [number, number] {
  const aspect = spec.w / spec.h;
  const faceDiag = Math.hypot(face[0], face[1]);
  if (spec.diagMm && faceDiag < spec.diagMm * 0.8) {
    const h = spec.diagMm / Math.sqrt(1 + aspect * aspect);
    return [h * aspect, h];
  }
  const fit = Math.min(face[0] / aspect, face[1]) * 0.9;
  return [fit * aspect, fit];
}
