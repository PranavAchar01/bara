import { describe, expect, it } from "vitest";
import { elementPoses, keyCentreLocal, rotateXYZ, rotateZ } from "./layout";
import type { Layout, Placement } from "../spec/types";
import { loadFixtures } from "../spec/fixtures";

const close = (a: number[], b: number[]) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], 6));

describe("SPEC 3.3 layout math", () => {
  it("centres a 1u key at half a pitch, with Y negated", () => {
    close(keyCentreLocal({ i: 0, x_u: 0, y_u: 0 }, 19.05, 19.05), [9.525, -9.525, 0]);
    close(keyCentreLocal({ i: 0, x_u: 2, y_u: 1, w_u: 1.5 }, 19.05, 19.05), [(2 + 0.75) * 19.05, -1.5 * 19.05, 0]);
  });

  it("rotates clockwise about the pivot for positive r_deg", () => {
    // Key centre (0.5, -0.5)u about pivot (0,0); r = 90 clockwise from above -> (-0.5, -0.5)u.
    close(keyCentreLocal({ i: 0, x_u: 0, y_u: 0, r_deg: 90 }, 1, 1), [-0.5, -0.5, 0]);
    // Pivot at the key centre leaves it in place.
    close(keyCentreLocal({ i: 0, x_u: 0, y_u: 0, r_deg: 30, rx_u: 0.5, ry_u: 0.5 }, 10, 10), [5, -5, 0]);
  });

  it("applies placement position and XYZ rotation", () => {
    close(rotateZ([1, 0, 0], 90), [0, 1, 0]);
    close(rotateXYZ([0, 1, 0], [90, 0, 0]), [0, 0, 1]);
    const layout: Layout = { layout_id: "l", pitch_x_mm: 10, pitch_y_mm: 10, keys: [{ i: 0, x_u: 0, y_u: 0 }] };
    const placement: Placement = { mode: "layout", position_mm: [100, 0, 5], rotation_deg: [0, 0, 90], layout_id: "l" };
    const [p] = elementPoses(placement, 1, layout);
    close(p.position, [100 + 5, 5, 5]);
  });

  it("lays out the Corne left half from the fixture with one pose per key", async () => {
    const fx = await loadFixtures();
    const steps = fx.streams.get("exact_keyboard")?.steps ?? [];
    const layout = steps.find((s) => s.msg.type === "layout.added")?.msg.payload as { layout: Layout };
    const part = steps.find(
      (s) => s.msg.type === "part.added" && (s.msg.payload as { part: { instance_id: string } }).part.instance_id === "u_sw_l",
    )?.msg.payload as { part: { placement: Placement; quantity: number } };
    const poses = elementPoses(part.part.placement, part.part.quantity, layout.layout);
    expect(poses).toHaveLength(21);
    const first = poses.find((p) => p.index === 0);
    close(first?.position ?? [], [-132 + 9.525 + (layout.layout.keys[0].x_u * 19.05), 40 - 9.525 - layout.layout.keys[0].y_u * 19.05, 1.6]);
  });
});
