// A product shot of one saved build (?shot=<build_id>): the device alone on a transparent canvas, filling
// the window. scripts/render-shots.mjs opens this for every build in the library and keeps the picture.
// window.__shot says when it is worth taking: the build has loaded and no model has landed for a while.
import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { openLibraryBuild } from "../net/client";
import { useApp } from "../state/store";
import { DeviceScene } from "../three/Viewport3D";
import { onModelsChanged } from "../three/assets";

declare global {
  interface Window {
    __shot?: "loading" | "ready" | "failed";
  }
}

/** Quiet this long after the last model landed counts as fully drawn. */
const SETTLE_MS = 2500;

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
    let t = window.setTimeout(() => (window.__shot = "ready"), SETTLE_MS);
    const off = onModelsChanged(() => {
      window.__shot = "loading";
      window.clearTimeout(t);
      t = window.setTimeout(() => (window.__shot = "ready"), SETTLE_MS);
    });
    return () => {
      off();
      window.clearTimeout(t);
    };
  }, [loaded]);
  const scene = useMemo(() => <DeviceScene />, []);
  if (!loaded || !hasBuild) return null;
  return (
    <div className="shot-stage">
      <Canvas dpr={2} frameloop="always" camera={{ up: [0, 0, 1], position: [-120, -380, 260], near: 1, far: 10000, fov: 32 }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}>
        {scene}
      </Canvas>
    </div>
  );
}
