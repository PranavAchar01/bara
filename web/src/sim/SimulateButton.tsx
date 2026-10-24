import { useApp } from "../state/store";
import { Icon } from "../ui/common";
import { openSim } from "./simStore";

/** Top right of the workspace, beside Export: opens the build's firmware in simulation mode. */
export function SimulateButton() {
  const hasFirmware = useApp((s) => !!s.build?.firmware);
  const running = useApp((s) => s.build?.status === "running" || s.build?.status === "awaiting_input");
  const ready = hasFirmware && !running;
  return (
    <button
      type="button"
      className="btn sm"
      disabled={!ready}
      onClick={openSim}
      title={ready ? "Load the firmware onto the device and try it" : hasFirmware ? "Simulation opens when the build is done" : "Simulation needs the build's firmware"}
    >
      <Icon name="play" size={12} /> Simulate
    </button>
  );
}
