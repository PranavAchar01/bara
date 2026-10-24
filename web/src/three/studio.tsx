// Studio look (render recipe 2.1-2.4): neutral tone mapping, a PMREM room
// environment for reflections, one key light, an off-white seamless floor
// with a baked contact shadow plus a soft key-light shadow. Shadows re-bake
// only when the scene settles, never per frame.
import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { ContactShadows } from "@react-three/drei";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { onModelsChanged } from "./assets";
import { stage, stageBox } from "./stage";

export interface StudioPalette {
  background: string;
  shadow: string;
  dark: boolean;
}

export function studioPalette(dark: boolean): StudioPalette {
  return dark ? { background: "#232427", shadow: "#000000", dark } : { background: "#F0EFEB", shadow: "#1B1F2A", dark };
}

/** Renderer, environment and background. */
export function StudioEnvironment(props: { palette: StudioPalette }) {
  const { gl, scene } = useThree();
  useEffect(() => {
    gl.toneMapping = THREE.NeutralToneMapping;
    gl.toneMappingExposure = 1.0;
    gl.outputColorSpace = THREE.SRGBColorSpace;
    gl.shadowMap.enabled = true;
    gl.shadowMap.type = THREE.PCFSoftShadowMap;
    gl.shadowMap.autoUpdate = false;
    gl.shadowMap.needsUpdate = true;
    const pmrem = new THREE.PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const env = pmrem.fromScene(room, 0.04).texture;
    scene.environment = env;
    scene.environmentIntensity = 0.85;
    room.dispose();
    pmrem.dispose();
    return () => {
      scene.environment = null;
      env.dispose();
    };
  }, [gl, scene]);
  useEffect(() => {
    scene.background = new THREE.Color(props.palette.background);
  }, [scene, props.palette.background]);
  return null;
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

/**
 * Key light with a soft shadow on an invisible shadow catcher, and a contact
 * shadow baked under the parts. Both refresh when models load, the build
 * changes, or the explode settles.
 */
export function StudioFloor(props: { palette: StudioPalette; revision: string }) {
  const { gl } = useThree();
  const [footing, setFooting] = useState<Footing | null>(null);
  const [version, setVersion] = useState(0);
  const settleSeen = useRef(stage.settleVersion);
  const light = useMemo(() => {
    const l = new THREE.DirectionalLight(0xffffff, 1.15);
    l.castShadow = true;
    l.shadow.mapSize.set(2048, 2048);
    l.shadow.bias = -0.0004;
    l.shadow.normalBias = 0.6;
    l.shadow.radius = 6;
    return l;
  }, []);
  useEffect(() => onModelsChanged(() => setVersion((v) => v + 1)), []);
  useEffect(() => {
    // Measure after the parts committed their instance matrices.
    const id = requestAnimationFrame(() => setFooting(measure()));
    return () => cancelAnimationFrame(id);
  }, [version, props.revision]);
  useFrame(() => {
    if (stage.moving) gl.shadowMap.needsUpdate = true;
    if (settleSeen.current !== stage.settleVersion) {
      settleSeen.current = stage.settleVersion;
      setFooting(measure());
      setVersion((v) => v + 1);
    }
  });
  useEffect(() => {
    if (!footing) return;
    const { center, size } = footing;
    const reach = Math.max(size.x, size.y, size.z, 60);
    light.position.set(center.x - reach * 0.55, center.y - reach * 0.35, center.z + reach * 1.6);
    light.target.position.copy(center);
    light.target.updateMatrixWorld();
    const cam = light.shadow.camera;
    const half = reach * 1.1;
    cam.left = -half;
    cam.right = half;
    cam.top = half;
    cam.bottom = -half;
    cam.near = 1;
    cam.far = reach * 5;
    cam.updateProjectionMatrix();
    gl.shadowMap.needsUpdate = true;
  }, [footing, light, gl]);
  const z = (footing?.floorZ ?? 0) - 0.05;
  const span = Math.max(footing?.size.x ?? 300, footing?.size.y ?? 300, 120);
  const cx = footing?.center.x ?? 0;
  const cy = footing?.center.y ?? 0;
  return (
    <>
      <primitive object={light} />
      <primitive object={light.target} />
      <mesh position={[cx, cy, z - 0.05]} receiveShadow raycast={() => null}>
        <planeGeometry args={[span * 6, span * 6]} />
        <shadowMaterial transparent opacity={props.palette.dark ? 0.35 : 0.13} depthWrite={false} />
      </mesh>
      {/* ContactShadows looks along +Y; rotate so its up axis is build-space +Z. */}
      <group position={[cx, cy, z]} rotation={[Math.PI / 2, 0, 0]}>
        <ContactShadows
          key={`${version}:${props.revision}`}
          frames={1}
          scale={span * 1.8}
          far={Math.max(20, (footing?.size.z ?? 40) * 0.8)}
          blur={3}
          opacity={props.palette.dark ? 0.7 : 0.55}
          resolution={512}
          color={props.palette.shadow}
        />
      </group>
    </>
  );
}
