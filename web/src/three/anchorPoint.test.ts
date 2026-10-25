import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { findAnchorPoint, partKeyAlong } from "./anchorPoint";

function scene() {
  const cam = new THREE.PerspectiveCamera(40, 1, 0.1, 1000);
  cam.position.set(0, 0, 100);
  cam.lookAt(0, 0, 0);
  cam.updateMatrixWorld(true);
  const box = (w: number, z: number) => {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(new THREE.BoxGeometry(w, w, 2), new THREE.MeshBasicMaterial()));
    g.position.z = z;
    g.updateMatrixWorld(true);
    return g;
  };
  return { cam, front: box(10, 20), back: box(30, 0), root: new THREE.Group() };
}

describe("leader landing point", () => {
  it("lands on the part's own surface facing the camera", () => {
    const { cam, front } = scene();
    const hit = findAnchorPoint([front], cam, () => true, 0, null);
    expect(hit).not.toBeNull();
    expect(front.localToWorld(hit!.local.clone()).z).toBeCloseTo(21);
  });

  it("is null for a part another part covers", () => {
    const { cam, front, back } = scene();
    const covered = (p: THREE.Vector3, owner: THREE.Object3D) => {
      const ray = new THREE.Raycaster(cam.position, p.clone().sub(cam.position).normalize(), 0, cam.position.distanceTo(p) - 0.12);
      const hits = ray.intersectObjects([front, back], true);
      return hits.length === 0 || hits[0].object.parent === owner;
    };
    expect(findAnchorPoint([back], cam, covered, 0, null)).not.toBeNull(); // the rim around the front part is in view
    const small = new THREE.Group();
    small.add(new THREE.Mesh(new THREE.BoxGeometry(4, 4, 2), new THREE.MeshBasicMaterial()));
    small.position.z = -10;
    small.updateMatrixWorld(true);
    expect(findAnchorPoint([small], cam, covered, 0, null)).toBeNull(); // wholly behind the front part
  });
});

describe("pick through see-through shells", () => {
  const hit = (name: string) => ({ object: Object.assign(new THREE.Mesh(), { name }) }) as unknown as THREE.Intersection;
  const keyOf = (o: THREE.Object3D) => ({ key: o.name, shell: o.name.startsWith("e:") });
  const glass = (m: THREE.Intersection) => {
    (m.object as THREE.Mesh).material = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.2 });
    return m;
  };
  it("takes the part behind a glass shell", () => {
    expect(partKeyAlong([glass(hit("e:case_top")), hit("p:display")], keyOf)).toBe("p:display");
  });
  it("takes the shell when nothing is behind it", () => {
    expect(partKeyAlong([glass(hit("e:case_top"))], keyOf)).toBe("e:case_top");
  });
  it("takes the nearest part when it is the one in front", () => {
    expect(partKeyAlong([hit("p:display"), hit("p:knob")], keyOf)).toBe("p:display");
  });
});
