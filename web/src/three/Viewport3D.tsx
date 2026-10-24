// C10 Viewport3D: build space is Z up, mm (SPEC 3.2). Arrayed parts use one
// instanced mesh per instance (SPEC 3.3). Missing assets render as translucent
// boxes with a label; failing checks get a red hull outline.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Edges, Html, OrbitControls, TransformControls } from "@react-three/drei";
import * as THREE from "three";
import { select, useApp, type ViewPreset } from "../state/store";
import { applyEdit } from "../net/client";
import { fetchPart } from "../components/Overlays";
import type { BBox, Board, BuildPart, Enclosure, Layout } from "../spec/types";
import { failingByInstance } from "../ui/format";
import { modelAsset, useModel } from "./assets";
import { placeholderBox, type Box } from "./bbox";
import { addScaled, elementPoses, type ElementPose, type V3 } from "./layout";

const DEG = Math.PI / 180;

interface Theme {
  accent: string;
  fail: string;
  grid: string;
  grid2: string;
  text: string;
}

function readTheme(): Theme {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, d: string) => cs.getPropertyValue(n).trim() || d;
  return {
    accent: v("--accent", "#2f55d4"),
    fail: v("--fail", "#c2362f"),
    grid: v("--grid-line", "#d9d9d3"),
    grid2: v("--line-strong", "#c9c9c2"),
    text: v("--text", "#1b1d1f"),
  };
}

function useTheme(): Theme {
  const [t, setT] = useState<Theme>(readTheme);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setT(readTheme());
    mq.addEventListener("change", on);
    const obs = new MutationObserver(on);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      mq.removeEventListener("change", on);
      obs.disconnect();
    };
  }, []);
  return t;
}

/** Default colours by catalog prefix, used when a part has no colour of its own. */
function defaultColor(part: BuildPart): string {
  const id = part.part_id;
  if (part.color?.hex) return part.color.hex;
  if (id.startsWith("cap:")) return "#E9E7E1";
  if (id.startsWith("sw:")) return /brown/.test(id) ? "#7A5236" : /red/.test(id) ? "#B8423A" : "#3A3D40";
  if (String(part.card.kind) === "pcb") return "#2F6B4F";
  if (/plate/.test(id)) return "#8E949A";
  if (id.startsWith("mod:")) return "#24324F";
  if (id.startsWith("disp:")) return "#15171A";
  if (id.startsWith("bat:")) return "#B9A65A";
  if (id.startsWith("cable:")) return "#2A2C2E";
  return "#7E858C";
}

function isKeycap(p: BuildPart): boolean {
  return p.part_id.startsWith("cap:") || /keycap/.test(p.card.primary_function ?? "");
}

const catalogBoxes = new Map<string, BBox | null>();
function useCatalogBbox(partId: string): BBox | null {
  const [b, setB] = useState<BBox | null>(catalogBoxes.get(partId) ?? null);
  useEffect(() => {
    if (catalogBoxes.has(partId)) {
      setB(catalogBoxes.get(partId) ?? null);
      return;
    }
    let live = true;
    void fetchPart(partId).then((p) => {
      const box = p?.mechanical?.bbox_mm ?? null;
      catalogBoxes.set(partId, box);
      if (live) setB(box);
    });
    return () => {
      live = false;
    };
  }, [partId]);
  return b;
}

function boxGeometry(box: Box): THREE.BufferGeometry {
  const sx = Math.max(0.2, box.max[0] - box.min[0]);
  const sy = Math.max(0.2, box.max[1] - box.min[1]);
  const sz = Math.max(0.2, box.max[2] - box.min[2]);
  const g = new THREE.BoxGeometry(sx, sy, sz);
  g.translate((box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (box.min[2] + box.max[2]) / 2);
  return g;
}

/** Hull for the outline: the same geometry grown by `pad` mm on every axis about its centre. */
function hullGeometry(src: THREE.BufferGeometry, pad: number): THREE.BufferGeometry {
  const g = src.clone();
  g.computeBoundingBox();
  const bb = g.boundingBox as THREE.Box3;
  const c = bb.getCenter(new THREE.Vector3());
  const s = bb.getSize(new THREE.Vector3());
  g.translate(-c.x, -c.y, -c.z);
  g.scale((s.x + 2 * pad) / Math.max(s.x, 0.01), (s.y + 2 * pad) / Math.max(s.y, 0.01), (s.z + 2 * pad) / Math.max(s.z, 0.01));
  g.translate(c.x, c.y, c.z);
  return g;
}

function elementMatrix(pose: ElementPose, explode: number[] | undefined, factor: number): THREE.Matrix4 {
  const p = addScaled(pose.position, explode, factor);
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(pose.rotation[0] * DEG, pose.rotation[1] * DEG, pose.rotation[2] * DEG, "XYZ"));
  const yaw = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), pose.yaw * DEG);
  q.multiply(yaw);
  return new THREE.Matrix4().compose(new THREE.Vector3(p[0], p[1], p[2]), q, new THREE.Vector3(1, 1, 1));
}

interface PartNodeProps {
  part: BuildPart;
  layout: Layout | undefined;
  layouts: Layout[];
  boards: Board[];
  parts: BuildPart[];
  explode: number;
  provisional: boolean;
  selected: boolean;
  failing: boolean;
  highlight: boolean;
  labels: boolean;
  theme: Theme;
  pose: { position_mm: number[]; rotation_deg: number[] } | null;
}

function PartNode(props: PartNodeProps) {
  const { part, theme } = props;
  const pose = props.pose;
  const poses = useMemo(() => {
    const placement = pose ? { ...part.placement, position_mm: pose.position_mm, rotation_deg: pose.rotation_deg } : part.placement;
    return elementPoses(placement, part.quantity, props.layout);
  }, [pose, part.placement, part.quantity, props.layout]);
  const asset = modelAsset(part.assets, poses.length > 1);
  const model = useModel(asset?.url ?? null);
  const catalog = useCatalogBbox(part.part_id);
  const box = useMemo(
    () => placeholderBox(part, { layouts: props.layouts, boards: props.boards, parts: props.parts, catalogBbox: catalog }),
    [part, props.layouts, props.boards, props.parts, catalog],
  );
  const ready = model.status === "ready" && model.model.merged !== null;
  const geometry = useMemo(() => (ready && model.status === "ready" && model.model.merged ? model.model.merged : boxGeometry(box)), [ready, model, box]);
  const hull = useMemo(() => hullGeometry(geometry, String(part.card.kind) === "pcb" ? 1.2 : 0.8), [geometry, part.card.kind]);
  useEffect(
    () => () => {
      if (!ready) geometry.dispose();
      hull.dispose();
    },
    [geometry, hull, ready],
  );
  const matrices = useMemo(
    () => poses.map((p) => elementMatrix(p, part.placement.explode_offset_mm, props.explode)),
    [poses, part.placement.explode_offset_mm, props.explode],
  );
  const outline = props.failing ? theme.fail : props.selected || props.highlight ? theme.accent : null;
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const hullRef = useRef<THREE.InstancedMesh>(null);
  useLayoutEffect(() => {
    for (const ref of [meshRef.current, hullRef.current]) {
      if (!ref) continue;
      matrices.forEach((m, i) => ref.setMatrixAt(i, m));
      ref.instanceMatrix.needsUpdate = true;
      ref.computeBoundingSphere();
    }
  }, [matrices, geometry, outline]);
  const missing = !ready;
  const opacity = props.provisional ? 0.5 : missing ? 0.62 : 1;
  const transparent = opacity < 1;
  const color = defaultColor(part);
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    select(part.instance_id);
  };
  const anchor = useMemo(() => {
    const c = new THREE.Vector3();
    for (const m of matrices) c.add(new THREE.Vector3().setFromMatrixPosition(m));
    c.divideScalar(Math.max(1, matrices.length));
    c.z += box.max[2] + 2;
    return c;
  }, [matrices, box]);
  const key = `${matrices.length}:${geometry.uuid}`;
  return (
    <group>
      <instancedMesh
        key={`m${key}`}
        ref={meshRef}
        args={[geometry, undefined, matrices.length]}
        onClick={onClick}
        onPointerOver={(e) => {
          e.stopPropagation();
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          document.body.style.cursor = "";
        }}
        castShadow={false}
      >
        <meshStandardMaterial
          color={color}
          roughness={missing ? 0.85 : 0.55}
          metalness={0.05}
          transparent={transparent}
          opacity={opacity}
          depthWrite={!transparent}
          emissive={props.selected ? theme.accent : "#000000"}
          emissiveIntensity={props.selected ? 0.18 : 0}
        />
      </instancedMesh>
      {outline && (
        <instancedMesh key={`h${key}${outline}`} ref={hullRef} args={[hull, undefined, matrices.length]} raycast={() => null}>
          <meshBasicMaterial color={outline} side={THREE.BackSide} transparent opacity={0.95} depthWrite={false} />
        </instancedMesh>
      )}
      {(props.labels || props.selected) && (
        <Html position={anchor} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
          <span className={`vp-label ${missing ? "missing" : ""} ${props.failing ? "failing" : ""}`}>
            {part.label ?? part.card.display_name}
            {missing ? " (no model)" : ""}
          </span>
        </Html>
      )}
    </group>
  );
}

function EnclosureNode(props: { enc: Enclosure; explode: number; theme: Theme; selected: boolean; failing: boolean }) {
  const { enc, theme } = props;
  const asset = modelAsset(enc.assets, false);
  const model = useModel(asset?.url ?? null);
  const size = enc.outer_size_mm;
  const geometry = useMemo(() => {
    if (model.status === "ready" && model.model.merged) return model.model.merged;
    if (!size || size.length < 3) return null;
    return new THREE.BoxGeometry(Math.max(size[0], 0.5), Math.max(size[1], 0.5), Math.max(size[2], 0.5));
  }, [model, size]);
  if (!geometry || enc.kind === "none") return null;
  const pos = addScaled([enc.position_mm?.[0] ?? 0, enc.position_mm?.[1] ?? 0, enc.position_mm?.[2] ?? 0] as V3, enc.explode_offset_mm, props.explode);
  const rot = enc.rotation_deg ?? [0, 0, 0];
  const pending = enc.status === "pending";
  const color = enc.color?.hex ?? "#9E9E9E";
  const edge = props.failing ? theme.fail : props.selected ? theme.accent : color;
  return (
    <mesh
      geometry={geometry}
      position={pos}
      rotation={new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG, "XYZ")}
      onClick={(e) => {
        e.stopPropagation();
        useApp.setState({ resizeTarget: { enclosure_id: enc.enclosure_id }, overlay: "resize", selection: null });
      }}
    >
      <meshStandardMaterial color={color} wireframe={pending} transparent opacity={pending ? 0.6 : 0.3} depthWrite={false} roughness={0.8} />
      {!pending && <Edges color={edge} threshold={20} />}
    </mesh>
  );
}

/** A board without its own PCB part instance: extrude its outline. */
function BoardNode(props: { board: Board; theme: Theme }) {
  const { board } = props;
  const geometry = useMemo(() => {
    const pts: number[][] = board.outline_mm?.length
      ? board.outline_mm
      : board.size_mm
        ? [
            [0, 0],
            [board.size_mm[0], 0],
            [board.size_mm[0], -board.size_mm[1]],
            [0, -board.size_mm[1]],
          ]
        : [];
    if (pts.length < 3) return null;
    const shape = new THREE.Shape(pts.map((p) => new THREE.Vector2(p[0], p[1])));
    return new THREE.ExtrudeGeometry(shape, { depth: board.thickness_mm ?? 1.6, bevelEnabled: false });
  }, [board.outline_mm, board.size_mm, board.thickness_mm]);
  if (!geometry) return null;
  const pos = board.position_mm ?? [0, 0, 0];
  const rot = board.rotation_deg ?? [0, 0, 0];
  return (
    <mesh geometry={geometry} position={[pos[0], pos[1], pos[2]]} rotation={new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG, "XYZ")}>
      <meshStandardMaterial color="#2F6B4F" wireframe={board.status === "pending"} transparent opacity={0.85} />
    </mesh>
  );
}

function assemblyBox(): { center: THREE.Vector3; radius: number } {
  const b = useApp.getState().build;
  const bb = b?.scene?.assembly_bbox_mm;
  const box = new THREE.Box3();
  if (bb?.min && bb?.max) {
    box.set(new THREE.Vector3(bb.min[0], bb.min[1], bb.min[2]), new THREE.Vector3(bb.max[0], bb.max[1], bb.max[2]));
  } else {
    for (const p of b?.parts ?? []) {
      const v = p.placement.position_mm;
      box.expandByPoint(new THREE.Vector3(v[0], v[1], v[2]));
    }
    if (box.isEmpty()) box.set(new THREE.Vector3(-60, -40, 0), new THREE.Vector3(60, 40, 20));
    box.expandByScalar(40);
  }
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(40, box.getSize(new THREE.Vector3()).length() / 2);
  return { center, radius };
}

function presetPose(preset: ViewPreset, fovDeg: number): { pos: THREE.Vector3; target: THREE.Vector3 } {
  const scene = useApp.getState().build?.scene;
  if (preset === "scene" && scene?.camera) {
    const p = scene.camera.position_mm;
    const t = scene.camera.target_mm;
    return { pos: new THREE.Vector3(p[0], p[1], p[2]), target: new THREE.Vector3(t[0], t[1], t[2]) };
  }
  const { center, radius } = assemblyBox();
  const dist = radius / Math.sin((fovDeg * DEG) / 2) * 1.05;
  const dir =
    preset === "top"
      ? new THREE.Vector3(0, -0.0001, 1)
      : preset === "front"
        ? new THREE.Vector3(0, -1, 0.18)
        : preset === "side"
          ? new THREE.Vector3(1, 0, 0.18)
          : new THREE.Vector3(0.75, -1, 0.95);
  dir.normalize();
  return { pos: center.clone().addScaledVector(dir, dist), target: center };
}

interface OrbitLike {
  target: THREE.Vector3;
  update: () => void;
}

/** Eases the camera to scene.camera (or a preset) whenever it changes. */
function CameraRig() {
  const { camera, controls } = useThree();
  const preset = useApp((s) => s.preset);
  const nonce = useApp((s) => s.cameraNonce);
  const sceneCam = useApp((s) => s.build?.scene?.camera ?? null);
  const buildId = useApp((s) => s.build?.build_id ?? null);
  const partsCount = useApp((s) => s.build?.parts.length ?? 0);
  const anim = useRef<{ fromP: THREE.Vector3; fromT: THREE.Vector3; toP: THREE.Vector3; toT: THREE.Vector3; t: number } | null>(null);
  const framedFor = useRef<string | null>(null);
  const start = (p: ViewPreset) => {
    const ctl = controls as unknown as OrbitLike | null;
    const fov = (camera as THREE.PerspectiveCamera).fov ?? 35;
    const to = presetPose(p, fov);
    anim.current = {
      fromP: camera.position.clone(),
      fromT: ctl?.target.clone() ?? new THREE.Vector3(),
      toP: to.pos,
      toT: to.target,
      t: 0,
    };
  };
  useEffect(() => {
    if (sceneCam) start(preset === "scene" ? "scene" : preset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneCam]);
  useEffect(() => {
    start(preset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);
  useEffect(() => {
    // Frame the first parts of a new build before scene.ready arrives.
    if (!buildId || partsCount === 0 || framedFor.current === buildId) return;
    framedFor.current = buildId;
    if (!sceneCam) start("iso");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildId, partsCount]);
  useFrame((_, dt) => {
    const a = anim.current;
    const ctl = controls as unknown as OrbitLike | null;
    if (!a) return;
    a.t = Math.min(1, a.t + dt / 0.7);
    const k = 1 - Math.pow(1 - a.t, 3);
    camera.position.lerpVectors(a.fromP, a.toP, k);
    if (ctl) {
      ctl.target.lerpVectors(a.fromT, a.toT, k);
      ctl.update();
    } else camera.lookAt(a.toT);
    if (a.t >= 1) anim.current = null;
  });
  return null;
}

/** C20 MoveGizmo: drag locally, send one absolute move with lock on release. */
function MoveGizmo(props: { mode: "translate" | "rotate" }) {
  const moving = useApp((s) => s.moving);
  const part = useApp((s) => s.build?.parts.find((p) => p.instance_id === s.moving) ?? null);
  const done = useApp((s) => s.build?.status === "done");
  const obj = useMemo(() => new THREE.Group(), []);
  useEffect(() => {
    if (!part) return;
    const pose = useApp.getState().dragPose;
    const p = pose && pose.instance_id === part.instance_id ? pose : part.placement;
    obj.position.set(p.position_mm[0], p.position_mm[1], p.position_mm[2]);
    obj.rotation.set(p.rotation_deg[0] * DEG, p.rotation_deg[1] * DEG, p.rotation_deg[2] * DEG, "XYZ");
  }, [part, obj]);
  if (!moving || !part || !done) return null;
  const read = () => ({
    instance_id: part.instance_id,
    position_mm: [obj.position.x, obj.position.y, obj.position.z].map((n) => Math.round(n * 10) / 10),
    rotation_deg: [obj.rotation.x, obj.rotation.y, obj.rotation.z].map((r) => Math.round((r / DEG) * 10) / 10),
  });
  return (
    <>
      <primitive object={obj} />
      <TransformControls
        object={obj}
        mode={props.mode}
        size={0.8}
        onObjectChange={() => useApp.setState({ dragPose: read() })}
        onMouseUp={() => {
          const pose = read();
          useApp.setState({ dragPose: pose });
          applyEdit(
            [{ op: "move", instance_id: part.instance_id, position_mm: pose.position_mm, rotation_deg: pose.rotation_deg, mode: "absolute", lock: true }],
            `Move ${part.label ?? part.card.display_name}`,
          );
        }}
      />
    </>
  );
}

function SceneContents(props: { gizmoMode: "translate" | "rotate" }) {
  const build = useApp((s) => s.build);
  const placeDone = useApp((s) => s.view.placeDone);
  const selection = useApp((s) => s.selection);
  const resizeTarget = useApp((s) => s.resizeTarget);
  const overlay = useApp((s) => s.overlay);
  const hoverConn = useApp((s) => s.hoverConnection);
  const explode = useApp((s) => s.explode);
  const toggles = useApp((s) => s.toggles);
  const dragPose = useApp((s) => s.dragPose);
  const theme = useTheme();
  const failing = useMemo(() => failingByInstance(build), [build]);
  const failingEnclosures = useMemo(() => {
    const out = new Set<string>();
    for (const c of build?.checks ?? []) {
      if (c.status !== "fail") continue;
      for (const s of c.subjects ?? []) if (s.enclosure_id) out.add(s.enclosure_id);
    }
    return out;
  }, [build?.checks]);
  const hoverEnds = useMemo(() => {
    const c = build?.connections.find((x) => x.connection_id === hoverConn);
    return new Set(c ? [c.from.instance_id, c.to.instance_id] : []);
  }, [build?.connections, hoverConn]);
  const parts = build?.parts ?? [];
  const layouts = build?.layouts ?? [];
  const boards = build?.boards ?? [];
  const visible = parts.filter((p) => (toggles.keycaps || !isKeycap(p)) && (toggles.board || String(p.card.kind) !== "pcb"));
  return (
    <>
      <ambientLight intensity={0.75} />
      <directionalLight position={[200, -300, 500]} intensity={1.6} />
      <directionalLight position={[-300, 200, 200]} intensity={0.5} />
      <gridHelper args={[1000, 50, theme.grid2, theme.grid]} rotation={[Math.PI / 2, 0, 0]} position={[0, 0, -0.05]} />
      {visible.map((p) => (
        <PartNode
          key={p.instance_id}
          part={p}
          layout={layouts.find((l) => l.layout_id === p.placement.layout_id)}
          layouts={layouts}
          boards={boards}
          parts={parts}
          explode={explode}
          provisional={!placeDone}
          selected={selection === p.instance_id}
          failing={failing.has(p.instance_id)}
          highlight={hoverEnds.has(p.instance_id)}
          labels={toggles.labels}
          theme={theme}
          pose={dragPose && dragPose.instance_id === p.instance_id ? dragPose : null}
        />
      ))}
      {toggles.case &&
        (build?.enclosures ?? []).map((e) => (
          <EnclosureNode
            key={e.enclosure_id}
            enc={e}
            explode={explode}
            theme={theme}
            selected={overlay === "resize" && resizeTarget?.enclosure_id === e.enclosure_id}
            failing={failingEnclosures.has(e.enclosure_id)}
          />
        ))}
      {toggles.board && boards.filter((b) => !b.part_instance_id).map((b) => <BoardNode key={b.board_id} board={b} theme={theme} />)}
      <MoveGizmo mode={props.gizmoMode} />
      <CameraRig />
    </>
  );
}

export function Viewport3D() {
  const hasParts = useApp((s) => (s.build?.parts.length ?? 0) > 0);
  const status = useApp((s) => s.build?.status);
  const missingCount = useApp((s) => (s.build?.parts ?? []).filter((p) => !modelAsset(p.assets, p.quantity > 1)).length);
  const [gizmoMode, setGizmoMode] = useState<"translate" | "rotate">("translate");
  return (
    <div className="viewport">
      <Canvas
        dpr={[1, 2]}
        camera={{ up: [0, 0, 1], position: [180, -260, 220], near: 1, far: 10000, fov: 35 }}
        onPointerMissed={(e) => {
          if (e.type === "click") select(null);
        }}
        gl={{ antialias: true, preserveDrawingBuffer: true }}
      >
        <SceneContents gizmoMode={gizmoMode} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
      </Canvas>
      {!hasParts && (
        <div className="vp-empty">
          {status === "running" || status === "awaiting_input" ? "Parts appear here as they are chosen." : status === "failed" ? "No parts were placed." : "Describe a device to start."}
        </div>
      )}
      {hasParts && missingCount > 0 && (
        <div className="vp-note small" title="These parts have no 3D model on the server, so they are drawn as boxes sized from the catalog.">
          {missingCount} of the parts drawn as boxes (no model)
        </div>
      )}
      <ViewportToolbar gizmoMode={gizmoMode} setGizmoMode={setGizmoMode} />
    </div>
  );
}

/** C11 ViewportToolbar. */
function ViewportToolbar(props: { gizmoMode: "translate" | "rotate"; setGizmoMode: (m: "translate" | "rotate") => void }) {
  const explode = useApp((s) => s.explode);
  const toggles = useApp((s) => s.toggles);
  const preset = useApp((s) => s.preset);
  const moving = useApp((s) => s.moving);
  const hasScene = useApp((s) => !!s.build?.scene);
  const setPreset = (p: ViewPreset) => useApp.setState((s) => ({ preset: p, cameraNonce: s.cameraNonce + 1 }));
  const toggle = (k: keyof typeof toggles) => useApp.setState((s) => ({ toggles: { ...s.toggles, [k]: !s.toggles[k] } }));
  return (
    <div className="vp-toolbar" role="toolbar" aria-label="View">
      <label className="vp-explode">
        <span className="small">Explode</span>
        <input type="range" min={0} max={1} step={0.01} value={explode} onChange={(e) => useApp.setState({ explode: Number(e.target.value) })} aria-label="Explode" />
      </label>
      <span className="vp-sep" />
      <div className="seg">
        {(["iso", "top", "front", "side"] as const).map((p) => (
          <button key={p} type="button" className={`seg-btn ${preset === p ? "active" : ""}`} onClick={() => setPreset(p)}>
            {p}
          </button>
        ))}
      </div>
      <button type="button" className="btn ghost sm" disabled={!hasScene} onClick={() => setPreset("scene")} title="Reset to the scene camera">
        Reset
      </button>
      <span className="vp-sep" />
      <div className="seg">
        {(["case", "board", "keycaps", "labels"] as const).map((k) => (
          <button key={k} type="button" className={`seg-btn ${toggles[k] ? "active" : ""}`} aria-pressed={toggles[k]} onClick={() => toggle(k)}>
            {k}
          </button>
        ))}
      </div>
      {moving && (
        <>
          <span className="vp-sep" />
          <div className="seg">
            {(["translate", "rotate"] as const).map((m) => (
              <button key={m} type="button" className={`seg-btn ${props.gizmoMode === m ? "active" : ""}`} onClick={() => props.setGizmoMode(m)}>
                {m}
              </button>
            ))}
          </div>
          <button type="button" className="btn ghost sm" onClick={() => useApp.setState({ moving: null })}>
            Done
          </button>
        </>
      )}
    </div>
  );
}
