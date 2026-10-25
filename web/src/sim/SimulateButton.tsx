import { useApp } from "../state/store";
import { Icon } from "../ui/common";
import { openSimPanel } from "./simPanelStore";

/** Top right of the workspace, beside Export: opens the build's firmware panel (the bot can demo the device there). The in-viewport "simulate" toggle is the main simulation mode. */
export function SimulateButton() {
  const hasFirmware = useApp((s) => !!s.build?.firmware);
  const running = useApp((s) => s.build?.status === "running" || s.build?.status === "awaiting_input");
  const ready = hasFirmware && !running;
  return (
    <button
      type="button"
      className="btn sm"
      disabled={!ready}
      onClick={openSimPanel}
      title={ready ? "Run the build's firmware on the device, or let the bot demo it" : hasFirmware ? "The firmware panel opens when the build is done" : "The firmware panel needs the build's firmware"}
    >
      <Icon name="play" size={12} /> Firmware
    </button>
  );
}
