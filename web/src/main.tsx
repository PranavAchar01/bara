import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { applyEdit, startClient } from "./net/client";
import { startStyleInherit } from "./project/companion";
import { startSceneSync } from "./project/scenes";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/shell.css";
import "./styles/workspace.css";

// BotLab (?botlab=1) is the bot alone: no server connection.
if (new URLSearchParams(window.location.search).get("botlab") !== "1") {
  void startClient();
  startSceneSync();
  // a device made for another takes on its colours once it is built
  startStyleInherit((palette) => applyEdit([{ op: "palette", palette }], "Match the colours"));
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
