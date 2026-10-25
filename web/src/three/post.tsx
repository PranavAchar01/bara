// Studio post-processing and on-demand rendering. Ambient occlusion (N8AO,
// screen space, sized in build millimetres) grounds parts in each other:
// switches in plates, caps over switches, boards in cases. SMAA replaces
// MSAA, which fights the AO pass at edges. Tone mapping moves from the
// renderer into the composer's last pass. The canvas renders on demand:
// store changes, model loads, the explode ease and camera moves ask for
// frames, so an idle viewport costs nothing however heavy the AO is.
import { useEffect } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { EffectComposer, N8AO, SMAA, ToneMapping } from "@react-three/postprocessing";
import { ToneMappingMode } from "postprocessing";
import { useApp } from "../state/store";
import { onModelsChanged } from "./assets";
import { stage } from "./stage";

/** `?post=0` turns the pass off, for comparison and for weak GPUs. */
export function postEnabled(): boolean {
  return new URLSearchParams(window.location.search).get("post") !== "0";
}

export function StudioPost(props: { dark: boolean }) {
  // In focus the shelf shrinks parts below the AO radius, which smeared them dark: lighter and tighter then.
  const focused = useApp((s) => s.focusKey !== null);
  const intensity = (props.dark ? 2.2 : 2.6) * (focused ? 0.45 : 1);
  return (
    <EffectComposer multisampling={0} enableNormalPass={false}>
      {/* Radius in mm: about a key gap, so crevices darken and open faces stay clean. */}
      <N8AO aoRadius={focused ? 2 : 5} distanceFalloff={1.2} intensity={intensity} quality="high" color="black" />
      <SMAA />
      <ToneMapping mode={ToneMappingMode.NEUTRAL} />
    </EffectComposer>
  );
}

/**
 * Asks for frames while anything moves. R3F already invalidates on React
 * changes, controls and resize; this covers what changes imperatively.
 */
export function DemandDriver() {
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => useApp.subscribe(() => invalidate()), [invalidate]);
  useEffect(() => onModelsChanged(() => invalidate()), [invalidate]);
  useFrame(() => {
    if (stage.moving || stage.animating || Math.abs(useApp.getState().explode - stage.explode) > 0.0015) invalidate();
  });
  return null;
}
