import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { courtyard, footprintBoxes } from "./boardgeom";
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
    const boxes = footprintBoxes(board([{ ref: "SW3", label: "Cherry MX", center_mm: [99, 99], size_mm: [1, 1] }]), glb);
    expect(boxes).toHaveLength(1);
    expect(boxes[0].box.max.z).toBe(11);
    expect(boxes[0].footprint?.label).toBe("Cherry MX");
  });
});
