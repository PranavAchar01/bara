// The 3D view of one open-source board, inside its detail panel: the board's own prerendered GLB (KiCad's
// export with every part's real library model, nodes named by refdes), turned with the pointer. One WebGL
// context, open only while the panel is, drawing on demand: it renders when the board lands, while it is
// being turned, and when a part is picked, then sits still. Picking a part here or in the list lights it in both.
import { Suspense, useEffect, useMemo, useRef, useState, type ComponentRef } from "react";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { boardGlbUrls } from "../library/openSource";

const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);

/** The first source that answers: this site's own copy, then the board library's published one. */
async function loadBoard(slug: string): Promise<THREE.Group> {
  let last: unknown = null;
  for (const url of boardGlbUrls(slug)) {
    try {
      const gltf = await loader.loadAsync(url);
      return gltf.scene;
    } catch (e) {
      last = e;
    }
  }
  throw last ?? new Error("no source");
}

/** The footprint node a mesh belongs to: the nearest ancestor named like one of the board's parts. */
function refOf(o: THREE.Object3D | null, refs: ReadonlySet<string>): string | null {
  for (let n = o; n; n = n.parent) if (n.name && refs.has(n.name)) return n.name;
  return null;
}

const PICK = new THREE.Color("#ff6a3d");

function Board(props: { root: THREE.Group; refs: ReadonlySet<string>; selected: string | null; onPick: (ref: string | null) => void }) {
  const { root, refs, selected, onPick } = props;
  const { camera, gl, scene, invalidate } = useThree();
  const controls = useRef<ComponentRef<typeof OrbitControls>>(null);
  // centre the board at the origin and frame it from a three-quarter angle, once per board
  const fit = useMemo(() => {
    const box = new THREE.Box3().setFromObject(root);
    const centre = box.getCenter(new THREE.Vector3());
    root.position.sub(centre);
    const size = box.getSize(new THREE.Vector3());
    return Math.max(size.x, size.z, size.y * 2);
  }, [root]);
  useEffect(() => {
    gl.toneMapping = THREE.NeutralToneMapping;
    gl.outputColorSpace = THREE.SRGBColorSpace;
    const pmrem = new THREE.PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const env = pmrem.fromScene(room, 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = 1;
    room.dispose();
    pmrem.dispose();
    return () => {
      scene.environment = null;
      env.dispose();
    };
  }, [gl, scene]);
  useEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    // far enough that the whole board fits the 30 degree view with a margin
    const d = fit * 1.8;
    cam.position.set(d * 0.55, d * 0.75, d * 0.75);
    cam.near = fit / 200;
    cam.far = fit * 40;
    cam.updateProjectionMatrix();
    controls.current?.target.set(0, 0, 0);
    controls.current?.update();
    invalidate();
  }, [camera, fit, invalidate]);
  // the picked part glows; every other material is left exactly as the board's file has it
  useEffect(() => {
    const touched: { m: THREE.MeshStandardMaterial; was: THREE.Color; wasI: number }[] = [];
    if (selected) {
      root.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh || refOf(mesh, refs) !== selected) return;
        const own = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).map((m) => {
          if (!(m as THREE.MeshStandardMaterial).isMeshStandardMaterial) return m;
          const c = (m as THREE.MeshStandardMaterial).clone();
          touched.push({ m: c, was: c.emissive.clone(), wasI: c.emissiveIntensity });
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
      for (const t of touched) t.m.dispose();
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
      <hemisphereLight args={["#ffffff", "#9aa3ad", 0.6]} />
      <directionalLight position={[fit, fit * 2, fit]} intensity={1.4} />
      <directionalLight position={[-fit, fit, -fit * 0.6]} intensity={0.4} />
      <primitive object={root} onClick={click} />
      <OrbitControls ref={controls} makeDefault enableDamping={false} minDistance={fit * 0.25} maxDistance={fit * 4} onChange={() => invalidate()} />
    </>
  );
}

export function LibraryBoard3D(props: { slug: string; title: string; refs: ReadonlySet<string>; selected: string | null; onPick: (ref: string | null) => void; poster?: string }) {
  const [root, setRoot] = useState<THREE.Group | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    setRoot(null);
    setFailed(false);
    loadBoard(props.slug).then(
      (g) => live && setRoot(g),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [props.slug]);
  // free the GPU copies of the board's meshes when the panel closes
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
  return (
    <div className="os-3d" aria-label={`${props.title}, 3D view. Drag to turn, scroll to zoom, click a part to pick it.`}>
      {props.poster && !root && <img className="os-3d-poster" src={props.poster} alt="" />}
      {root && (
        <Canvas frameloop="demand" dpr={[1, 2]} camera={{ fov: 30, position: [0, 0.2, 0.2] }} gl={{ antialias: true, alpha: true }}>
          <Suspense fallback={null}>
            <Board root={root} refs={props.refs} selected={props.selected} onPick={props.onPick} />
          </Suspense>
        </Canvas>
      )}
      {!root && <span className="os-3d-note mono">{failed ? "The 3D board could not be loaded" : "Loading the 3D board"}</span>}
      {root && <span className="os-3d-hint mono">Drag to turn · click a part</span>}
    </div>
  );
}
