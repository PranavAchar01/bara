import { describe, expect, it } from "vitest";
import { loadFixtures } from "../spec/fixtures";
import type { Build, ClientEnvelope, StreamFixture } from "../spec/types";
import { CONNECTION_SCOPED } from "../spec/types";
import { createBuild, reduceBuild } from "../state/reducer";
import { emptyView, reduceView, type ViewState } from "../state/view";
import { explainPart, SHORT_MAX } from "./explain";

const fx = await loadFixtures();

function chain(name: string): StreamFixture[] {
  const f = fx.streams.get(name);
  if (!f) throw new Error(`no fixture ${name}`);
  return f.requires_fixture ? [...chain(f.requires_fixture), f] : [f];
}

/** Replays a fixture chain into the Build and the view, like the store does. */
function replay(name: string): { build: Build; view: ViewState } {
  let build: Build | null = null;
  let view = emptyView(0);
  let lastStart: ClientEnvelope<"build.start"> | null = null;
  for (const f of chain(name)) {
    for (const step of f.steps) {
      if (step.dir === "client") {
        if (step.msg.type === "build.start") lastStart = step.msg as ClientEnvelope<"build.start">;
        continue;
      }
      const env = step.msg;
      if (env.type === "ack" && lastStart && (env.payload as { msg_id: string }).msg_id === lastStart.msg_id) {
        build = createBuild((env.payload as { build_id: string }).build_id, lastStart.payload.prompt, lastStart.ts);
        view = emptyView(0);
        lastStart = null;
        continue;
      }
      if (CONNECTION_SCOPED.has(env.type) || !build) continue;
      build = reduceBuild(build, env);
      view = reduceView(view, env, 0);
    }
  }
  if (!build) throw new Error("no build");
  return { build, view };
}

const compose = replay("compose_wireless_split_oled");
const exact = replay("exact_keyboard");

describe("explainPart", () => {
  it("says why a model pick won, with the filter and the design it fits", () => {
    const e = explainPart(compose.build, compose.view, "u_mcu_l")!;
    expect(e.short).toBe("Picked nice!nano v2: BLE, fits the Corne");
    expect(e.long[0]).toMatch(/BLE controller in Corne builds/);
    expect(e.long.join(" ")).toMatch(/Narrowed 214 controllers to 4; runner-up SuperMini nRF52840 \(0\.77 vs 0\.91\)/);
    expect(e.long.join(" ")).toMatch(/Wired to PCB left \(Socketed on the PCB\)/);
  });

  it("names parts kept from the reused design", () => {
    const e = explainPart(compose.build, compose.view, "u_pcb_l")!;
    expect(e.short).toBe("Kept Corne v3 PCB (left) from the Corne");
    expect(e.long[0]).toBe("From the open Corne (crkbd) design (MIT), kept as the skeleton.");
    expect(e.long.join(" ")).not.toMatch(/runner-up/);
  });

  it("explains an exact design reuse without repeating itself", () => {
    const e = explainPart(exact.build, exact.view, "u_trrs_l")!;
    expect(e.short).toBe("PJ-320A TRRS jack, straight from the Corne");
    expect(e.long.filter((l) => /Corne/.test(l))).toHaveLength(1);
    expect(e.long.join(" ")).toMatch(/Wired to TRRS cable/);
  });

  it("keeps every line short and gives 2 to 4 facts for every part", () => {
    for (const { build, view } of [compose, exact]) {
      for (const p of build.parts) {
        const e = explainPart(build, view, p.instance_id);
        expect(e, p.instance_id).not.toBeNull();
        expect(e!.short.length, e!.short).toBeLessThanOrEqual(SHORT_MAX);
        expect(e!.long.length, p.instance_id).toBeGreaterThanOrEqual(2);
        expect(e!.long.length, p.instance_id).toBeLessThanOrEqual(4);
      }
    }
  });

  it("returns null for unknown parts or no build", () => {
    expect(explainPart(compose.build, compose.view, "nope")).toBeNull();
    expect(explainPart(null, compose.view, "u_mcu_l")).toBeNull();
  });
});
