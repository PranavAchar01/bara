// The Build pop-up, opened from the landing: one big prompt, a few plain examples that fill it,
// and Build. Sending starts the build on the Build page (a fresh canvas if one is already in use).
// Holding Space anywhere on the landing opens it, so what is said lands in its prompt.
import { useEffect, useRef } from "react";
import { create } from "zustand";
import { ExampleChips, fillPrompt, PromptBar } from "./PromptBar";
import { Icon } from "../ui/common";
import { armHandoff } from "./Handoff";

export const useBuildDialog = create<{ open: boolean; seed: string | null }>(() => ({ open: false, seed: null }));
/** Opens the dialog; with a seed, its prompt starts filled in (an example, or a gallery build to make again). */
export const openBuildDialog = (seed: string | null = null) => useBuildDialog.setState({ open: true, seed });
const close = () => useBuildDialog.setState({ open: false, seed: null });

export function BuildDialog() {
  const open = useBuildDialog((s) => s.open);
  const seed = useBuildDialog((s) => s.seed);
  const card = useRef<HTMLDivElement>(null);
  const back = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!open) return;
    back.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      back.current?.focus?.();
    };
  }, [open]);
  // the prompt mounts with the dialog, so the seed is handed over once it is there
  useEffect(() => {
    if (open && seed) requestAnimationFrame(() => fillPrompt(seed));
  }, [open, seed]);
  // the pop-up hands its prompt to the workspace the same way the intro does, then goes
  const sent = () => {
    const input = document.querySelector<HTMLInputElement>(".bd-field .prompt-input");
    armHandoff(input?.value ?? "", document.querySelector(".bd-field .promptbar") ?? document.querySelector(".bd-field"), null);
    close();
  };
  if (!open) return null;
  return (
    <div className="bd-scrim" onPointerDown={(e) => e.target === e.currentTarget && close()}>
      <div ref={card} className="bd-card" role="dialog" aria-modal="true" aria-labelledby="bd-h">
        <button type="button" className="btn ghost sm icon bd-close" aria-label="Close" onClick={close}>
          <Icon name="x" />
        </button>
        <h2 id="bd-h">What should Bara build?</h2>
        <p className="bd-sub">One line is enough. It picks real parts, routes the board, shapes the case and writes the firmware.</p>
        <div className="bd-field">
          <PromptBar autoFocus fresh onSent={sent} placeholder="Describe a device, or hold the bot and say it" />
        </div>
        <div className="bd-examples">
          <span className="bd-k">Try</span>
          <ExampleChips onPick={fillPrompt} max={4} />
        </div>
        <p className="bd-foot">
          <span>
            <kbd>Enter</kbd> to build
          </span>
          <span>Hold the bot to talk</span>
          <span>
            <kbd>Esc</kbd> to close
          </span>
        </p>
      </div>
    </div>
  );
}
