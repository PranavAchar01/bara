// The 3D view of one open-source board, inside its detail panel: the board's own prerendered GLB (KiCad's
// export with every part's real library model, nodes named by refdes), turned with the pointer. The board
// is drawn the way Bara draws any KiCad board (three/assets restyleBoardScene: real mask colour, ENIG pads,
// silk, FR4, part bodies), under a soft room light with a contact shadow. Until the first real frame the
// board's KiCad render (the poster, shot from the same three-quarter angle) is shown at full strength, then
// the live view fades in over it, so the panel never opens empty or half drawn. A fetch that stalls or
// fails is retried; if it still fails the poster stays with a Retry chip. One WebGL context, open only while
// the panel is, drawing on demand. Picking a part here or in the list lights it in both.
import { Suspense, useEffect, useMemo, useRef, useState, type ComponentRef } from "react";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { boardGlbUrls } from "../library/openSource";
import { cachedLoad, MODEL_RETRY_DELAYS_MS, MODEL_TIMEOUT_MS, restyleBoardScene } from "../three/assets";
import { homeView } from "../three/boardView";
import "../styles/board3d.css";

const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);

/** The GLB's bytes per board, kept for the session: reopening a board parses again but never refetches. */
const bytes = new Map<string, Promise<ArrayBuffer | null>>();

/** The first source that answers: this site's own copy, then the board library's published one. */
function boardBytes(slug: string): Promise<ArrayBuffer | null> {
  return cachedLoad(
    bytes,
    slug,
    async () => {
      for (const url of boardGlbUrls(slug)) {
        const r = await fetch(url).catch(() => null);
        if (r?.ok) return r.arrayBuffer();
      }
      throw new Error("no source");
    },
    MODEL_TIMEOUT_MS,
  );
}

/** Start fetching a board before its panel opens (a card hovered or in view). */
export function prefetchBoard(slug: string): void {
  void boardBytes(slug);
}

async function loadBoard(slug: string): Promise<THREE.Group | null> {
  const buf = await boardBytes(slug);
  if (!buf) return null;
  try {
    const gltf = await loader.parseAsync(buf.slice(0), "");
    restyleBoardScene(gltf);
    return gltf.scene;
  } catch {
    return null;
  }
}

/** The footprint node a mesh belongs to: the nearest ancestor named like one of the board's parts. */
function refOf(o: THREE.Object3D | null, refs: ReadonlySet<string>): string | null {
  for (let n = o; n; n = n.parent) if (n.name && refs.has(n.name)) return n.name;
  return null;
}

const PICK = new THREE.Color("#ff6a3d");

/** A soft dark pad under the board, drawn once: a blurred rounded rectangle, no shadow maps. */
let shadowTex: THREE.CanvasTexture | null = null;
function contactShadow(): THREE.CanvasTexture {
  if (!shadowTex) {
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    const g = c.getContext("2d");
    if (g) {
      g.filter = "blur(22px)";
      g.fillStyle = "rgba(20, 30, 45, 0.9)";
      g.beginPath();
      g.roundRect(56, 56, 144, 144, 18);
      g.fill();
    }
    shadowTex = new THREE.CanvasTexture(c);
    shadowTex.colorSpace = THREE.SRGBColorSpace;
  }
  return shadowTex;
}

function Board(props: { root: THREE.Group; refs: ReadonlySet<string>; selected: string | null; onPick: (ref: string | null) => void; onReady: () => void }) {
  const { root, refs, selected, onPick, onReady } = props;
  const { camera, gl, scene, invalidate, size } = useThree();
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);
  // centre the board at the origin, once per board
  const box = useMemo(() => {
    const b = new THREE.Box3().setFromObject(root);
    root.position.sub(b.getCenter(new THREE.Vector3()));
    return new THREE.Box3().setFromObject(root);
  }, [root]);
  const extent = useMemo(() => box.getSize(new THREE.Vector3()), [box]);
  const fit = Math.max(extent.x, extent.y, extent.z);
  useEffect(() => {
    gl.toneMapping = THREE.ACESFilmicToneMapping;
    gl.toneMappingExposure = 1;
    gl.outputColorSpace = THREE.SRGBColorSpace;
    const pmrem = new THREE.PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const env = pmrem.fromScene(room, 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = 0.55;
    room.dispose();
    pmrem.dispose();
    return () => {
      scene.environment = null;
      env.dispose();
    };
  }, [gl, scene]);
  // the home view: the poster's three-quarter angle, the board filling about two thirds of the frame
  useEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    const v = homeView(box, cam.fov, size.width / Math.max(1, size.height));
    cam.position.copy(v.position);
    cam.near = v.distance / 100;
    cam.far = v.distance * 20;
    cam.updateProjectionMatrix();
    controls.current?.target.set(0, 0, 0);
    controls.current?.update();
    invalidate();
  }, [camera, box, size.width, size.height, invalidate]);
  // the panel shows the live view only once a real frame of the board has been drawn
  useEffect(() => {
    let raf = requestAnimationFrame(() => {
      raf = requestAnimationFrame(onReady);
    });
    return () => cancelAnimationFrame(raf);
  }, [root, onReady]);
  // the picked part glows; every other material stays as the board look drew it
  useEffect(() => {
    const touched: THREE.MeshStandardMaterial[] = [];
    if (selected) {
      root.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh || refOf(mesh, refs) !== selected) return;
        const own = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).map((m) => {
          if (!(m as THREE.MeshStandardMaterial).isMeshStandardMaterial) return m;
          const c = (m as THREE.MeshStandardMaterial).clone();
          touched.push(c);
          c.emissive = PICK.clone();
          c.emissiveIntensity = 0.55;
          return c;
        });
        mesh.userData.original ??= mesh.material;
        mesh.material = Array.isArray(mesh.material) ? own : own[0];
      });
    }
    invalidate();
    return () => {
      root.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (mesh.isMesh && mesh.userData.original) {
          mesh.material = mesh.userData.original as THREE.Material;
          delete mesh.userData.original;
        }
      });
      for (const m of touched) m.dispose();
    };
  }, [root, refs, selected, invalidate]);
  const click = (e: ThreeEvent<MouseEvent>) => {
    // a drag that turned the board is not a pick
    if (e.delta > 4) return;
    e.stopPropagation();
    const ref = refOf(e.object, refs);
    onPick(ref && ref !== selected ? ref : null);
  };
  return (
    <>
      <hemisphereLight args={["#ffffff", "#d8d8d2", 0.7]} />
      <directionalLight position={[-0.5 * fit, fit, 0.7 * fit]} intensity={1.5} />
      <primitive object={root} onClick={click} />
      <mesh position={[0, box.min.y - fit * 0.002, 0]} rotation={[-Math.PI / 2, 0, 0]} scale={[extent.x * 1.6, extent.z * 1.6, 1]} raycast={() => null} renderOrder={-1}>
        <planeGeometry />
        <meshBasicMaterial map={contactShadow()} transparent opacity={0.3} depthWrite={false} toneMapped={false} />
      </mesh>
      <OrbitControls ref={controls} makeDefault enableDamping={false} zoomToCursor minDistance={fit * 0.25} maxDistance={fit * 5} onChange={() => invalidate()} />
    </>
  );
}

type Load = { status: "loading" } | { status: "ready"; root: THREE.Group } | { status: "failed" };

export function LibraryBoard3D(props: { slug: string; title: string; refs: ReadonlySet<string>; selected: string | null; onPick: (ref: string | null) => void; poster?: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [drawn, setDrawn] = useState(false);
  const [round, setRound] = useState(0);
  useEffect(() => {
    let live = true;
    let wait: ReturnType<typeof setTimeout> | undefined;
    setLoad({ status: "loading" });
    setDrawn(false);
    const attempt = (n: number) => {
      void loadBoard(props.slug).then((root) => {
        if (!live) return;
        if (root) setLoad({ status: "ready", root });
        else if (n < MODEL_RETRY_DELAYS_MS.length) wait = setTimeout(() => attempt(n + 1), MODEL_RETRY_DELAYS_MS[n]);
        else setLoad({ status: "failed" });
      });
    };
    attempt(0);
    return () => {
      live = false;
      clearTimeout(wait);
    };
  }, [props.slug, round]);
  const root = load.status === "ready" ? load.root : null;
  // free the GPU copies of the board's meshes when the panel closes or the board changes
  useEffect(
    () => () => {
      root?.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh) return;
        mesh.geometry.dispose();
        for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) m.dispose();
      });
    },
    [root],
  );
  const onReady = useMemo(() => () => setDrawn(true), []);
  return (
    <div className="os-3d b3d" aria-label={`${props.title}, 3D view. Drag to turn, scroll to zoom, click a part to pick it.`} aria-busy={!drawn && load.status === "loading"}>
      {props.poster && <img className={`b3d-poster ${drawn ? "gone" : ""}`} src={props.poster} alt="" />}
      {!props.poster && !drawn && <span className="b3d-blank" aria-hidden="true" />}
      {root && (
        <Canvas className={`b3d-canvas ${drawn ? "on" : ""}`} frameloop="demand" dpr={[1, 2]} camera={{ fov: 32, position: [0, 0.2, 0.2] }} gl={{ antialias: true, alpha: true }}>
          <Suspense fallback={null}>
            <Board root={root} refs={props.refs} selected={props.selected} onPick={props.onPick} onReady={onReady} />
          </Suspense>
        </Canvas>
      )}
      {load.status === "failed" ? (
        <button
          type="button"
          className="b3d-chip b3d-retry"
          onClick={() => {
            bytes.delete(props.slug);
            setRound((r) => r + 1);
          }}
        >
          3D view did not load · Retry
        </button>
      ) : drawn ? (
        <span className="os-3d-hint mono">Drag to turn · click a part</span>
      ) : (
        <span className="b3d-chip mono">
          <span className="b3d-dot" aria-hidden="true" />
          Opening in 3D
        </span>
      )}
    </div>
  );
}
