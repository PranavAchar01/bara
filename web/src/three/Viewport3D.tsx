// C10 Viewport3D: build space is Z up, mm (SPEC 3.2). Arrayed parts draw as
// one instanced mesh per material (SPEC 3.3). Studio look per the render
// recipe: neutral tone mapping, room environment, off-white floor with baked
// contact shadow, GLB materials kept, matte case in the build's colour.
// Missing assets render as translucent boxes with a label (SPEC 11.4);
// failing checks get a red hull outline. The explode slider eases every part
// along Z by layer; when it is held open, one leader-line label per part.
import { type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useShallow } from "zustand/react/shallow";
import { GizmoHelper, GizmoViewcube, Html, OrbitControls, TransformControls } from "@react-three/drei";
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { focusPart, pickPart, select, setView, useApp, type ViewPreset } from "../state/store";
import { switchCanvas } from "../state/canvases";
import { applyEdit } from "../net/client";
import { fetchPart } from "../components/Overlays";
import type { BBox, Board, Build, BuildPart, Enclosure, Layout } from "../spec/types";
import { failingByInstance } from "../ui/format";
import { groupPieces, modelAsset, onModelsChanged, preloadModels, useModel, useModelsLoading, type LoadedModel, type MeshGroup } from "./assets";
import { placeholderBox, type Box } from "./bbox";
import { boardMatrix, matchComponents, type BoardCandidate } from "./boardgeom";
import { LAYER_RANK, explodeZ, isKeycapPart, layerGap, layerOf, layerOffsets, partLabel, type LayerExtent, type LayerId, type PartLabel } from "./explode";
import { elementPoses, type ElementPose } from "./layout";
import { arrangeDevices, chooseCamera, type Box as FloorBox } from "./arrange";
import { LabelOverlay, LabelProjector, labelOpacity } from "./labels";
import { FocusDriver, meshBox, nearFocused } from "./focus";
import { setLook, type Look } from "./look";
import { ProjectLinkLines } from "./projectLinks";
import { AutoLinker } from "../project/project";
import { caseMaterial, useCasePreview } from "./caseFinish";
import { defaultColor, finishMaterial, ghost, placeholderMaterial, presetFor, presetMaterial, tinted, usesPreset, wearsFinish } from "./materials";
import { focusAmount, registerAnchor, stage, stageBox } from "./stage";
import { StudioEnvironment, StudioFloor, studioPalette, type StudioPalette } from "./studio";
import { DemandDriver, StudioPost, postEnabled } from "./post";
import { SHOT_ID } from "./shot";
import { Glyph } from "../ui/glyphs";
import { Icon } from "../ui/common";
import { BoardPlaceholder, BoardStatus, FootprintHover, boardBadge, footprintBoxes } from "./board";
import { AgentTargetProbe, partWorldBox, registerPart } from "./agentTargets";
import { agentPose, easeOut } from "./agentCam";
import { caps } from "../sim/press";
import { pressKeyOf, type SimInput } from "../sim/inputMap";
import { canSimulate, enterSimulation, exitSimulation, useSim } from "../sim/simStore";
import { SimOverlay } from "../sim/SimOverlay";
import { SimHotspotsHost } from "../sim/SimHotspots";
import { inputHandlers, SimCaps, SimDriver, SimScreens } from "./sim3d";

const DEG = Math.PI / 180;

interface Theme {
  accent: string;
  fail: string;
  text: string;
  muted: string;
  line: string;
  dark: boolean;
}

function isDark(): boolean {
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "dark") return true;
  if (attr === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readTheme(): Theme {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, d: string) => cs.getPropertyValue(n).trim() || d;
  const dark = isDark();
  return {
    accent: v("--accent", "#2f55d4"),
    fail: v("--fail", "#c2362f"),
    text: dark ? "#ECECEA" : "#1B1D1F",
    muted: dark ? "#A3A5A8" : "#5D6166",
    line: dark ? "#8D9095" : "#7C8086",
    dark,
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

/** Placeholder solid: a rounded box so caps and modules read as objects, not wireframes. */
function boxGeometry(box: Box): THREE.BufferGeometry {
  const sx = Math.max(0.2, box.max[0] - box.min[0]);
  const sy = Math.max(0.2, box.max[1] - box.min[1]);
  const sz = Math.max(0.2, box.max[2] - box.min[2]);
  const r = Math.min(2, Math.min(sx, sy, sz) * 0.2);
  const g = r > 0.15 ? new RoundedBoxGeometry(sx, sy, sz, 2, r) : new THREE.BoxGeometry(sx, sy, sz);
  g.translate((box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (box.min[2] + box.max[2]) / 2);
  return g;
}

/** Stand-in for a keycap without a model: a rounded cap that narrows toward its top, filling the box. */
function keycapGeometry(box: Box): THREE.BufferGeometry {
  const sx = Math.max(1, box.max[0] - box.min[0] - 0.6);
  const sy = Math.max(1, box.max[1] - box.min[1] - 0.6);
  const sz = Math.max(1, box.max[2] - box.min[2]);
  const g = new RoundedBoxGeometry(sx, sy, sz, 3, Math.min(1.2, sz * 0.2, Math.min(sx, sy) * 0.12));
  // taper: the top face is about 3/4 of the skirt, like a DSA or OEM cap
  const pos = g.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const t = (pos.getZ(i) + sz / 2) / sz;
    const k = 1 - 0.24 * t;
    const inset = Math.min(sx, sy) * 0.06 * t;
    pos.setXYZ(i, pos.getX(i) * k, pos.getY(i) * k - inset, pos.getZ(i));
  }
  g.computeVertexNormals();
  g.translate((box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (box.min[2] + box.max[2]) / 2);
  return g;
}

/** Stand-in for a knob without a model: a turned metal cylinder with a softened top edge. */
function knobGeometry(box: Box): THREE.BufferGeometry {
  const d = Math.max(2, Math.min(box.max[0] - box.min[0], box.max[1] - box.min[1]));
  const h = Math.max(2, box.max[2] - box.min[2]);
  const g = new THREE.CylinderGeometry(d * 0.47, d / 2, h, 64, 1);
  g.rotateX(Math.PI / 2);
  g.translate((box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, box.min[2] + h / 2);
  return g;
}

/** Parts drawn as their shape when they have no model: keycaps and knobs (a board without them reads as unfinished). */
function hasStandIn(part: BuildPart, preset: ReturnType<typeof presetFor>): boolean {
  return preset === "keycap" || (preset === "metal" && /\bknob\b|^knob:/.test(`${part.part_id} ${part.card.display_name}`.toLowerCase()));
}

/** Placeholder for a ball (trackball without a model): a sphere filling the box. */
function sphereGeometry(box: Box): THREE.BufferGeometry {
  const d = Math.max(1, Math.min(box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]));
  const g = new THREE.SphereGeometry(d / 2, 48, 32);
  g.translate((box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, box.min[2] + d / 2);
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

function elementMatrix(pose: ElementPose): THREE.Matrix4 {
  const p = pose.position;
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(pose.rotation[0] * DEG, pose.rotation[1] * DEG, pose.rotation[2] * DEG, "XYZ"));
  const yaw = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), pose.yaw * DEG);
  q.multiply(yaw);
  return new THREE.Matrix4().compose(new THREE.Vector3(p[0], p[1], p[2]), q, new THREE.Vector3(1, 1, 1));
}

/**
 * Moves a group along Z with the eased explode factor, registers its label anchor, and blends it
 * toward its focus pose (centre stage, or the shelf) as focus eases in.
 */
function useLayerGroup(layer: LayerId, anchorKey: string | null, anchorLocal: THREE.Vector3, focusKey: string | null = null) {
  const ref = useRef<THREE.Group>(null);
  useFrame(() => {
    const g = ref.current;
    if (!g) return;
    // each layer lifts by its measured height so layers stand clear of one another; the plain
    // rank-times-gap stack stands in until they are measured
    const lifted = stage.layerZ?.[layer];
    let z = lifted !== undefined ? lifted * stage.explode : explodeZ(layer, stage.gap, stage.explode);
    g.userData.restZ = z;
    // pick view: the picked part lifts a little out of its layer, every other part fades to a ghost;
    // otherwise the part under the pointer is tinted
    const mine = !!focusKey && focusKey === stage.pickKey;
    let look: Look = "none";
    let amount = 0;
    if (stage.pickK > 0.002 && stage.pickKey) {
      if (mine) z += pickLift() * stage.pickK;
      else {
        look = "ghost";
        amount = stage.pickK;
      }
    } else if (focusKey && stage.hoverKey === focusKey && stage.explode > 0.5) look = "hover";
    if (look !== "none" || g.userData.look) {
      setLook(g, look, amount);
      g.userData.look = look === "none" ? undefined : look;
    }
    const pose = stage.focusK > 0 ? stage.focusPose.get(g) : undefined;
    if (!pose) {
      g.position.set(0, 0, z);
      if (g.scale.x !== 1) g.scale.setScalar(1);
      return;
    }
    const k = stage.focusK;
    g.position.set(pose.pos.x * k, pose.pos.y * k, z + (pose.pos.z - z) * k);
    g.scale.setScalar(1 + (pose.scale - 1) * k);
  });
  useEffect(() => {
    const g = ref.current;
    if (!g) return;
    stage.layerGroups.set(g, layer);
    return () => {
      stage.layerGroups.delete(g);
    };
  }, [layer]);
  useEffect(() => {
    const g = ref.current;
    if (!g || !focusKey) return;
    stage.focusGroups.set(g, focusKey);
    g.userData.fkey = focusKey;
    return () => {
      stage.focusGroups.delete(g);
      stage.focusPose.delete(g);
    };
  }, [focusKey]);
  useEffect(() => {
    if (!anchorKey) return;
    const out = new THREE.Vector3();
    return registerAnchor({
      key: anchorKey,
      world: () => {
        const g = ref.current;
        out.copy(anchorLocal);
        if (g) out.z += g.position.z;
        return out;
      },
      owner: () => ref.current,
    });
  }, [anchorKey, anchorLocal]);
  return ref;
}

/** One instanced mesh per material group; all share the same instance matrices. */
function InstancedGroups(props: {
  groups: MeshGroup[];
  matrices: THREE.Matrix4[];
  onClick?: (e: ThreeEvent<MouseEvent>) => void;
  onHover?: (on: boolean) => void;
  /** Simulation: the press key of each element and the inputs they stand for. */
  sim?: { keys: string[]; inputs: Map<string, SimInput> };
}) {
  const refs = useRef<(THREE.InstancedMesh | null)[]>([]);
  const capSeen = useRef(-1);
  useLayoutEffect(() => {
    capSeen.current = -1;
    for (const ref of refs.current) {
      if (!ref) continue;
      props.matrices.forEach((m, i) => ref.setMatrixAt(i, m));
      ref.instanceMatrix.needsUpdate = true;
      ref.computeBoundingBox();
      ref.computeBoundingSphere();
    }
  }, [props.matrices, props.groups, props.sim]);
  // A pressed key or button sinks along its own up axis.
  const lift = useMemo(() => new THREE.Matrix4(), []);
  const pressed = useMemo(() => new THREE.Matrix4(), []);
  useFrame(() => {
    const sim = props.sim;
    if (!sim || capSeen.current === caps.version) return;
    capSeen.current = caps.version;
    props.matrices.forEach((m, j) => {
      const depth = caps.depth.get(sim.keys[j]) ?? 0;
      const mat = depth > 0 ? pressed.copy(m).multiply(lift.makeTranslation(0, 0, -depth)) : m;
      for (const ref of refs.current) ref?.setMatrixAt(j, mat);
    });
    for (const ref of refs.current) if (ref) ref.instanceMatrix.needsUpdate = true;
  });
  const simHandlers = useMemo(() => {
    const sim = props.sim;
    return sim ? inputHandlers((e) => (e.instanceId === undefined ? null : (sim.inputs.get(sim.keys[e.instanceId]) ?? null))) : null;
  }, [props.sim]);
  const n = props.matrices.length;
  return (
    <>
      {props.groups.map((g, i) => (
        <instancedMesh
          key={`${g.geometry.uuid}:${g.material.uuid}:${n}`}
          ref={(el) => {
            refs.current[i] = el;
          }}
          args={[g.geometry, g.material, n]}
          castShadow
          onClick={props.onClick}
          {...simHandlers}
          onPointerOver={(e) => {
            if (simHandlers) {
              simHandlers.onPointerOver(e);
              return;
            }
            if (!props.onClick) return;
            e.stopPropagation();
            document.body.style.cursor = "pointer";
            props.onHover?.(true);
          }}
          onPointerOut={() => {
            document.body.style.cursor = "";
            if (simHandlers) simHandlers.onPointerOut();
            else props.onHover?.(false);
          }}
        />
      ))}
    </>
  );
}

interface PartNodeProps {
  part: BuildPart;
  layout: Layout | undefined;
  layouts: Layout[];
  boards: Board[];
  parts: BuildPart[];
  provisional: boolean;
  selected: boolean;
  failing: boolean;
  highlight: boolean;
  /** The agent on stage is working on this part: accent outline, no forced label. */
  focus: boolean;
  labels: boolean;
  theme: Theme;
  pose: { position_mm: number[]; rotation_deg: number[] } | null;
  labelKey: string | null;
  /** The routed board GLB already shows this part: keep its anchor and outline, draw no mesh. */
  covered: boolean;
}

/** PCBs and FR4 plates are kicad-cli board exports: their layers get the KiCad board look. */
function isBoardPart(part: BuildPart): boolean {
  return String(part.card.kind) === "pcb" || /plate_fr4/.test(part.part_id);
}

function PartNode(props: PartNodeProps) {
  const { part, theme } = props;
  const pose = props.pose;
  const poses = useMemo(() => {
    const placement = pose ? { ...part.placement, position_mm: pose.position_mm, rotation_deg: pose.rotation_deg } : part.placement;
    return elementPoses(placement, part.quantity, props.layout);
  }, [pose, part.placement, part.quantity, props.layout]);
  const asset = modelAsset(part.assets, poses.length > 1);
  const model = useModel(asset?.url ?? null, isBoardPart(part));
  const catalog = useCatalogBbox(part.part_id);
  const box = useMemo(
    () => placeholderBox(part, { layouts: props.layouts, boards: props.boards, parts: props.parts, catalogBbox: catalog }),
    [part, props.layouts, props.boards, props.parts, catalog],
  );
  const loaded = model.status === "ready" && model.model.groups.length > 0 ? model.model : null;
  const missing = !loaded;
  const color = defaultColor(part);
  const preset = presetFor(part);
  // keycaps and knobs keep their shape without a model: a board missing them reads as unfinished
  const standIn = hasStandIn(part, preset);
  const placeholderGeom = useMemo(
    () =>
      loaded
        ? null
        : preset === "glossy"
          ? sphereGeometry(box)
          : standIn
            ? preset === "keycap"
              ? keycapGeometry(box)
              : knobGeometry(box)
            : boxGeometry(box),
    [loaded, box, preset, standIn],
  );
  useEffect(() => () => placeholderGeom?.dispose(), [placeholderGeom]);
  const groups = useMemo<MeshGroup[]>(() => {
    if (loaded) {
      if (wearsFinish(part.finish)) {
        const mat = finishMaterial(part.finish);
        return loaded.groups.map((g) => ({ ...g, material: mat }));
      }
      // Keycaps, knobs and balls take the studio preset in the part's colour.
      if (usesPreset(preset)) {
        const mat = presetMaterial(preset, color);
        return loaded.groups.map((g) => ({ ...g, material: mat }));
      }
      // Keep the GLB's own PBR materials; a single flat-colour part takes the build's colour.
      // A textured one (gltf-transform palette) carries its real colours in the texture, so it keeps them.
      if (loaded.groups.length === 1 && part.color?.hex && !loaded.groups[0].material.map) {
        const g = loaded.groups[0];
        return [{ ...g, material: tinted(g.material, part.color.hex) }];
      }
      return loaded.groups;
    }
    // No model: a keycap or knob is still drawn solid in its colour and preset;
    // anything else is a faint neutral shell with its edges drawn, labelled, so it never reads as the part.
    if (!placeholderGeom) return [];
    return [{ geometry: placeholderGeom, material: standIn ? presetMaterial(preset, color) : placeholderMaterial(), weight: 0 }];
  }, [loaded, part.color?.hex, part.finish, preset, color, placeholderGeom, standIn]);
  const placeholderEdges = useMemo(() => (placeholderGeom && !standIn ? new THREE.EdgesGeometry(placeholderGeom, 25) : null), [placeholderGeom, standIn]);
  useEffect(() => () => placeholderEdges?.dispose(), [placeholderEdges]);
  const assembled = useApp((s) => s.explode < 0.8);
  const provisionalGroups = useMemo(
    () => (props.provisional && loaded ? groups.map((g) => ({ ...g, material: ghost(g.material, 0.5) })) : groups),
    [props.provisional, loaded, groups],
  );
  const hullSrc = loaded?.merged ?? placeholderGeom;
  const hull = useMemo(() => (hullSrc ? hullGeometry(hullSrc, String(part.card.kind) === "pcb" ? 1.2 : 0.8) : null), [hullSrc, part.card.kind]);
  useEffect(() => () => hull?.dispose(), [hull]);
  const matrices = useMemo(() => poses.map((p) => elementMatrix(p)), [poses]);
  // in focus the part is already singled out; a selection outline would only drown it in blue
  const inFocus = useApp((s) => s.focusKey === partLabel(part).key);
  const focusOn = useApp((s) => s.focusKey !== null);
  const outline = props.failing ? theme.fail : (props.selected || props.highlight || props.focus) && !inFocus ? theme.accent : null;
  const hullRef = useRef<THREE.InstancedMesh>(null);
  useLayoutEffect(() => {
    const ref = hullRef.current;
    if (!ref) return;
    matrices.forEach((m, i) => ref.setMatrixAt(i, m));
    ref.instanceMatrix.needsUpdate = true;
    ref.computeBoundingSphere();
  }, [matrices, hull, outline]);
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    select(part.instance_id);
    pickPart(partLabel(part).key);
  };
  const simActive = useSim((s) => s.active);
  const simInputs = useSim((s) => s.byPressKey);
  const pressKeys = useMemo(() => poses.map((p, j) => pressKeyOf(part, p.index, j)), [poses, part]);
  const sim = useMemo(
    () => (simActive && pressKeys.some((k) => simInputs.has(k)) ? { keys: pressKeys, inputs: simInputs } : undefined),
    [simActive, simInputs, pressKeys],
  );
  const midZ = loaded ? (loaded.bbox.min.z + loaded.bbox.max.z) / 2 : (box.min[2] + box.max[2]) / 2;
  const topZ = loaded ? loaded.bbox.max.z : box.max[2];
  const centroid = useMemo(() => {
    const c = new THREE.Vector3();
    for (const m of matrices) c.add(new THREE.Vector3().setFromMatrixPosition(m));
    return c.divideScalar(Math.max(1, matrices.length));
  }, [matrices]);
  const anchorLocal = useMemo(() => {
    // Leader lines land on the element nearest the centroid, mid-height.
    let best = centroid.clone();
    let d = Infinity;
    for (const m of matrices) {
      const p = new THREE.Vector3().setFromMatrixPosition(m);
      const dd = p.distanceToSquared(centroid);
      if (dd < d) {
        d = dd;
        best = p;
      }
    }
    return new THREE.Vector3(best.x, best.y, best.z + midZ);
  }, [centroid, matrices, midZ]);
  const htmlAnchor = useMemo(() => new THREE.Vector3(centroid.x, centroid.y, centroid.z + topZ + 2), [centroid, topZ]);
  const ref = useLayerGroup(layerOf(part), props.labelKey, anchorLocal, partLabel(part).key);
  // Agent target: every element's box (model or placeholder) in the layer group's space; holds when covered too.
  const localBox = useMemo(() => {
    const out = new THREE.Box3();
    const base = loaded ? loaded.bbox.clone() : new THREE.Box3(new THREE.Vector3(...box.min), new THREE.Vector3(...box.max));
    const t = new THREE.Box3();
    for (const m of matrices) out.union(t.copy(base).applyMatrix4(m));
    return out;
  }, [loaded, box, matrices]);
  useEffect(() => (ref.current ? registerPart(part.instance_id, ref.current, localBox) : undefined), [ref, part.instance_id, localBox]);
  // A placeholder's "(no model)" tag shows on hover or when the parts panel points at it, never by
  // default: a tag pinned in the hero sat on top of real parts (battery under the OLED).
  const [hover, setHover] = useState(false);
  // hoverPart: the nearest part mesh under the pointer (its over handler stops propagation), for the agent on stage.
  const id = part.instance_id;
  const onHover = useCallback(
    (on: boolean) => {
      const cur = useApp.getState().hoverPart;
      if (on && cur !== id) useApp.setState({ hoverPart: id });
      else if (!on && cur === id) useApp.setState({ hoverPart: null });
    },
    [id],
  );
  useEffect(() => () => onHover(false), [onHover, props.covered]);
  return (
    <group
      ref={ref}
      onPointerOver={missing ? () => setHover(true) : undefined}
      onPointerOut={missing ? () => setHover(false) : undefined}
    >
      {!props.covered && <InstancedGroups groups={provisionalGroups} matrices={matrices} onClick={simActive ? undefined : onClick} onHover={onHover} sim={sim} />}
      {!props.covered &&
        placeholderEdges &&
        matrices.map((m, i) => (
          <lineSegments key={i} geometry={placeholderEdges} matrixAutoUpdate={false} matrix={m} raycast={() => null}>
            <lineBasicMaterial color="#8A9099" transparent opacity={0.7} depthWrite={false} toneMapped={false} />
          </lineSegments>
        ))}
      {outline && hull && (
        <instancedMesh key={`h${matrices.length}:${hull.uuid}${outline}`} ref={hullRef} args={[hull, undefined, matrices.length]} raycast={() => null}>
          <meshBasicMaterial color={outline} side={THREE.BackSide} transparent opacity={0.95} depthWrite={false} toneMapped={false} />
        </instancedMesh>
      )}
      {!focusOn && (props.labels || props.selected || (missing && !props.covered && assembled && (hover || props.highlight))) && (
        <Html position={htmlAnchor} center zIndexRange={[20, 0]} style={{ pointerEvents: "none" }}>
          <span className={`vp-label ${missing ? "missing" : ""} ${props.failing ? "failing" : ""}`}>
            {part.label ?? part.card.display_name}
            {missing ? " (no model)" : ""}
          </span>
        </Html>
      )}
    </group>
  );
}

/** Case colour: the brief's, or graphite when the server only filled in its default (a light grey melted into the white floor). */
const CASE_NEUTRAL = "#4A4E55";
function caseHex(enc: Enclosure): string {
  return enc.color?.hex && enc.color_source !== "default" ? enc.color.hex : CASE_NEUTRAL;
}

const LID_NAME = /bezel|lid|cover|top/i;

/**
 * Share of the footprint covered by upward faces in the upper half of the
 * geometry: near 1 for a closed lid, low for an open tray or a key plate.
 */
function upCoverage(geoms: THREE.BufferGeometry[]): number {
  const box = new THREE.Box3();
  for (const g of geoms) {
    g.computeBoundingBox();
    if (g.boundingBox) box.union(g.boundingBox);
  }
  const footprint = (box.max.x - box.min.x) * (box.max.y - box.min.y);
  if (!(footprint > 0)) return 0;
  const zCut = box.min.z + (box.max.z - box.min.z) * 0.5;
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  const n = new THREE.Vector3();
  let area = 0;
  for (const g of geoms) {
    const pos = g.attributes.position as THREE.BufferAttribute;
    const idx = g.index;
    const tris = (idx ? idx.count : pos.count) / 3;
    for (let t = 0; t < tris; t++) {
      const i0 = idx ? idx.getX(t * 3) : t * 3;
      const i1 = idx ? idx.getX(t * 3 + 1) : t * 3 + 1;
      const i2 = idx ? idx.getX(t * 3 + 2) : t * 3 + 2;
      a.fromBufferAttribute(pos, i0);
      b.fromBufferAttribute(pos, i1);
      c.fromBufferAttribute(pos, i2);
      if ((a.z + b.z + c.z) / 3 < zCut) continue;
      n.subVectors(c, b).cross(a.clone().sub(b));
      const len = n.length();
      if (len > 0 && n.z / len > 0.7) area += len / 2;
    }
  }
  return area / footprint;
}

/** A case piece: its geometries, and whether it is the lid that lifts off in the explode. */
const CLEAR_MAX = 0.42;

interface CasePiece {
  geoms: THREE.BufferGeometry[];
  lid: boolean;
}

function casePieces(loaded: LoadedModel): CasePiece[] {
  const named = loaded.components.map((c, i) => ({ i, lid: LID_NAME.test(c.name) }));
  const geomsOf = (keep: (i: number) => boolean) => groupPieces(loaded.pieces, keep).map((g) => g.geometry);
  if (named.length > 1 && named.some((c) => c.lid) && named.some((c) => !c.lid)) {
    const lidSet = new Set(named.filter((c) => c.lid).map((c) => c.i));
      return [
      { geoms: geomsOf((i) => !lidSet.has(i)), lid: false },
      { geoms: geomsOf((i) => lidSet.has(i)), lid: true },
    ];
  }
  const all = loaded.groups.map((g) => g.geometry);
  return [{ geoms: all, lid: upCoverage(all) > 0.6 }];
}

function CasePieceNode(props: {
  piece: CasePiece;
  enc: Enclosure;
  material: THREE.MeshStandardMaterial;
  /** The user chose a finish: show the real material assembled, not the ghost shell. */
  real: boolean;
  edge: string | null;
  anchorKey: string | null;
  focusKey: string;
  onClick: (e: ThreeEvent<MouseEvent>) => void;
}) {
  const { piece, enc } = props;
  const pos = useMemo(() => enc.position_mm ?? [0, 0, 0], [enc.position_mm]);
  const rot = useMemo(() => enc.rotation_deg ?? [0, 0, 0], [enc.rotation_deg]);
  const anchorLocal = useMemo(() => {
    const box = new THREE.Box3();
    for (const g of piece.geoms) {
      g.computeBoundingBox();
      if (g.boundingBox) box.union(g.boundingBox);
    }
    // Leader lines land on the near (front) wall, a third of the way up.
    const v = new THREE.Vector3((box.min.x + box.max.x) / 2, box.min.y, box.min.z + (box.max.z - box.min.z) * (piece.lid ? 0.8 : 0.4));
    v.applyEuler(new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG, "XYZ"));
    return v.add(new THREE.Vector3(pos[0], pos[1], pos[2]));
  }, [piece, pos, rot]);
  const ref = useLayerGroup(piece.lid ? "lid" : "case", props.anchorKey, anchorLocal, props.focusKey);
  // Assembled, every case piece is a translucent shell with its edges drawn, so
  // the board inside stays in view; pieces turn solid as the explode opens. A
  // finish the user picked is shown as it is instead: see-through finishes pass
  // light (transmission) and show the board for real, opaque ones are solid.
  const material = useMemo(() => {
    const m = props.material.clone();
    m.transparent = true;
    m.depthWrite = false;
    return m;
  }, [props.material]);
  useEffect(() => () => material.dispose(), [material]);
  const edges = useMemo(() => piece.geoms.map((g) => new THREE.EdgesGeometry(g, 40)), [piece.geoms]);
  useEffect(() => () => edges.forEach((e) => e.dispose()), [edges]);
  const edgeMat = useMemo(() => new THREE.LineBasicMaterial({ color: "#1F2226", transparent: true, opacity: 0.3, depthWrite: false, toneMapped: false }), []);
  useEffect(() => () => edgeMat.dispose(), [edgeMat]);
  const base = props.material.opacity;
  const floor = piece.lid ? 0.16 : 0.24;
  const real = props.real;
  useFrame(() => {
    const k = real ? 1 : Math.min(1, stage.explode / 0.6);
    // A chosen real material carries its own opacity; otherwise clear plastic, a little denser when pulled apart, never opaque.
    const o = real ? base : (floor + (CLEAR_MAX - floor) * k) * base;
    material.opacity = o;
    // Creases stay drawn when pulled apart, like the outlines the library parts carry in their own geometry.
    edgeMat.opacity = real ? 0.12 : 0.3 + 0.25 * k;
    const solid = k >= 0.999 && base >= 0.999;
    if (material.depthWrite !== solid) {
      material.depthWrite = solid;
      material.transparent = !solid;
      material.needsUpdate = true;
    }
  });
  return (
    <group ref={ref}>
      <group
        position={[pos[0], pos[1], pos[2]]}
        rotation={new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG, "XYZ")}
        userData={props.enc.status === "pending" ? undefined : { fit: `case:${props.enc.enclosure_id}` }}
      >
        {piece.geoms.map((g) => (
          <mesh
            key={g.uuid}
            geometry={g}
            material={material}
            onClick={(e) => {
              // A see-through shell lets the click reach the part you can see inside it (a key, the
              // board, the controller): only a click on bare case picks the case.
              if (material.transparent && material.opacity < 0.5 && throughShell(e, ref.current)) return;
              if (useApp.getState().explode > 0.5 && !useSim.getState().active) {
                e.stopPropagation();
                pickPart(props.focusKey);
              } else props.onClick(e);
            }}
            renderOrder={2}
          />
        ))}
        {edges.map((e) => (
          <lineSegments key={e.uuid} geometry={e} material={edgeMat} raycast={() => null} renderOrder={3} />
        ))}
        {props.edge && piece.geoms[0] && (
          <mesh geometry={piece.geoms[0]} scale={1.01} raycast={() => null}>
            <meshBasicMaterial color={props.edge} side={THREE.BackSide} transparent opacity={0.9} depthWrite={false} toneMapped={false} />
          </mesh>
        )}
      </group>
    </group>
  );
}

function EnclosureNode(props: { enc: Enclosure; theme: Theme; selected: boolean; failing: boolean; labelled: boolean }) {
  const { enc, theme } = props;
  const asset = modelAsset(enc.assets, false);
  const model = useModel(asset?.url ?? null);
  const size = enc.outer_size_mm;
  const loaded = model.status === "ready" && model.model.groups.length > 0 ? model.model : null;
  const pending = enc.status === "pending";
  const preview = useCasePreview((s) => s.byId[enc.enclosure_id]);
  const hex = preview?.hex ?? caseHex(enc);
  const pieces = useMemo<CasePiece[]>(() => {
    if (loaded) return casePieces(loaded);
    if (!size || size.length < 3) return [];
    const [x, y, z] = [Math.max(size[0], 0.5), Math.max(size[1], 0.5), Math.max(size[2], 0.5)];
    return [{ geoms: [boxGeometry({ min: [-x / 2, -y / 2, -z / 2], max: [x / 2, y / 2, z / 2] })], lid: false }];
  }, [loaded, size]);
  useEffect(() => () => {
    if (!loaded) for (const p of pieces) for (const g of p.geoms) g.dispose();
  }, [loaded, pieces]);
  const finish = preview ? preview.finish : enc.color?.finish;
  const material = useMemo(() => {
    const base = caseMaterial(hex, finish);
    if (pending) return ghost(base, 0.35);
    return loaded ? base : ghost(base, 0.6);
  }, [hex, finish, loaded, pending]);
  if (enc.kind === "none" || !pieces.length) return null;
  const edge = props.failing ? theme.fail : props.selected ? theme.accent : null;
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    if (useSim.getState().active) return;
    e.stopPropagation();
    useApp.setState({ resizeTarget: { enclosure_id: enc.enclosure_id }, overlay: "resize", selection: null });
  };
  return (
    <>
      {pieces.map((p, i) => (
        <CasePieceNode
          key={`${enc.enclosure_id}:${i}:${p.lid}`}
          piece={p}
          enc={enc}
          material={material}
          real={!!finish}
          edge={edge}
          onClick={onClick}
          anchorKey={props.labelled ? (p.lid && pieces.length > 1 ? "e:case_top" : "e:case") : null}
          focusKey={p.lid && pieces.length > 1 ? "e:case_top" : "e:case"}
        />
      ))}
    </>
  );
}

/** True when the click also hits a part of the build behind this shell (not the shell itself). */
function throughShell(e: ThreeEvent<MouseEvent>, shell: THREE.Object3D | null): boolean {
  const root = stage.root;
  if (!root || !shell) return false;
  const under = (o: THREE.Object3D | null, owner: THREE.Object3D) => {
    for (let x = o; x; x = x.parent) if (x === owner) return true;
    return false;
  };
  return e.intersections.some((h) => h.distance > e.distance && h.object.visible && (h.object as THREE.Mesh).isMesh && under(h.object, root) && !under(h.object, shell));
}

/** Board GLB from the board stage (kicad-cli export): drawn with KiCad's own materials. */
function boardModelUrl(board: Board): string | null {
  return modelAsset(board.assets, false)?.url ?? null;
}


function BoardPiece(props: {
  groups: MeshGroup[];
  board: Board;
  layer: LayerId;
  labelKey: string | null;
  anchor: THREE.Vector3;
  /** The part this piece draws (a footprint's 3D model), or the bare board. */
  focusKey?: string;
  /** Registers the piece as an agent target under this id, bounded by `targetBox` (board space). */
  targetId?: string;
  targetBox?: THREE.Box3 | null;
  onClick?: (e: ThreeEvent<MouseEvent>) => void;
  children?: ReactNode;
}) {
  const { board, targetId, targetBox } = props;
  const pos = useMemo(() => board.position_mm ?? [0, 0, 0], [board.position_mm]);
  const rot = useMemo(() => board.rotation_deg ?? [0, 0, 0], [board.rotation_deg]);
  const ref = useLayerGroup(props.layer, props.labelKey, props.anchor, props.focusKey ?? "b:board");
  const localBox = useMemo(() => (targetBox && !targetBox.isEmpty() ? targetBox.clone().applyMatrix4(boardMatrix(board)) : null), [targetBox, board]);
  useEffect(() => (targetId && localBox && ref.current ? registerPart(targetId, ref.current, localBox) : undefined), [ref, targetId, localBox]);
  return (
    <group ref={ref}>
      <group position={[pos[0], pos[1], pos[2]]} rotation={new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG, "XYZ")}>
        {props.groups.map((g) => (
          // Without a click handler the mesh never raycasts: footprint hover uses boxes, not the board mesh.
          <mesh key={`${g.geometry.uuid}:${g.material.uuid}`} geometry={g.geometry} material={g.material} onClick={props.onClick} raycast={props.onClick ? undefined : () => null} />
        ))}
        {props.children}
      </group>
    </group>
  );
}

function BoardNode(props: {
  board: Board;
  labelKey: string | null;
  candidates: BoardCandidate[];
  onCovered: (boardId: string, ids: string[]) => void;
  parts: BuildPart[];
  theme: Theme;
}) {
  const { board, onCovered } = props;
  const model = useModel(boardModelUrl(board), true);
  const loaded = model.status === "ready" && model.model.groups.length > 0 ? model.model : null;
  const playing = useSim((s) => s.active);
  const buildOver = useApp((s) => s.view.done !== null || s.view.failure !== null);
  const boardStage = useApp((s) => s.view.stages.board?.status);
  // Routing or the GLB still on its way: the placeholder breathes and says which; a failed load offers a retry.
  const badge = loaded ? null : boardBadge({ boardStatus: board.status, model, buildOver, boardStage, playing });
  const busy = badge !== null && !badge.retry;
  const boxes = useMemo(() => footprintBoxes(board, loaded), [board, loaded]);
  const match = useMemo(() => (loaded ? matchComponents(loaded, board, props.candidates) : null), [loaded, board, props.candidates]);
  const coveredKey = useMemo(() => (match ? [...new Set([...match.owner.values()].map((c) => c.instanceId))].sort().join("|") : ""), [match]);
  useEffect(() => {
    onCovered(board.board_id, coveredKey ? coveredKey.split("|") : []);
    return () => onCovered(board.board_id, []);
  }, [board.board_id, coveredKey, onCovered]);
  const pieces = useMemo(() => {
    if (!loaded || !match) return null;
    const base = groupPieces(loaded.pieces, (i) => !match.owner.has(i));
    const byPart = new Map<string, BoardCandidate>();
    for (const c of match.owner.values()) byPart.set(c.instanceId, c);
    const parts = [...byPart.values()].map((cand) => ({ cand, groups: groupPieces(loaded.pieces, (i) => match.owner.get(i)?.instanceId === cand.instanceId) }));
    return { base, parts };
  }, [loaded, match]);
  const anchorLocal = useMemo(() => {
    const c = loaded ? loaded.bbox.getCenter(new THREE.Vector3()) : new THREE.Vector3((board.size_mm?.[0] ?? 0) / 2, -(board.size_mm?.[1] ?? 0) / 2, 0.8);
    if (loaded && match && match.substrate >= 0) {
      // Leader line lands on the bare board's front edge, not on a component.
      const sb = loaded.components[match.substrate].bbox;
      c.set((sb.min.x + sb.max.x) / 2, sb.min.y + (sb.max.y - sb.min.y) * 0.12, (sb.min.z + sb.max.z) / 2);
    }
    return c.applyMatrix4(boardMatrix(board));
  }, [loaded, match, board]);
  const hover = <FootprintHover boxes={boxes} parts={props.parts} accent={props.theme.accent} />;
  const targetId = board.part_instance_id ?? board.board_id;
  const targetBox = useMemo(() => {
    if (loaded) return loaded.bbox;
    const pts = board.outline_mm?.length ? board.outline_mm : board.size_mm ? [[0, 0], [board.size_mm[0], -board.size_mm[1]]] : [];
    if (!pts.length) return null;
    const b = new THREE.Box3();
    for (const p of pts) b.expandByPoint(new THREE.Vector3(p[0], p[1], 0));
    b.max.z = board.thickness_mm ?? 1.6;
    return b;
  }, [loaded, board.outline_mm, board.size_mm, board.thickness_mm]);
  // the bare board picks as the board, like its row in the label column
  const onBoardClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (board.part_instance_id) select(board.part_instance_id);
    pickPart("b:board");
  };
  if (!pieces) {
    // No GLB yet (routing, exporting or loading): the board drawn from its record.
    return (
      <group userData={{ fit: `board:${board.board_id}` }}>
        <BoardPiece groups={[]} board={board} layer="pcb" labelKey={props.labelKey} anchor={anchorLocal} targetId={targetId} targetBox={targetBox}>
          <BoardPlaceholder board={board} busy={busy} />
          {hover}
          {badge && <BoardStatus board={board} badge={badge} />}
        </BoardPiece>
      </group>
    );
  }
  return (
    <>
      <group userData={{ fit: `board:${board.board_id}` }}>
        <BoardPiece groups={pieces.base} board={board} layer="pcb" labelKey={props.labelKey} anchor={anchorLocal} targetId={targetId} targetBox={targetBox} onClick={onBoardClick}>
          {hover}
        </BoardPiece>
      </group>
      {pieces?.parts.map(({ cand, groups: g }) => {
        // a footprint's 3D model focuses as its part (the switches, the MCU), not as the board
        const part = props.parts.find((p) => p.instance_id === cand.instanceId);
        const key = part ? partLabel(part).key : "b:board";
        return (
          <BoardPiece
            key={cand.instanceId}
            groups={g}
            board={board}
            layer={cand.layer}
            labelKey={null}
            anchor={anchorLocal}
            focusKey={key}
            onClick={(e) => {
              e.stopPropagation();
              select(cand.instanceId);
              pickPart(key);
            }}
          />
        );
      })}
    </>
  );
}

// ---------------------------------------------------------------- case fit check

/** How far (mm) a board may poke past its case in plan before it is flagged; connectors overhang a little. */
const FIT_TOLERANCE_MM = 3;

/**
 * Worst plan-view overhang (mm) of any board past the case that overlaps it
 * most; a board touching no case counts its whole size. 0 when all fit.
 * Explode moves parts only in Z, so the check holds at any explode factor.
 */
export function caseOverhang(cases: THREE.Box3[], boards: THREE.Box3[]): number {
  let worst = 0;
  for (const b of boards) {
    let best: THREE.Box3 | null = null;
    let bestArea = 0;
    for (const c of cases) {
      const w = Math.min(b.max.x, c.max.x) - Math.max(b.min.x, c.min.x);
      const h = Math.min(b.max.y, c.max.y) - Math.max(b.min.y, c.min.y);
      const a = w > 0 && h > 0 ? w * h : 0;
      if (a > bestArea) {
        bestArea = a;
        best = c;
      }
    }
    if (!best) worst = Math.max(worst, b.max.x - b.min.x, b.max.y - b.min.y);
    else worst = Math.max(worst, best.min.x - b.min.x, b.max.x - best.max.x, best.min.y - b.min.y, b.max.y - best.max.y);
  }
  return worst;
}

/**
 * Measures the drawn cases and boards every 0.7 s while the scene is still and
 * reports the misfit in whole mm (0 = fits). A timer, not useFrame: with the
 * demand frame loop no frame follows the one where the last model lands.
 */
function FitCheck(props: { onResult: (overhangMm: number) => void }) {
  const scene = useThree((s) => s.scene);
  const { onResult } = props;
  useEffect(() => {
    let last = -1;
    const id = window.setInterval(() => {
      if (stage.moving) return;
      const cases = new Map<string, THREE.Box3>();
      const boards: THREE.Box3[] = [];
      scene.traverseVisible((o) => {
        const tag = o.userData?.fit as string | undefined;
        if (!tag) return;
        const box = new THREE.Box3().setFromObject(o);
        if (box.isEmpty()) return;
        if (tag.startsWith("case:")) cases.set(tag, (cases.get(tag) ?? new THREE.Box3()).union(box));
        else boards.push(box);
      });
      const over = cases.size && boards.length ? caseOverhang([...cases.values()], boards) : 0;
      const v = over > FIT_TOLERANCE_MM ? Math.round(over) : 0;
      if (v !== last) {
        last = v;
        onResult(v);
      }
    }, 700);
    return () => window.clearInterval(id);
  }, [scene, onResult]);
  return null;
}

// ---------------------------------------------------------------- camera

const HERO_DIR = new THREE.Vector3(-0.55, -1, 1.1).normalize();
const EXPLODED_DIR = new THREE.Vector3(-0.22, -1, 0.42).normalize();
/** Fraction of the view width the model may use while labels are shown. */
const LABEL_MODEL_WIDTH = 0.5;
/** How far the view shifts right (as a fraction of width) so the model sits left of the labels. */
const LABEL_SHIFT = 0.2;

function fallbackBox(): THREE.Box3 {
  const b = useApp.getState().build;
  const bb = b?.scene?.assembly_bbox_mm;
  if (bb?.min && bb?.max) return new THREE.Box3(new THREE.Vector3(bb.min[0], bb.min[1], bb.min[2]), new THREE.Vector3(bb.max[0], bb.max[1], bb.max[2]));
  return new THREE.Box3(new THREE.Vector3(-80, -50, 0), new THREE.Vector3(80, 50, 25));
}

/**
 * Fit the box's eight corners (not its bounding sphere, which leaves a lot of
 * empty grid) so the projected assembly spans `fill` of the view on its
 * tighter axis. `lift` raises the model by that fraction of the view height,
 * keeping it clear of the prompt bar and toolbar along the bottom edge.
 */
function fitPose(box: THREE.Box3, dir: THREE.Vector3, cam: THREE.PerspectiveCamera, widthFrac: number, fill: number, lift = 0) {
  const tanV = Math.tan((cam.fov * DEG) / 2);
  const tanH = tanV * cam.aspect * widthFrac;
  const fwd = dir.clone().negate();
  const right = new THREE.Vector3().crossVectors(fwd, cam.up).normalize();
  if (right.lengthSq() < 1e-6) right.set(1, 0, 0);
  const up = new THREE.Vector3().crossVectors(right, fwd).normalize();
  const center = box.getCenter(new THREE.Vector3());
  const corners: THREE.Vector3[] = [];
  for (let i = 0; i < 8; i++) {
    corners.push(new THREE.Vector3(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z));
  }
  // Centre on the projected extents (orthographic estimate), then solve the distance per corner.
  let x0 = Infinity;
  let x1 = -Infinity;
  let y0 = Infinity;
  let y1 = -Infinity;
  for (const c of corners) {
    const r = c.clone().sub(center);
    x0 = Math.min(x0, r.dot(right));
    x1 = Math.max(x1, r.dot(right));
    y0 = Math.min(y0, r.dot(up));
    y1 = Math.max(y1, r.dot(up));
  }
  const target = center.clone().addScaledVector(right, (x0 + x1) / 2).addScaledVector(up, (y0 + y1) / 2);
  let dist = 40;
  for (const c of corners) {
    const rel = c.clone().sub(target);
    const z = rel.dot(dir);
    dist = Math.max(dist, z + Math.abs(rel.dot(right)) / (tanH * fill), z + Math.abs(rel.dot(up)) / (tanV * fill));
  }
  target.addScaledVector(up, -2 * tanV * dist * lift);
  return { pos: target.clone().addScaledVector(dir, dist), target, dist };
}

type FrameKind = ViewPreset | "hero" | "exploded" | "sim";

/** Diagonal (mm) of a full-size keyboard: a device this big gets the whole `fill`. */
const FULL_SIZE_DIAG_MM = 330;

/**
 * How much of the view a device spans, by its real size: a handheld sits small in the frame and
 * a keyboard larger, so the scene reads as an object on a desk, not a poster. Square root so a
 * thumb-sized part still shows its features; never below 55% of `fill`.
 */
export function sizedFill(box: THREE.Box3, fill: number): number {
  const diag = box.getSize(new THREE.Vector3()).length();
  return fill * Math.min(1, Math.max(0.55, Math.sqrt(diag / FULL_SIZE_DIAG_MM)));
}

/**
 * Share of the view (its tighter axis) the framed device or devices may span: the device sits small
 * on the desk with plenty of breathing room, so a first look is calm rather than a wall of parts.
 */
const FIT_MIN = 0.36;
const FIT_MAX = 0.46;

/** 36% of the view for a thumb-sized device up to 46% for a full-size keyboard or bigger. */
export function sceneFill(box: THREE.Box3): number {
  const diag = box.getSize(new THREE.Vector3()).length();
  return FIT_MIN + (FIT_MAX - FIT_MIN) * Math.min(1, Math.max(0, diag / FULL_SIZE_DIAG_MM));
}

const toBox = (b: THREE.Box3): FloorBox => ({ min: [b.min.x, b.min.y, b.min.z], max: [b.max.x, b.max.y, b.max.z] });

/**
 * Where the camera goes for the devices on stage: one rule over their boxes (arrange.ts). Flat,
 * wide devices are seen from high up, near top-down, with the long side across the screen; tall or
 * handheld ones from a 3/4 view.
 */
function sceneDir(): THREE.Vector3 | null {
  const boxes = stageBoxes();
  if (!boxes.length) return null;
  const [x, y, z] = chooseCamera(boxes.map(toBox)).dir;
  return new THREE.Vector3(x, y, z);
}

/** Share of the free sim area the device spans on its tighter axis: a modest margin all round. */
const SIM_FILL = 0.82;

/** Space the play layout keeps clear around the device, in px (the top bar and the outputs dock). */
const SIM_TOP_PX = 56;
const SIM_DOCK_PX = 160;
const SIM_EDGE_PX = 32;

/**
 * The part of the canvas the device may use once play mode has settled: the canvas minus the play
 * panel on the right, the top bar and the outputs dock. Null when the canvas is not on the page.
 */
function simFreeArea(cam: THREE.PerspectiveCamera): { w: number; canvasW: number; left: number; canvasH: number; freeH: number; top: number; bottom: number } | null {
  const canvas = document.querySelector<HTMLElement>(".viewport canvas");
  if (!canvas) return null;
  const r = canvas.getBoundingClientRect();
  const narrow = window.innerWidth <= 860;
  const panel = narrow ? null : document.querySelector<HTMLElement>(".play-panel")?.getBoundingClientRect();
  const panelW = narrow ? 0 : panel && panel.width > 0 ? window.innerWidth - panel.left : Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--play-w")) || 340;
  const w = Math.min(r.right, window.innerWidth - panelW) - Math.max(0, r.left);
  const canvasH = r.height;
  const dock = document.querySelector<HTMLElement>(".play-dock")?.offsetHeight ?? SIM_DOCK_PX;
  // the terminal sits over the top of the canvas: the device starts below it, never under it
  const term = document.querySelector<HTMLElement>(".sim-terminal")?.getBoundingClientRect();
  const termBottom = term && term.height > 0 ? term.bottom - r.top + SIM_EDGE_PX / 2 : 0;
  const top = Math.max(0, SIM_TOP_PX - Math.max(0, r.top), termBottom);
  const bottom = dock + SIM_EDGE_PX + (narrow ? window.innerHeight * 0.46 : 0);
  const freeH = canvasH - top - bottom;
  if (w < 80 || freeH < 80 || !Number.isFinite(cam.fov)) return null;
  return { w, canvasW: r.width, left: Math.max(0, -r.left), canvasH, freeH, top, bottom };
}

/**
 * The operating direction turned about the vertical so the device's long floor axis runs across
 * the screen (arrange.ts decides which axis that is). Only a view from above or below has a free
 * turn; a view from the side already shows the width.
 */
function simDir(dir: THREE.Vector3): THREE.Vector3 {
  const boxes = stageBoxes();
  if (!boxes.length || Math.abs(dir.z) < 0.9) return dir;
  if (chooseCamera(boxes.map(toBox)).across === "x") return dir;
  // looking down with +Y to the right: a tiny sideways lean fixes the screen's right-hand axis
  return new THREE.Vector3(0.0001 * Math.sign(dir.z), 0, dir.z).normalize();
}

function stageBoxes(): THREE.Box3[] {
  return [stage.root, ...(stage.companions?.children ?? [])].filter((o): o is THREE.Object3D => !!o).map((o) => new THREE.Box3().setFromObject(o)).filter((b) => !b.isEmpty());
}

function framePose(kind: FrameKind, cam: THREE.PerspectiveCamera, predictExplode: number | null) {
  const box = stageBox() ?? fallbackBox();
  if (predictExplode !== null) box.max.z += (stage.layerZ ? stage.lift : stage.gap * maxRank()) * (predictExplode - stage.explode);
  if (kind === "exploded") return fitPose(box, EXPLODED_DIR, cam, LABEL_MODEL_WIDTH, Math.max(0.62, sizedFill(box, 0.8)), 0.04);
  if (kind === "sim") {
    // The operating view: straight at the control face, the device filling most of the viewport.
    const { view } = useSim.getState();
    const dir = simDir(new THREE.Vector3(...view.dir).normalize());
    const free = simFreeArea(cam);
    if (!free) return fitPose(box, dir, cam, 1, SIM_FILL, 0.02);
    // Fit inside the free area (left of the play panel, between the top bar and the outputs dock),
    // judged at the size the canvas settles to: the workspace is still resizing when the glide starts.
    const tanV = Math.tan((cam.fov * DEG) / 2) * (free.freeH / free.canvasH);
    const virt = cam.clone();
    virt.fov = (2 * Math.atan(tanV)) / DEG;
    virt.aspect = free.w / free.freeH;
    const fit = fitPose(box, dir, virt, 1, SIM_FILL, (free.bottom - free.top) / 2 / free.freeH);
    // and centre it across the free area, not the whole canvas (the play panel covers the right of it)
    const shiftX = (free.canvasW / 2 - (free.left + free.w / 2)) / free.canvasW;
    if (Math.abs(shiftX) > 1e-3) {
      const right = new THREE.Vector3().crossVectors(dir.clone().negate(), cam.up).normalize();
      if (right.lengthSq() < 1e-6) right.set(1, 0, 0);
      const tanH = Math.tan((cam.fov * DEG) / 2) * cam.aspect;
      const d = right.multiplyScalar(2 * tanH * fit.dist * shiftX);
      fit.target.add(d);
      fit.pos.add(d);
    }
    return fit;
  }
  if (kind === "hero" || kind === "iso" || kind === "scene") {
    return fitPose(box, sceneDir() ?? HERO_DIR.clone().normalize(), cam, 1, sceneFill(box), 0.05);
  }
  const dir =
    kind === "top"
      ? new THREE.Vector3(0, -0.0001, 1)
      : kind === "bottom"
        ? // keyboards and most two-sided boards carry their circuit (diodes, sockets, routing) on the back
          new THREE.Vector3(0, -0.0001, -1)
        : kind === "front"
        ? new THREE.Vector3(0, -1, 0.18)
        : new THREE.Vector3(1, 0, 0.18);
  return fitPose(box, dir.normalize(), cam, 1, sizedFill(box, 0.56), 0.05);
}

/** How far the picked part lifts out of its layer, mm. */
function pickLift(): number {
  return Math.max(6, stage.gap * 0.4);
}

/**
 * Measures how tall each exploded layer really is (as built), a few times a second, and works out
 * how far each lifts so no two layers overlap. Idle while a part is out in focus or picked.
 */
function LayerMeasure() {
  const { invalidate } = useThree();
  const n = useRef(0);
  useFrame(() => {
    if (++n.current % 12 !== 0 || stage.focusK > 0 || stage.pickK > 0.002) return;
    const ext: Partial<Record<LayerId, LayerExtent>> = {};
    for (const [g, layer] of stage.layerGroups) {
      if (!g.visible) continue;
      g.updateMatrixWorld(true);
      const b = meshBox(g);
      if (b.isEmpty()) continue;
      const dz = g.matrixWorld.elements[14];
      const cur = ext[layer];
      ext[layer] = [Math.min(cur?.[0] ?? Infinity, b.min.z - dz), Math.max(cur?.[1] ?? -Infinity, b.max.z - dz)];
    }
    const next = layerOffsets(ext, Math.max(6, stage.gap * 0.45));
    const same = stage.layerZ && Object.keys(next).length === Object.keys(stage.layerZ).length && (Object.keys(next) as LayerId[]).every((l) => Math.abs((stage.layerZ?.[l] ?? NaN) - (next[l] ?? 0)) < 0.05);
    if (same) return;
    stage.layerZ = Object.keys(next).length ? next : null;
    stage.lift = Math.max(0, ...Object.values(next));
    stage.settleVersion++;
    invalidate();
  });
  return null;
}

/** The exploded view's hover: the part under the pointer (by focus key) is tinted. */
function HoverDriver() {
  const { gl, camera, invalidate } = useThree();
  useEffect(() => {
    const el = gl.domElement;
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let last: PointerEvent | null = null;
    let raf = 0;
    const set = (key: string | null) => {
      if (stage.hoverKey === key) return;
      stage.hoverKey = key;
      invalidate();
    };
    const run = () => {
      raf = 0;
      if (!last || !stage.root || useApp.getState().explode <= 0.5 || useSim.getState().active) return set(null);
      const r = el.getBoundingClientRect();
      ndc.set(((last.clientX - r.left) / r.width) * 2 - 1, -((last.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      for (const hit of ray.intersectObject(stage.root, true)) {
        for (let o: THREE.Object3D | null = hit.object; o; o = o.parent) {
          const key = stage.layerGroups.has(o as THREE.Group) ? stage.focusGroups.get(o as THREE.Group) : undefined;
          if (key) return set(key);
        }
      }
      set(null);
    };
    const move = (e: PointerEvent) => {
      last = e;
      if (!raf) raf = requestAnimationFrame(run);
    };
    const leave = () => {
      last = null;
      set(null);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
      cancelAnimationFrame(raf);
      stage.hoverKey = null;
    };
  }, [gl, camera, invalidate]);
  return null;
}

/** The picked part's name and what it does, floating beside it in the exploded view. */
function PickTag() {
  const key = useApp((s) => s.focusKey);
  const exploded = useApp((s) => s.explode > 0.5);
  const build = useApp((s) => s.build);
  const info = useMemo(() => {
    const row = labelRows(build).find((r) => r.key === key);
    const part = build?.parts.find((p) => partLabel(p).key === key);
    if (!row) return null;
    const what = part?.card.summary ?? row.detail;
    return { title: row.title, what: what && what.length > 96 ? `${what.slice(0, 93)}...` : what, qty: row.quantity };
  }, [build, key]);
  const ref = useRef<THREE.Group>(null);
  const box = useMemo(() => new THREE.Box3(), []);
  useFrame(() => {
    const g = ref.current;
    if (!g || !key) return;
    box.makeEmpty();
    for (const [grp, k] of stage.focusGroups) if (k === key) box.union(meshBox(grp));
    if (!box.isEmpty()) g.position.set(box.max.x, (box.min.y + box.max.y) / 2, (box.min.z + box.max.z) / 2);
  });
  if (!key || !exploded || !info) return null;
  return (
    <group ref={ref}>
      <Html zIndexRange={[24, 0]} style={{ pointerEvents: "none" }}>
        <div className="pick-tag">
          <b>{info.qty > 1 ? `${info.title} x${info.qty}` : info.title}</b>
          {info.what && <span>{info.what}</span>}
        </div>
      </Html>
    </group>
  );
}

let rankMax = LAYER_RANK.keycaps;
function maxRank(): number {
  return rankMax;
}

interface OrbitLike extends THREE.EventDispatcher<{ start: object; change: object; end: object }> {
  target: THREE.Vector3;
  update: () => void;
}

/** Eases the explode factor toward the slider value; flags settle for shadows and framing. */
function ExplodeDriver() {
  const target = useApp((s) => s.explode);
  useFrame((_, dt) => {
    const d = target - stage.explode;
    if (Math.abs(d) < 0.0015) {
      if (stage.moving) {
        stage.explode = target;
        stage.moving = false;
        stage.settleVersion++;
      }
      return;
    }
    stage.moving = true;
    stage.explode += d * (1 - Math.exp(-dt * 5.5));
  });
  return null;
}

/**
 * Hero 3/4 framing auto-fitted to the loaded assembly; re-fits as models load
 * until the user orbits. The explode hold frames the whole stack, side-on,
 * shifted left to leave room for the label column.
 */
function CameraRig() {
  const { camera, controls, size } = useThree();
  const cam = camera as THREE.PerspectiveCamera;
  const preset = useApp((s) => s.preset);
  const nonce = useApp((s) => s.cameraNonce);
  const sceneCam = useApp((s) => s.build?.scene?.camera ?? null);
  const buildId = useApp((s) => s.build?.build_id ?? null);
  const partsCount = useApp((s) => s.build?.parts.length ?? 0);
  const explodeTarget = useApp((s) => s.explode);
  const sceneDevices = useApp((s) => s.companions.join(","));
  const content = useApp((s) => `${s.build?.parts.length ?? 0}:${s.build?.enclosures?.length ?? 0}:${s.build?.boards?.length ?? 0}:${s.build?.revision ?? 0}`);
  const anim = useRef<{ fromP: THREE.Vector3; fromT: THREE.Vector3; toP: THREE.Vector3; toT: THREE.Vector3; t: number } | null>(null);
  const userMoved = useRef(false);
  const framedFor = useRef<string | null>(null);
  const shift = useRef(0);
  const mode = useRef<"hero" | "exploded">("hero");
  const simActive = useSim((s) => s.active);
  const savedCam = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 } | null>(null);
  const start = (asked: FrameKind, predict: number | null = null) => {
    const ctl = controls as unknown as OrbitLike | null;
    // while simulating, every refit (models loading, content changing) keeps the operating view
    const sim = useSim.getState().active;
    const kind = sim ? "sim" : asked;
    const to = framePose(kind, cam, sim ? 0 : predict);
    cam.near = Math.max(0.5, to.dist * 0.02);
    cam.far = to.dist * 20;
    cam.updateProjectionMatrix();
    anim.current = { fromP: cam.position.clone(), fromT: ctl?.target.clone() ?? new THREE.Vector3(), toP: to.pos, toT: to.target, t: 0 };
  };
  const heroOrPreset = (): FrameKind => (preset === "scene" || preset === "iso" ? "hero" : preset);
  useEffect(() => {
    const ctl = controls as unknown as OrbitLike | null;
    if (!ctl) return;
    const on = () => {
      if (!anim.current) userMoved.current = true;
    };
    ctl.addEventListener("start", on);
    return () => ctl.removeEventListener("start", on);
  }, [controls]);
  useEffect(() => {
    const ctl = controls as unknown as OrbitLike | null;
    if (simActive) {
      savedCam.current = { pos: cam.position.clone(), target: ctl?.target.clone() ?? new THREE.Vector3() };
      start("sim");
    } else if (savedCam.current) {
      const back = savedCam.current;
      savedCam.current = null;
      anim.current = { fromP: cam.position.clone(), fromT: ctl?.target.clone() ?? new THREE.Vector3(), toP: back.pos, toT: back.target, t: 0 };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simActive]);
  useEffect(() => {
    // While playing, the play panel, the terminal and the outputs dock arrive and resize after the
    // glide starts (the firmware boots first): re-fit whenever that layout changes, so the device
    // always sits in the free area and never under the terminal or the panel.
    if (!simActive) return;
    const sig = () => {
      const r = (s: string) => {
        const b = document.querySelector<HTMLElement>(s)?.getBoundingClientRect();
        return b ? `${Math.round(b.left)},${Math.round(b.top)},${Math.round(b.width)},${Math.round(b.height)}` : "-";
      };
      return `${window.innerWidth}x${window.innerHeight}|${r(".viewport canvas")}|${r(".play-panel")}|${r(".sim-terminal")}|${r(".play-dock")}`;
    };
    let last = sig();
    const id = window.setInterval(() => {
      const now = sig();
      if (now === last) return;
      last = now;
      if (!userMoved.current) start("sim");
    }, 250);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [simActive]);
  useEffect(() => {
    if (sceneCam && !userMoved.current && stage.explode < 0.05) start(heroOrPreset());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneCam]);
  useEffect(() => {
    userMoved.current = false;
    start(stage.explode > 0.5 && (preset === "scene" || preset === "iso") ? "exploded" : heroOrPreset());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce]);
  useEffect(() => {
    // A device added to (or taken from) the scene: ease the camera to the new arrangement, even
    // if the view was orbited, so the new arrangement is always seen whole.
    if (framedFor.current === null) return;
    userMoved.current = false;
    // after the new device has slid into place, so it is framed where it ends up
    const id = window.setTimeout(() => start(mode.current === "exploded" ? "exploded" : heroOrPreset()), 450);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneDevices]);
  useEffect(() => {
    // Frame the first parts of a new build before scene.ready arrives.
    if (!buildId || partsCount === 0 || framedFor.current === buildId) return;
    framedFor.current = buildId;
    userMoved.current = false;
    const id = requestAnimationFrame(() => start("hero"));
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildId, partsCount]);
  useEffect(() => {
    // Parts, cases and boards keep arriving while the build streams: re-fit until the user orbits.
    if (userMoved.current || stage.moving || framedFor.current === null) return;
    const id = requestAnimationFrame(() => start(mode.current === "exploded" ? "exploded" : heroOrPreset()));
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content]);
  useEffect(() => {
    // Re-fit as real meshes replace placeholders (boxes are a guess at size).
    let raf = 0;
    const off = onModelsChanged(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        if (!userMoved.current && !stage.moving) start(mode.current === "exploded" ? "exploded" : heroOrPreset());
      });
    });
    return () => {
      off();
      cancelAnimationFrame(raf);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset]);
  useEffect(() => {
    const next = explodeTarget >= 0.9 ? "exploded" : explodeTarget <= 0.1 ? "hero" : null;
    if (!next || next === mode.current) return;
    mode.current = next;
    userMoved.current = false;
    start(next === "exploded" ? "exploded" : heroOrPreset(), explodeTarget);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [explodeTarget]);
  useFrame((_, dt) => {
    // Label column room: shift the projection, not the camera, so orbit stays centred on the model.
    // no label column while a part is in focus, so the view centres again
    const want = labelOpacity(stage.explode) * (1 - focusAmount()) * LABEL_SHIFT;
    if (Math.abs(want - shift.current) > 1e-4) {
      shift.current = want;
      if (want > 0) cam.setViewOffset(size.width, size.height, size.width * want, 0, size.width, size.height);
      else cam.clearViewOffset();
    }
    const a = anim.current;
    const ctl = controls as unknown as OrbitLike | null;
    stage.animating = !!a;
    if (!a) return;
    a.t = Math.min(1, a.t + dt / 0.9);
    const k = 1 - Math.pow(1 - a.t, 3);
    cam.position.lerpVectors(a.fromP, a.toP, k);
    if (ctl) {
      ctl.target.lerpVectors(a.fromT, a.toT, k);
      ctl.update();
    } else cam.lookAt(a.toT);
    if (a.t >= 1) anim.current = null;
  });
  useEffect(() => {
    if (shift.current > 0) cam.setViewOffset(size.width, size.height, size.width * shift.current, 0, size.width, size.height);
  }, [size.width, size.height, cam]);
  return null;
}

const USER_QUIET_MS = 6000;
const AGENT_HOME_MS = 1500;
const AGENT_EASE_S = 0.8;
const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Drifts the camera toward the part the agent on stage works on (agentFocus), and back to
 * the rig's framing 1.5 s after it lets go. Never while the user has touched the view or
 * picked a preset in the last 6 s, while the explode is open, the MoveGizmo is up, the rig
 * is easing, or the user prefers reduced motion. Runs after CameraRig in the frame order.
 */
function AgentCam() {
  const { camera, controls, gl, invalidate } = useThree();
  const cam = camera as THREE.PerspectiveCamera;
  const focus = useApp((s) => s.agentFocus);
  const nonce = useApp((s) => s.cameraNonce);
  const touched = useRef(-Infinity);
  const drifted = useRef(false);
  const anim = useRef<{ fromP: THREE.Vector3; fromT: THREE.Vector3; toP: THREE.Vector3; toT: THREE.Vector3; t: number } | null>(null);
  useEffect(() => {
    const ctl = controls as unknown as OrbitLike | null;
    const el = gl.domElement;
    const on = () => {
      touched.current = performance.now();
      anim.current = null;
      drifted.current = false;
    };
    el.addEventListener("pointerdown", on, { passive: true });
    el.addEventListener("wheel", on, { passive: true });
    ctl?.addEventListener("start", on);
    return () => {
      el.removeEventListener("pointerdown", on);
      el.removeEventListener("wheel", on);
      ctl?.removeEventListener("start", on);
    };
  }, [controls, gl]);
  const lastNonce = useRef(nonce);
  useEffect(() => {
    if (lastNonce.current === nonce) return;
    lastNonce.current = nonce;
    touched.current = performance.now();
    anim.current = null;
    drifted.current = false;
  }, [nonce]);
  useEffect(() => {
    const blocked = () => {
      const s = useApp.getState();
      return reducedMotion() || performance.now() - touched.current < USER_QUIET_MS || !!s.moving || s.explode > 0.05 || stage.explode > 0.05 || (stage.animating && !anim.current);
    };
    const go = (toP: THREE.Vector3, toT: THREE.Vector3) => {
      const ctl = controls as unknown as OrbitLike | null;
      if (!ctl) return;
      anim.current = { fromP: cam.position.clone(), fromT: ctl.target.clone(), toP, toT, t: 0 };
      invalidate();
    };
    if (focus) {
      const ctl = controls as unknown as OrbitLike | null;
      const box = partWorldBox(focus, new THREE.Box3());
      if (!ctl || !box || blocked()) return;
      const to = agentPose(cam.position, ctl.target, box, cam.fov, cam.aspect);
      drifted.current = true;
      go(to.pos, to.target);
      return;
    }
    if (!drifted.current) return;
    const id = window.setTimeout(() => {
      if (!drifted.current || blocked()) return;
      const p = useApp.getState().preset;
      const to = framePose(p === "scene" || p === "iso" ? "hero" : p, cam, null);
      drifted.current = false;
      go(to.pos, to.target);
    }, AGENT_HOME_MS);
    return () => window.clearTimeout(id);
  }, [focus, cam, controls, invalidate]);
  useFrame((_, dt) => {
    const a = anim.current;
    if (!a) return;
    // The rig's own ease (refit, preset, explode) wins; so does a gizmo or the explode opening.
    if (stage.animating || useApp.getState().moving || stage.explode > 0.05) {
      anim.current = null;
      return;
    }
    const ctl = controls as unknown as OrbitLike | null;
    stage.animating = true;
    a.t = Math.min(1, a.t + dt / AGENT_EASE_S);
    const k = easeOut(a.t);
    cam.position.lerpVectors(a.fromP, a.toP, k);
    if (ctl) {
      ctl.target.lerpVectors(a.fromT, a.toT, k);
      ctl.update();
    }
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

// ---------------------------------------------------------------- scene

/** PCB part instances drawn by a board GLB instead (avoids a double board). */
function boardDrawnPcbs(build: Build | null): Set<string> {
  const out = new Set<string>();
  for (const b of build?.boards ?? []) if (b.part_instance_id && boardModelUrl(b)) out.add(b.part_instance_id);
  return out;
}

function footprintMm(build: Build | null): number {
  const bb = build?.scene?.assembly_bbox_mm;
  const sides = new Set((build?.parts ?? []).map((p) => p.side).filter((s) => s === "left" || s === "right"));
  if (bb?.min && bb?.max) {
    const x = (bb.max[0] - bb.min[0]) / (sides.size === 2 ? 2 : 1);
    return Math.max(x, bb.max[1] - bb.min[1]);
  }
  return 120;
}

export interface LabelRowData extends PartLabel {
  quantity: number;
}

/** The focus (and label) key a part belongs to: a PCB drawn from the board GLB focuses as the board. */
export function focusKeyOf(build: Build | null, part: BuildPart): string {
  return boardDrawnPcbs(build).has(part.instance_id) ? "b:board" : partLabel(part).key;
}

/** One label per catalog part, plus the case and any board drawn from its GLB. */
export function labelRows(build: Build | null): LabelRowData[] {
  if (!build) return [];
  const hidden = boardDrawnPcbs(build);
  const rows = new Map<string, LabelRowData>();
  for (const p of build.parts) {
    if (hidden.has(p.instance_id)) continue;
    const l = partLabel(p);
    if (!modelAsset(p.assets, p.quantity > 1)) l.sub += " · no 3D model yet";
    const prev = rows.get(l.key);
    if (prev) prev.quantity += p.quantity;
    else rows.set(l.key, { ...l, quantity: p.quantity });
  }
  const boards = build.boards?.filter((b) => !b.part_instance_id || hidden.has(b.part_instance_id)) ?? [];
  if (boards.length) {
    const routed = boards.some((b) => b.routing?.method === "autorouted" || b.routing?.status === "routed");
    rows.set("b:board", {
      key: "b:board",
      title: "PCB",
      detail: routed ? "routed, KiCad" : "",
      sub: boards.some((b) => b.source === "design") ? "from the source design" : "designed by us",
      generated: boards.every((b) => b.source !== "design"),
      quantity: boards.length,
    });
  }
  const encs = (build.enclosures ?? []).filter((e) => e.kind !== "none");
  if (encs.length) {
    const generated = encs.some((e) => e.kind === "generated");
    const sub = generated ? "designed by us" : "from the source design";
    // A generated case is a tray plus a bezel; the bezel row shows only when its piece exists (labels hide rows without an anchor).
    rows.set("e:case_top", { key: "e:case_top", title: "Case top", detail: "", sub, generated, quantity: encs.length });
    rows.set("e:case", { key: "e:case", title: generated ? "Case bottom" : "Case", detail: "", sub, generated, quantity: encs.length });
  }
  return [...rows.values()];
}

const NO_COVER = new Set<string>();

// ---------------------------------------------------------------- companion devices

function assemblyBox(build: Build | null): THREE.Box3 | null {
  const bb = build?.scene?.assembly_bbox_mm;
  if (!bb?.min || !bb?.max) return null;
  return new THREE.Box3(new THREE.Vector3(bb.min[0], bb.min[1], bb.min[2]), new THREE.Vector3(bb.max[0], bb.max[1], bb.max[2]));
}

interface CompanionPick {
  onClick: (e: ThreeEvent<MouseEvent>) => void;
  onHover: (on: boolean) => void;
}

/** One part of a device standing beside the build: its model where the build placed it, nothing else. */
function CompanionPart(props: { part: BuildPart; build: Build; pick: CompanionPick }) {
  const { part, build } = props;
  const layout = (build.layouts ?? []).find((l) => l.layout_id === part.placement.layout_id);
  const poses = useMemo(() => elementPoses(part.placement, part.quantity, layout), [part.placement, part.quantity, layout]);
  const model = useModel(modelAsset(part.assets, poses.length > 1)?.url ?? null, isBoardPart(part));
  const loaded = model.status === "ready" && model.model.groups.length > 0 ? model.model : null;
  const preset = presetFor(part);
  const color = defaultColor(part);
  const catalog = useCatalogBbox(part.part_id);
  // a device beside this one keeps its keycaps and knobs too, drawn as their shape when there is no model
  const standIn = useMemo(() => {
    if (loaded || !hasStandIn(part, preset)) return null;
    const box = placeholderBox(part, { layouts: build.layouts ?? [], boards: build.boards ?? [], parts: build.parts, catalogBbox: catalog });
    return preset === "keycap" ? keycapGeometry(box) : knobGeometry(box);
  }, [loaded, part, preset, build, catalog]);
  useEffect(() => () => standIn?.dispose(), [standIn]);
  const groups = useMemo<MeshGroup[]>(() => {
    if (!loaded) return standIn ? [{ geometry: standIn, material: presetMaterial(preset, color), weight: 0 }] : [];
    if (usesPreset(preset)) {
      const mat = presetMaterial(preset, color);
      return loaded.groups.map((g) => ({ ...g, material: mat }));
    }
    if (loaded.groups.length === 1 && part.color?.hex && !loaded.groups[0].material.map) return [{ ...loaded.groups[0], material: tinted(loaded.groups[0].material, part.color.hex) }];
    return loaded.groups;
  }, [loaded, preset, color, part.color?.hex, standIn]);
  const matrices = useMemo(() => poses.map((p) => elementMatrix(p)), [poses]);
  if (!groups.length) return null;
  return <InstancedGroups groups={groups} matrices={matrices} onClick={props.pick.onClick} onHover={props.pick.onHover} />;
}

function CompanionBoard(props: { board: Board; pick: CompanionPick }) {
  const model = useModel(boardModelUrl(props.board), true);
  const loaded = model.status === "ready" && model.model.groups.length > 0 ? model.model : null;
  const pos = props.board.position_mm ?? [0, 0, 0];
  const rot = props.board.rotation_deg ?? [0, 0, 0];
  if (!loaded) return null;
  return (
    <group position={[pos[0], pos[1], pos[2]]} rotation={new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG, "XYZ")}>
      {loaded.groups.map((g) => (
        <mesh key={`${g.geometry.uuid}:${g.material.uuid}`} geometry={g.geometry} material={g.material} onClick={props.pick.onClick} onPointerOver={(e) => (e.stopPropagation(), props.pick.onHover(true))} onPointerOut={() => props.pick.onHover(false)} />
      ))}
    </group>
  );
}

/** The case as the assembled build shows it: a translucent shell with its creases drawn. */
function CompanionCase(props: { enc: Enclosure; pick: CompanionPick }) {
  const { enc } = props;
  const model = useModel(modelAsset(enc.assets, false)?.url ?? null);
  const loaded = model.status === "ready" && model.model.groups.length > 0 ? model.model : null;
  const geoms = useMemo(() => (loaded ? casePieces(loaded).flatMap((p) => p.geoms) : []), [loaded]);
  const hex = caseHex(enc);
  const material = useMemo(() => {
    const m = presetMaterial("case", hex).clone();
    m.transparent = true;
    m.opacity = 0.24;
    m.depthWrite = false;
    return m;
  }, [hex]);
  useEffect(() => () => material.dispose(), [material]);
  const edges = useMemo(() => geoms.map((g) => new THREE.EdgesGeometry(g, 40)), [geoms]);
  useEffect(() => () => edges.forEach((e) => e.dispose()), [edges]);
  const edgeMat = useMemo(() => new THREE.LineBasicMaterial({ color: "#1F2226", transparent: true, opacity: 0.3, depthWrite: false, toneMapped: false }), []);
  useEffect(() => () => edgeMat.dispose(), [edgeMat]);
  const pos = enc.position_mm ?? [0, 0, 0];
  const rot = enc.rotation_deg ?? [0, 0, 0];
  return (
    <group position={[pos[0], pos[1], pos[2]]} rotation={new THREE.Euler(rot[0] * DEG, rot[1] * DEG, rot[2] * DEG, "XYZ")}>
      {geoms.map((g) => (
        <mesh key={g.uuid} geometry={g} material={material} renderOrder={2} onClick={props.pick.onClick} onPointerOver={(e) => (e.stopPropagation(), props.pick.onHover(true))} onPointerOut={() => props.pick.onHover(false)} />
      ))}
      {edges.map((e) => (
        <lineSegments key={e.uuid} geometry={e} material={edgeMat} raycast={() => null} renderOrder={3} />
      ))}
    </group>
  );
}

/** Another device in this canvas's scene, display only: clicking it opens its own canvas. */
function CompanionDevice(props: { canvasId: string; build: Build; offset: THREE.Vector3; name: string }) {
  const { build } = props;
  const [hover, setHover] = useState(false);
  const pick = useMemo<CompanionPick>(
    () => ({
      onClick: (e) => {
        e.stopPropagation();
        document.body.style.cursor = "";
        switchCanvas(props.canvasId);
      },
      onHover: (on) => {
        setHover(on);
        document.body.style.cursor = on ? "pointer" : "";
      },
    }),
    [props.canvasId],
  );
  const boardGlb = (build.boards ?? []).some((b) => boardModelUrl(b));
  const hiddenPcbs = boardDrawnPcbs(build);
  // with the routed board drawn, what it already carries (its parts, the bare PCB) is not drawn twice
  const parts = build.parts.filter((p) => !hiddenPcbs.has(p.instance_id) && !(boardGlb && (layerOf(p) === "board_parts" || layerOf(p) === "pcb" || layerOf(p) === "under")));
  const box = assemblyBox(build);
  // a device added to the scene slides in from the side to its place, and moves to a new one when the row changes
  const slide = useRef<THREE.Group>(null);
  const { invalidate } = useThree();
  const entered = useRef(false);
  useLayoutEffect(() => {
    if (entered.current || !slide.current) return;
    entered.current = true;
    slide.current.position.copy(props.offset).add(new THREE.Vector3(70, 0, 0));
  }, [props.offset]);
  useFrame((_, dt) => {
    const g = slide.current;
    if (!g || g.position.distanceToSquared(props.offset) < 0.01) return;
    g.position.lerp(props.offset, reducedMotion() ? 1 : 1 - Math.exp(-dt * 6));
    invalidate();
  });
  const tag = box ? new THREE.Vector3((box.min.x + box.max.x) / 2, (box.min.y + box.max.y) / 2, box.max.z + 6) : new THREE.Vector3(0, 0, 30);
  return (
    <group ref={slide} position={props.offset} userData={{ companion: props.canvasId }}>
      {parts.map((p) => (
        <CompanionPart key={p.instance_id} part={p} build={build} pick={pick} />
      ))}
      {(build.boards ?? []).map((b) => (
        <CompanionBoard key={b.board_id} board={b} pick={pick} />
      ))}
      {(build.enclosures ?? [])
        .filter((e) => e.kind !== "none")
        .map((e) => (
          <CompanionCase key={e.enclosure_id} enc={e} pick={pick} />
        ))}
      <Html position={tag} center zIndexRange={[4, 0]} style={{ pointerEvents: "none" }}>
        <span className={`companion-tag ${hover ? "on" : ""}`}>{hover ? `Open ${props.name}` : props.name}</span>
      </Html>
    </group>
  );
}

/**
 * The other devices of this canvas's scene ("add a mouse to the keyboard"), stood to the right of
 * it on the same floor, centres in line, a gap apart. They step away while the build is pulled
 * apart or a part is in focus: those views are about this one device.
 */
function CompanionRow() {
  const ids = useApp(useShallow((s) => s.companions));
  const others = useApp(useShallow((s) => s.companions.map((id) => s.canvasStash[id]?.build ?? null)));
  const names = useApp(useShallow((s) => s.companions.map((id) => s.canvases.find((c) => c.id === id)?.name ?? s.canvasStash[id]?.build?.prompt ?? "")));
  const active = useApp((s) => s.build);
  const away = useApp((s) => s.focusKey !== null || s.explode > 0.5);
  const ref = useRef<THREE.Group>(null);
  useLayoutEffect(() => {
    stage.companions = ref.current;
    return () => {
      stage.companions = null;
    };
  }, []);
  const activeId = useApp((s) => s.activeCanvas);
  const slots = useMemo(() => {
    // arrange.ts stands the devices on the floor by their sizes; the open one stays at its origin,
    // so switching tabs never moves the device being worked on
    const here = assemblyBox(active) ?? fallbackBox();
    const guess = new THREE.Box3(new THREE.Vector3(-40, -40, 0), new THREE.Vector3(40, 40, 20));
    const boxes = [here, ...ids.map((_, i) => assemblyBox(others[i]) ?? guess)].map(toBox);
    const at = arrangeDevices(boxes);
    return ids.map((id, i) => ({
      id,
      build: others[i],
      offset: new THREE.Vector3(at[i + 1][0] - at[0][0], at[i + 1][1] - at[0][1], at[i + 1][2] - at[0][2]),
    }));
  }, [ids, others, active]);
  useEffect(() => {
    stage.settleVersion++;
  }, [slots, away]);
  // The open device sits at its own origin; links run between it and the companions.
  const linkSlots = useMemo(() => [{ id: activeId, build: active, offset: new THREE.Vector3() }, ...slots], [activeId, active, slots]);
  return (
    <group ref={ref}>
      {!away &&
        slots.map((sl) =>
          sl.build ? <CompanionDevice key={sl.id} canvasId={sl.id} build={sl.build} offset={sl.offset} name={shortName(names[ids.indexOf(sl.id)])} /> : null,
        )}
      {!away && <ProjectLinkLines slots={linkSlots} />}
      <AutoLinker />
    </group>
  );
}

/** "a wireless mouse with a scroll wheel" reads as "Wireless mouse" on its tag. */
function shortName(prompt: string): string {
  const t = prompt.replace(/^(?:an?|the|make|build|create)\s+/i, "").split(/\s+(?:with|that|for|to)\s+/i)[0].trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1, 40) : "Device";
}

function SceneContents(props: {
  gizmoMode: "translate" | "rotate";
  theme: Theme;
  palette: StudioPalette;
  boardOnly: boolean;
  post: boolean;
  onFit: (overhangMm: number) => void;
}) {
  const { theme } = props;
  const build = useApp((s) => s.build);
  const placeDone = useApp((s) => s.view.placeDone);
  const selection = useApp((s) => s.selection);
  const resizeTarget = useApp((s) => s.resizeTarget);
  const overlay = useApp((s) => s.overlay);
  const hoverConn = useApp((s) => s.hoverConnection);
  const toggles = useApp((s) => s.toggles);
  const dragPose = useApp((s) => s.dragPose);
  const agentFocus = useApp((s) => s.agentFocus);
  const rootRef = useRef<THREE.Group>(null);
  useLayoutEffect(() => {
    stage.root = rootRef.current;
    return () => {
      stage.root = null;
    };
  }, []);
  const preload = build?.scene?.preload;
  useEffect(() => preloadModels(preload), [preload]);
  const failing = useMemo(() => failingByInstance(build), [build]);
  const failingEnclosures = useMemo(() => {
    const out = new Set<string>();
    for (const c of build?.checks ?? []) {
      if (c.status !== "fail") continue;
      for (const s of c.subjects ?? []) if (s.enclosure_id) out.add(s.enclosure_id);
    }
    return out;
  }, [build?.checks]);
  const hoverLabel = useApp((s) => s.hoverLabel);
  const hoverEnds = useMemo(() => {
    const c = build?.connections.find((x) => x.connection_id === hoverConn);
    return new Set(c ? [c.from.instance_id, c.to.instance_id] : []);
  }, [build?.connections, hoverConn]);
  const parts = useMemo(() => build?.parts ?? [], [build?.parts]);
  const layouts = build?.layouts ?? [];
  const boards = build?.boards ?? [];
  const hiddenPcbs = useMemo(() => boardDrawnPcbs(build), [build]);
  stage.gap = layerGap(footprintMm(build));
  const hasCase = toggles.case && !props.boardOnly && (build?.enclosures ?? []).some((e) => e.kind !== "none");
  rankMax = Math.max(
    parts.reduce((m, p) => Math.max(m, LAYER_RANK[layerOf(p)]), LAYER_RANK.case),
    hasCase ? LAYER_RANK.lid : 0,
  );
  // Parts a routed board GLB may already show (it carries every footprint's model).
  const candidates = useMemo<BoardCandidate[]>(() => {
    const out: BoardCandidate[] = [];
    for (const p of parts) {
      if (hiddenPcbs.has(p.instance_id) || String(p.card.kind) === "pcb" || isKeycapPart(p) || usesPreset(presetFor(p))) continue;
      const layout = layouts.find((l) => l.layout_id === p.placement.layout_id);
      const points = elementPoses(p.placement, p.quantity, layout).map((e) => new THREE.Vector3(e.position[0], e.position[1], e.position[2]));
      out.push({ instanceId: p.instance_id, layer: layerOf(p), points });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parts, hiddenPcbs, build?.layouts]);
  const [coveredBy, setCoveredBy] = useState<Record<string, string[]>>({});
  const onCovered = useCallback((boardId: string, ids: string[]) => {
    setCoveredBy((prev) => ((prev[boardId] ?? []).join("|") === ids.join("|") ? prev : { ...prev, [boardId]: ids }));
  }, []);
  const covered = useMemo(() => new Set(Object.values(coveredBy).flat()), [coveredBy]);
  // The first instance of each catalog part carries its label anchor.
  const anchorOwner = useMemo(() => {
    const owner = new Map<string, string>();
    for (const p of parts) {
      if (hiddenPcbs.has(p.instance_id)) continue;
      const k = partLabel(p).key;
      if (!owner.has(k)) owner.set(k, p.instance_id);
    }
    return owner;
  }, [parts, hiddenPcbs]);
  const boardOnly = props.boardOnly;
  const preset = useApp((s) => s.preset);
  const visible = parts.filter((p) => {
    if (hiddenPcbs.has(p.instance_id)) return false;
    const pcb = String(p.card.kind) === "pcb";
    if (boardOnly) return pcb;
    return (toggles.keycaps || !isKeycapPart(p)) && (toggles.board || !pcb);
  });
  const showCase = toggles.case && !boardOnly;
  const showBoard = toggles.board || boardOnly;
  const simOn = useSim((s) => s.active);
  // with a part pulled out, its shelf of the rest takes the top left: the view cube steps away
  const focusing = useApp((s) => s.focusKey !== null);
  const revision = `${build?.build_id ?? ""}:${build?.revision ?? 0}:${parts.length}:${showCase}:${showBoard}:${toggles.keycaps}:${covered.size}`;
  return (
    <>
      <StudioEnvironment palette={props.palette} post={props.post} />
      {preset !== "bottom" && <StudioFloor palette={props.palette} revision={revision} grid={!simOn && !SHOT_ID} />}
      <ExplodeDriver />
      <LayerMeasure />
      <HoverDriver />
      <PickTag />
      <FocusDriver />
      <SimDriver />
      <group ref={rootRef}>
        {visible.map((p) => (
          <PartNode
            key={p.instance_id}
            part={p}
            layout={layouts.find((l) => l.layout_id === p.placement.layout_id)}
            layouts={layouts}
            boards={boards}
            parts={parts}
            provisional={!placeDone}
            selected={selection === p.instance_id}
            failing={failing.has(p.instance_id)}
            highlight={hoverEnds.has(p.instance_id) || hoverLabel === partLabel(p).key}
            focus={agentFocus === p.instance_id}
            labels={toggles.labels}
            theme={theme}
            pose={dragPose && dragPose.instance_id === p.instance_id ? dragPose : null}
            labelKey={anchorOwner.get(partLabel(p).key) === p.instance_id ? partLabel(p).key : null}
            covered={showBoard && covered.has(p.instance_id)}
          />
        ))}
        {showCase &&
          (build?.enclosures ?? []).map((e) => (
            <EnclosureNode
              key={e.enclosure_id}
              enc={e}
              theme={theme}
              selected={overlay === "resize" && resizeTarget?.enclosure_id === e.enclosure_id}
              failing={failingEnclosures.has(e.enclosure_id)}
              labelled
            />
          ))}
        {showBoard &&
          boards
            .filter((b) => !b.part_instance_id || hiddenPcbs.has(b.part_instance_id))
            .map((b, i) => (
              <BoardNode key={b.board_id} board={b} labelKey={i === 0 ? "b:board" : null} candidates={candidates} onCovered={onCovered} parts={parts} theme={theme} />
            ))}
      </group>
      <CompanionRow />
      <SimCaps covered={showBoard ? covered : NO_COVER} />
      <SimScreens />
      <MoveGizmo mode={props.gizmoMode} />
      <CameraRig />
      <AgentCam />
      <LabelProjector />
      <AgentTargetProbe />
      <DemandDriver />
      <FitCheck onResult={props.onFit} />
      {props.post && <StudioPost dark={false} />}
      {/* View cube, top left. Build space is Z up: +Y is the back face, -Y the front. */}
      {!simOn && !SHOT_ID && !focusing && (
        <GizmoHelper alignment="top-left" margin={[64, 64]} renderPriority={2}>
          <GizmoViewcube faces={["Right", "Left", "Back", "Front", "Top", "Bottom"]} color="#F4F5F7" textColor="#5B6470" strokeColor="#B9C0C8" hoverColor="#CFE3F7" opacity={1} />
        </GizmoHelper>
      )}
    </>
  );
}

export function Viewport3D() {
  // A board streamed as pending before any part still counts as something on stage.
  const hasParts = useApp((s) => (s.build?.parts.length ?? 0) + (s.build?.boards?.length ?? 0) > 0);
  const status = useApp((s) => s.build?.status);
  const missingCount = useApp((s) => (s.build?.parts ?? []).filter((p) => !modelAsset(p.assets, p.quantity > 1)).length);
  const modelsLoading = useModelsLoading();
  const build = useApp((s) => s.build);
  const rows = useMemo(() => labelRows(build), [build]);
  const theme = useTheme();
  const palette = useMemo(() => studioPalette(), []);
  const [gizmoMode, setGizmoMode] = useState<"translate" | "rotate">("translate");
  const [boardOnly, setBoardOnly] = useState(false);
  const [misfit, setMisfit] = useState(0);
  const simOn = useSim((s) => s.active);
  useEffect(() => {
    if (simOn) setBoardOnly(false);
  }, [simOn]);
  // a part pulled out into focus has left its case on purpose: the fit check does not apply
  const focusOn = useApp((s) => s.focusKey !== null);
  // Narrow viewports get a compact toolbar so it stays one row and never covers the prompt bar.
  const vpRef = useRef<HTMLDivElement>(null);
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const el = vpRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setCompact(e.contentRect.width < 760));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const post = useMemo(postEnabled, []);
  const overlayRows = useMemo(
    () => rows.map((r) => ({ key: r.key, title: `${r.title} x${r.quantity}`, detail: r.detail, sub: r.sub, generated: r.generated })),
    [rows],
  );
  return (
    <div ref={vpRef} className="viewport" data-agent="viewport" style={{ background: palette.background }}>
      <Canvas
        dpr={[1, 2]}
        frameloop="demand"
        camera={{ up: [0, 0, 1], position: [-120, -380, 260], near: 1, far: 10000, fov: 32 }}
        onPointerMissed={(e) => {
          // a click on empty space steps back: out of focus first, then clears the selection
          // (R3F only reports a miss for a click, not for the end of an orbit drag)
          if (e.type !== "click") return;
          if (useApp.getState().focusKey) {
            // a click in a gap inside the part (between keys) keeps it out; only clearly empty space puts it back
            const r = (e.currentTarget as HTMLElement | null)?.getBoundingClientRect?.() ?? (e.target as HTMLElement).getBoundingClientRect();
            if (!nearFocused(e.clientX - r.left, e.clientY - r.top, r.width, r.height)) focusPart(null);
          } else select(null);
        }}
        gl={{ antialias: !post, preserveDrawingBuffer: true, powerPreference: "high-performance" }}
      >
        <SceneContents gizmoMode={gizmoMode} theme={theme} palette={palette} boardOnly={boardOnly} post={post} onFit={setMisfit} />
        <SimHotspotsHost />
        <OrbitControls makeDefault enableDamping dampingFactor={0.12} enabled={!simOn} />
      </Canvas>
      {hasParts && <LabelOverlay rows={overlayRows} color="#1B1D1F" muted="#5D6166" line="#7C8086" accent="#2E7D46" />}
      {!hasParts && (
        <div className="vp-empty">
          {status === "running" || status === "awaiting_input" ? "Parts appear here as they are chosen." : status === "failed" ? "No parts were placed." : "Describe a device to start."}
        </div>
      )}
      {hasParts && misfit > 0 && !focusOn && !simOn && (
        <div style={MISFIT_CHIP} role="status">
          <span className="chip solid tone-warn" title="The case model does not contain the board in plan view. It is shown as generated and needs regenerating.">
            Case does not fit the board: off by {misfit} mm
          </span>
        </div>
      )}
      {/* a stored build reopened: its models are still on their way */}
      {status === "done" && modelsLoading && (
        <span className="canvas-loading" role="status" aria-label="Loading the model" title={missingCount ? `${missingCount} parts have no model and are drawn as shapes` : undefined}>
          <i />
          <i />
        </span>
      )}
      <SimOverlay />
      <ViewportToolbar gizmoMode={gizmoMode} setGizmoMode={setGizmoMode} boardOnly={boardOnly} setBoardOnly={setBoardOnly} compact={compact} />
    </div>
  );
}

const MISFIT_CHIP: React.CSSProperties = { position: "absolute", top: 12, left: 0, right: 0, display: "flex", justifyContent: "center", pointerEvents: "none", zIndex: 4 };

/** Centre without the translate trick so the bar can use the full viewport width instead of half of it. */
const TOOLBAR_FIT: React.CSSProperties = {
  left: 12,
  right: 12,
  transform: "none",
  width: "fit-content",
  maxWidth: "calc(100% - 24px)",
  marginInline: "auto",
  overflowX: "auto",
  scrollbarWidth: "none",
};

/** C11 ViewportToolbar. */
function ViewportToolbar(props: {
  gizmoMode: "translate" | "rotate";
  setGizmoMode: (m: "translate" | "rotate") => void;
  boardOnly: boolean;
  setBoardOnly: (v: boolean) => void;
  compact: boolean;
}) {
  const explode = useApp((s) => s.explode);
  const toggles = useApp((s) => s.toggles);
  const preset = useApp((s) => s.preset);
  const moving = useApp((s) => s.moving);
  const hasScene = useApp((s) => !!s.build?.scene);
  const simOn = useSim((s) => s.active);
  const simReady = useApp((s) => canSimulate(s.build));
  // Only offer toggles that change something in this build (a smartwatch has no keycaps).
  const applies = useApp(
    useShallow((s) => {
      const b = s.build;
      return {
        case: !!b?.enclosures?.some((e) => e.kind !== "none"),
        board: !!b && ((b.boards?.length ?? 0) > 0 || b.parts.some((p) => layerOf(p) === "pcb")),
        keycaps: !!b?.parts.some((p) => isKeycapPart(p)),
        labels: !!b?.parts.length,
      };
    }),
  );
  const setPreset = (p: ViewPreset) => setView(p);
  const toggle = (k: keyof typeof toggles) => useApp.setState((s) => ({ toggles: { ...s.toggles, [k]: !s.toggles[k] } }));
  // folded into one small button until wanted: the canvas is the device, not a control panel
  const [open, setOpen] = useState(false);
  if (simOn) {
    return (
      <div className="vp-toolbar" role="toolbar" aria-label="Simulation" style={props.compact ? { ...TOOLBAR_FIT, gap: 4, padding: "4px 6px" } : TOOLBAR_FIT}>
        <button type="button" className="seg-btn active" aria-pressed onClick={exitSimulation} title="Leave simulation (Esc)">
          simulate
        </button>
        <span className="vp-sep" />
        <span className="small sim-hint">Click the device or use your keyboard. Esc leaves.</span>
      </div>
    );
  }
  if (!open) {
    return (
      <button type="button" className="vp-view-btn" onClick={() => setOpen(true)} title="View: explode, angles, what to show" aria-label="View options" aria-expanded={false}>
        <Glyph name="view" />
      </button>
    );
  }
  return (
    <div className="vp-toolbar" role="toolbar" aria-label="View" style={props.compact ? { ...TOOLBAR_FIT, gap: 4, padding: "4px 6px" } : TOOLBAR_FIT}>
      <button type="button" className="btn ghost sm icon vp-fold" onClick={() => setOpen(false)} title="Fold the view options" aria-label="Fold the view options">
        <Icon name="x" size={12} />
      </button>
      <label className="vp-explode">
        {!props.compact && <span className="small">Explode</span>}
        <input style={props.compact ? { width: 56 } : undefined} type="range" min={0} max={1} step={0.01} value={explode} onChange={(e) => {
            if (useApp.getState().focusKey) focusPart(null);
            useApp.setState({ explode: Number(e.target.value) });
          }} aria-label="Explode" />
      </label>
      <span className="vp-sep" />
      <div className="seg">
        {(["iso", "top", "bottom", "front", "side"] as const).map((p) => (
          <button key={p} type="button" className={`seg-btn ${preset === p ? "active" : ""}`} onClick={() => setPreset(p)}>
            {p}
          </button>
        ))}
      </div>
      <button type="button" className="btn ghost sm" disabled={!hasScene} onClick={() => setPreset("scene")} title="Reset to the hero view">
        Reset
      </button>
      <span className="vp-sep" />
      <div className="seg">
        {(["case", "board", "keycaps", "labels"] as const)
          .filter((k) => applies[k])
          .map((k) => (
          <button key={k} type="button" className={`seg-btn ${toggles[k] ? "active" : ""}`} aria-pressed={toggles[k]} onClick={() => toggle(k)}>
            {k}
          </button>
        ))}
        {applies.board && (
          <button
            type="button"
            className={`seg-btn ${props.boardOnly ? "active" : ""}`}
            aria-pressed={props.boardOnly}
            title="Show only the populated board"
            onClick={() => props.setBoardOnly(!props.boardOnly)}
          >
            {props.compact ? "pcb only" : "board only"}
          </button>
        )}
      </div>
      {simReady && (
        <>
          <span className="vp-sep" />
          <button type="button" className="seg-btn" aria-pressed={false} onClick={enterSimulation} title="Run the device: press its keys and buttons, see what it does">
            simulate
          </button>
        </>
      )}
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

const noFit = () => undefined;

/** The build drawn as the workspace draws it, for another canvas (the simulator): no toolbar, no move gizmo. */
export function DeviceScene() {
  const theme = useTheme();
  const palette = useMemo(() => studioPalette(), []);
  const post = useMemo(postEnabled, []);
  return <SceneContents gizmoMode="translate" theme={theme} palette={palette} boardOnly={false} post={post} onFit={noFit} />;
}
