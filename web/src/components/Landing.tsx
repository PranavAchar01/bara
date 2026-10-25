// Landing: one screen, one button. Behind it, a small mock of the app replays real builds from
// scratch (BuildScene). Build goes to the Library (finished builds), whose own Build button opens
// the prompt pop-up; the build itself runs on its own page (/build/<id>).
import { useEffect } from "react";
import { useApp } from "../state/store";
import { useVoice } from "../voice/voice";
import { BuildScene } from "./BuildScene";
import { openBuildDialog } from "./BuildDialog";

export function LandingHero() {
  // holding Space on the landing still talks to the Build pop-up, so it opens to catch the words
  useEffect(
    () =>
      useVoice.subscribe((s, prev) => {
        if (s.listening && !prev.listening) openBuildDialog();
      }),
    [],
  );
  return (
    <section className="ld">
      <header className="ld-head">
        <h1>Hardware, built while you watch.</h1>
        <p>A small robot picks real parts, routes the board and closes the case around it.</p>
      </header>
      <figure className="ld-window">
        <BuildScene />
      </figure>
      <div className="ld-cta">
        <button type="button" className="btn primary ld-build" onClick={() => useApp.setState({ screen: "drafts" })}>
          Build
        </button>
      </div>
    </section>
  );
}
