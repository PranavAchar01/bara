import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { courtyard, footprintBoxes, matchComponents } from "./boardgeom";
import type { LoadedModel } from "./assets";
import type { Board } from "../spec/types";

const board = (footprints: Board["footprints"]): Board => ({
  board_id: "pcb_left",
  source: "unknown",
  status: "pending",
  revision: 0,
  thickness_mm: 1.6,
  footprints,
});

describe("board footprints", () => {
  it("rotates a courtyard about its centre", () => {
    const pts = courtyard({ ref: "U1", center_mm: [10, 5], size_mm: [4, 2], rot_deg: 90 });
    expect(pts).not.toBeNull();
    const xs = pts!.map((p) => p.x);
    const ys = pts!.map((p) => p.y);
    // 4 x 2 turned a quarter: 2 wide, 4 tall, still centred on (10, 5).
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(2);
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(4);
    expect((Math.max(...xs) + Math.min(...xs)) / 2).toBeCloseTo(10);
  });

  it("boxes footprints from the record above the board top", () => {
    const boxes = footprintBoxes(board([{ ref: "D1", center_mm: [0, 0], size_mm: [2, 1] }, { ref: "J1" }]), null);
    expect(boxes.map((b) => b.ref)).toEqual(["D1"]);
    expect(boxes[0].box.min.z).toBeCloseTo(1.6);
    expect(boxes[0].box.max.z).toBeGreaterThan(1.6);
  });

  it("prefers the GLB's footprint boxes and keeps the record's names", () => {
    const glb = { footprints: [{ ref: "SW3", box: new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(14, 14, 11)) }] };
    const boxes = footprintBoxes(
      board([
        { ref: "SW3", label: "Cherry MX", center_mm: [99, 99], size_mm: [1, 1] },
        // no 3D model, so no GLB node: still hoverable from its courtyard
        { ref: "J1", label: "JST PH", center_mm: [40, 0], size_mm: [9, 10] },
      ]),
      glb,
    );
    expect(boxes.map((b) => b.ref)).toEqual(["SW3", "J1"]);
    expect(boxes[0].box.max.z).toBe(11);
    expect(boxes[0].footprint?.label).toBe("Cherry MX");
    expect(boxes[1].box.getCenter(new THREE.Vector3()).x).toBeCloseTo(40);
  });
});

describe("board components", () => {
  const comp = (name: string, min: number[], max: number[]) => ({ name, bbox: new THREE.Box3(new THREE.Vector3(...min), new THREE.Vector3(...max)) });

  it("matches a display bigger than a quarter of the board by its reference", () => {
    // a handheld: 80 x 130 board, a 70 x 55 TFT on it (37% of the board) and one switch
    const loaded = {
      bbox: new THREE.Box3(new THREE.Vector3(0, -130, 0), new THREE.Vector3(80, 0, 6)),
      components: [comp("", [0, -130, 0], [80, 0, 1.6]), comp("U3", [5, -60, 1.6], [75, -5, 6]), comp("SW1", [10, -100, 1.6], [16, -94, 5])],
    } as unknown as LoadedModel;
    const b = board([
      { ref: "U3", instance_id: "u_display", center_mm: [40, -32] },
      { ref: "SW1", instance_id: "u_btn", center_mm: [13, -97] },
    ]);
    const cands = [
      { instanceId: "u_display", layer: "pcb" as const, points: [new THREE.Vector3(40, -32, 8)] },
      { instanceId: "u_btn", layer: "pcb" as const, points: [new THREE.Vector3(13, -97, 1.6)] },
    ];
    const { owner, substrate } = matchComponents(loaded, b, cands);
    expect(owner.get(1)?.instanceId).toBe("u_display"); // drawn once, by the board
    expect(owner.get(2)?.instanceId).toBe("u_btn");
    expect(substrate).toBe(0);
  });
});
