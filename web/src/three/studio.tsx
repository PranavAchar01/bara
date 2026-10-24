// Studio look (render recipe 2.1-2.4): neutral tone mapping, a PMREM room
// environment for reflections, one key light, an off-white floor with a light
// blue millimetre grid and a baked contact shadow. Ambient occlusion lives in
// post.tsx (N8AO), so parts sit on the board instead of floating. The studio
// stays light in dark mode: it is a photo backdrop, not page chrome. Shadows
// re-bake only when the scene settles, never per frame.
import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { ContactShadows } from "@react-three/drei";
import { useApp } from "../state/store";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { onModelsChanged } from "./assets";
import { stage, stageBox } from "./stage";

export interface StudioPalette {
  background: string;
  shadow: string;
  grid: string;
  gridMajor: string;
  gridText: string;
  gridFill: string;
}

export function studioPalette(): StudioPalette {
  return {
    background: "#F3F4F6",
    shadow: "#1B2433",
    grid: "rgba(110,165,220,0.28)",
    gridMajor: "rgba(80,145,212,0.55)",
    gridText: "rgba(62,128,196,0.95)",
    gridFill: "rgba(196,226,248,0.55)",
  };
}

/** Renderer, environment, key light and background. */
export function StudioEnvironment(props: { palette: StudioPalette; post: boolean }) {
  const { gl, scene } = useThree();
  const post = props.post;
  useEffect(() => {
    // With the post pass on, its last effect tone maps; mapping here too would apply it twice.
    gl.toneMapping = post ? THREE.NoToneMapping : THREE.NeutralToneMapping;
    gl.toneMappingExposure = 1.0;
    gl.outputColorSpace = THREE.SRGBColorSpace;
    gl.shadowMap.enabled = false;
    const pmrem = new THREE.PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const env = pmrem.fromScene(room, 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = 0.9;
    room.dispose();
    pmrem.dispose();
    return () => {
      scene.environment = null;
      env.dispose();
    };
  }, [gl, scene, post]);
  useEffect(() => {
    scene.background = new THREE.Color(props.palette.background);
  }, [scene, props.palette.background]);
  const key = useMemo(() => {
    const l = new THREE.DirectionalLight(0xffffff, 1.1);
    l.position.set(-0.5, -0.6, 1).multiplyScalar(500);
    return l;
  }, []);
  const fill = useMemo(() => new THREE.DirectionalLight(0xffffff, 0.35), []);
  fill.position.set(0.7, 0.4, 0.6).multiplyScalar(500);
  return (
    <>
      <primitive object={key} />
      <primitive object={fill} />
    </>
  );
}

interface Footing {
  center: THREE.Vector3;
  size: THREE.Vector3;
  floorZ: number;
}

function measure(): Footing | null {
  const box = stageBox();
  if (!box) return null;
  return { center: box.getCenter(new THREE.Vector3()), size: box.getSize(new THREE.Vector3()), floorZ: box.min.z };
}

/** Grid plate: a rectangle (multiples of 10 mm) around the model footprint, plus a band for the axis numbers. */
export function gridExtent(size: { x: number; y: number }, center: { x: number; y: number }) {
  const pad = Math.max(20, Math.max(size.x, size.y) * 0.22);
  const w = Math.ceil((Math.max(size.x, 40) + 2 * pad) / 10) * 10;
  const h = Math.ceil((Math.max(size.y, 40) + 2 * pad) / 10) * 10;
  const x0 = Math.floor((center.x - w / 2) / 10) * 10;
  const y0 = Math.floor((center.y - h / 2) / 10) * 10;
  return { x0, y0, w, h, band: Math.max(8, Math.max(w, h) * 0.05) };
}

/**
 * Light blue millimetre plate: tinted fill, 1 mm minor and 10 mm major lines,
 * a darker rim, and axis numbers every 10 mm along the left and front edges.
 */
function gridTexture(g: ReturnType<typeof gridExtent>, palette: StudioPalette): THREE.CanvasTexture {
  const totalW = g.w + g.band * 2;
  const totalH = g.h + g.band * 2;
  const ppm = Math.min(12, 4096 / Math.max(totalW, totalH));
  const pw = Math.round(totalW * ppm);
  const ph = Math.round(totalH * ppm);
  const canvas = document.createElement("canvas");
  canvas.width = pw;
  canvas.height = ph;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const toX = (mm: number) => (mm - g.x0 + g.band) * ppm;
  const toY = (mm: number) => ph - (mm - g.y0 + g.band) * ppm;
  const L = toX(g.x0);
  const R = toX(g.x0 + g.w);
  const T = toY(g.y0 + g.h);
  const B = toY(g.y0);
  ctx.fillStyle = palette.gridFill;
  ctx.fillRect(L, T, R - L, B - T);
  const lines = (step: number, color: string, width: number) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    for (let mm = g.x0; mm <= g.x0 + g.w + 1e-6; mm += step) {
      ctx.moveTo(toX(mm), T);
      ctx.lineTo(toX(mm), B);
    }
    for (let mm = g.y0; mm <= g.y0 + g.h + 1e-6; mm += step) {
      ctx.moveTo(L, toY(mm));
      ctx.lineTo(R, toY(mm));
    }
    ctx.stroke();
  };
  if (ppm >= 4) lines(1, palette.grid, Math.max(0.6, ppm * 0.08));
  lines(10, palette.gridMajor, Math.max(1, ppm * 0.16));
  ctx.strokeStyle = palette.gridText;
  ctx.lineWidth = Math.max(1.5, ppm * 0.3);
  ctx.strokeRect(L, T, R - L, B - T);
  ctx.fillStyle = palette.gridText;
  ctx.font = `500 ${Math.round(ppm * Math.min(3, g.band * 0.35))}px ui-sans-serif, system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let mm = g.x0; mm <= g.x0 + g.w + 1e-6; mm += 10) ctx.fillText(String(mm), toX(mm), B + ppm * 1.5);
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let mm = g.y0; mm <= g.y0 + g.h + 1e-6; mm += 10) ctx.fillText(String(mm), L - ppm * 1.5, toY(mm));
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 16;
  tex.generateMipmaps = true;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  return tex;
}

/**
 * Floor: grid plus a contact shadow baked under the parts. Both refresh when
 * models load, the build changes, or the explode settles.
 */
export function StudioFloor(props: { palette: StudioPalette; revision: string; grid: boolean }) {
  const [footing, setFooting] = useState<Footing | null>(null);
  const [version, setVersion] = useState(0);
  const settleSeen = useRef(stage.settleVersion);
  useEffect(() => onModelsChanged(() => setVersion((v) => v + 1)), []);
  useEffect(() => {
    // Measure after the parts committed their instance matrices.
    const id = requestAnimationFrame(() => setFooting(measure()));
    return () => cancelAnimationFrame(id);
  }, [version, props.revision]);
  useFrame(() => {
    if (settleSeen.current !== stage.settleVersion) {
      settleSeen.current = stage.settleVersion;
      setFooting(measure());
      setVersion((v) => v + 1);
    }
  });
  const z = (footing?.floorZ ?? 0) - 0.05;
  const size = footing?.size ?? new THREE.Vector3(200, 200, 30);
  const center = footing?.center ?? new THREE.Vector3();
  const g = gridExtent(size, center);
  const tex = useMemo(
    () => (props.grid ? gridTexture({ x0: g.x0, y0: g.y0, w: g.w, h: g.h, band: g.band }, props.palette) : null),
    [props.grid, g.x0, g.y0, g.w, g.h, g.band, props.palette],
  );
  useEffect(() => () => tex?.dispose(), [tex]);
  const span = Math.max(size.x, size.y, 120);
  // A part in focus floats free of the build; the floor and its shadow belong to the build.
  const focused = useApp((s) => s.focusKey !== null);
  return (
    <group visible={!focused}>
      {tex && (
        <mesh position={[g.x0 + g.w / 2, g.y0 + g.h / 2, z - 0.15]} raycast={() => null} renderOrder={-2}>
          <planeGeometry args={[g.w + 2 * g.band, g.h + 2 * g.band]} />
          <meshBasicMaterial map={tex} transparent depthWrite={false} toneMapped={false} />
        </mesh>
      )}
      {/* ContactShadows looks along +Y; rotate so its up axis is build-space +Z. */}
      <group position={[center.x, center.y, z]} rotation={[Math.PI / 2, 0, 0]}>
        <ContactShadows
          key={`${version}:${props.revision}`}
          frames={1}
          scale={span * 1.9}
          far={Math.max(25, size.z * 0.9)}
          blur={2.6}
          opacity={0.5}
          resolution={1024}
          color={props.palette.shadow}
        />
      </group>
    </group>
  );
}
