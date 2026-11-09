import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadConsoleConfig } from "./api/console";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);

// The console's process says which server (or folder) this page is for before anything renders.
loadConsoleConfig().then(
  () => root.render(<StrictMode><App /></StrictMode>),
  (e: unknown) => root.render(<p className="error" role="alert">{e instanceof Error ? e.message : String(e)}</p>),
);
