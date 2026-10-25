import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { startClient } from "./net/client";
import { startSceneSync } from "./project/scenes";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/shell.css";
import "./styles/workspace.css";

// BotLab (?botlab=1) is the bot alone: no server connection.
if (new URLSearchParams(window.location.search).get("botlab") !== "1") {
  void startClient();
  startSceneSync();
}

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
