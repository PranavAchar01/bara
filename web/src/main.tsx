import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { startClient } from "./net/client";
import "./styles/tokens.css";
import "./styles/app.css";

void startClient();

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
