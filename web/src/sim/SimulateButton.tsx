import { useEffect } from "react";
import { useApp } from "../state/store";
import { Icon } from "../ui/common";
import { openSimPanel } from "./simPanelStore";

// A /build/<id>#/sim/<id> link: read once at load, since the router rewrites the address before the build arrives.
let linkedSim: string | null = typeof window === "undefined" ? null : (/^#\/sim\/([A-Za-z0-9_-]{1,64})$/.exec(window.location.hash)?.[1] ?? null);

/** The firmware simulator needs the parts and the controller, not a finished case: a build that failed
 *  at a later stage (enclosure, routing) still simulates. */
function useSimReady(): { ready: boolean; id: string | null } {
  const ready = useApp((s) => !!s.build && (s.build.status === "done" || s.build.status === "failed") && (s.build.parts?.length ?? 0) > 0);
  const id = useApp((s) => s.build?.build_id ?? null);
  return { ready, id };
}

/** Top right of the workspace, beside Export: opens the simulation screen (same as the viewport's "simulate"). */
export function SimulateButton() {
  const { ready, id } = useSimReady();
  // a /build/<id>#/sim/<id> link opens the simulator once that build has loaded
  useEffect(() => {
    if (ready && id && linkedSim === id) {
      linkedSim = null;
      openSimPanel();
    }
  }, [ready, id]);
  return (
    <button
      type="button"
      className="btn sm"
      disabled={!ready}
      onClick={openSimPanel}
      title={ready ? "Build the firmware, run it on the device and test it" : "Simulation opens when the build has its parts"}
    >
      <Icon name="play" size={12} /> Simulate
    </button>
  );
}
