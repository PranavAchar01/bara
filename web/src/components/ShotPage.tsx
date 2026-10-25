// A product shot of one saved build (?shot=<build_id>): the device alone on a transparent canvas, filling
// the window. Once it is fully drawn (no model has landed for a while) it crops itself and leaves the WebP
// in window.__shotData, with window.__shot = "shot". library/shots.ts (a hidden frame, when a build finishes)
// and scripts/render-shots.mjs (older builds) take it from there.
import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { openLibraryBuild } from "../net/client";
import { useApp } from "../state/store";
import { DeviceScene } from "../three/Viewport3D";
import { onModelsChanged } from "../three/assets";
import { cropShot, SHOT_DPR } from "../library/shots";

declare global {
  interface Window {
    __shot?: "loading" | "shot" | "failed";
    __shotData?: string | null;
  }
}

/** Quiet this long after the last model landed counts as fully drawn. */
const SETTLE_MS = 2500;
/** A build whose models never stop arriving (one keeps retrying) is shot as it stands after this long. */
const DEADLINE_MS = 60_000;

export function ShotPage(props: { buildId: string }) {
  const [loaded, setLoaded] = useState(false);
  const hasBuild = useApp((s) => s.build?.build_id === props.buildId);
  useEffect(() => {
    window.__shot = "loading";
    document.documentElement.classList.add("shot-page");
    void openLibraryBuild(props.buildId).then((ok) => {
      if (!ok) {
        window.__shot = "failed";
        return;
      }
      // just the device: no labels, nothing pulled apart, the hero angle
      useApp.setState((s) => ({ toggles: { ...s.toggles, labels: false, case: true, board: true, keycaps: true }, explode: 0, preset: "iso" }));
      setLoaded(true);
    });
  }, [props.buildId]);
  useEffect(() => {
    if (!loaded) return;
    const take = () => {
      const canvas = document.querySelector<HTMLCanvasElement>(".shot-stage canvas");
      window.__shotData = canvas ? cropShot(canvas) : null;
      window.__shot = window.__shotData ? "shot" : "failed";
    };
    let t = window.setTimeout(take, SETTLE_MS);
    const deadline = window.setTimeout(() => {
      off();
      window.clearTimeout(t);
      take();
    }, DEADLINE_MS);
    const off = onModelsChanged(() => {
      window.__shot = "loading";
      window.clearTimeout(t);
      t = window.setTimeout(take, SETTLE_MS);
    });
    return () => {
      off();
      window.clearTimeout(t);
      window.clearTimeout(deadline);
    };
  }, [loaded]);
  const scene = useMemo(() => <DeviceScene />, []);
  if (!loaded || !hasBuild) return null;
  return (
    <div className="shot-stage">
      <Canvas dpr={SHOT_DPR} frameloop="always" camera={{ up: [0, 0, 1], position: [-120, -380, 260], near: 1, far: 10000, fov: 32 }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: "high-performance" }}>
        {scene}
      </Canvas>
    </div>
  );
}
