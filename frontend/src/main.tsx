import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import "./styles.css";
import "./theme.css";
import { applyTheme, useTheme } from "./store/theme";

applyTheme(useTheme.getState().mode);   // before the first paint: no flash of the wrong theme

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
