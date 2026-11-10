// The graph preview's webview, bundled as dist/preview.js: renders Preview with what the extension posts (`{type: 'state',
// state}` after every check of the document) and posts back `{type: 'open', line}` when a step or a
// loop is clicked, so the editor moves the cursor to it. The mode and the direction are kept in the
// webview's own state.

import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Direction } from "../../../../console/src/graph/layout.ts";
import { Preview, type Mode, type PreviewState } from "./Preview.tsx";
import "./page.css";

interface Saved { direction?: Direction; mode?: Mode }

declare function acquireVsCodeApi(): {
  postMessage(message: unknown): void;
  getState(): Saved | undefined;
  setState(state: Saved): void;
};

const vscode = acquireVsCodeApi();

function App() {
  const [state, setState] = useState<PreviewState>({ title: "", graph: null, problems: [], stale: false });
  const [direction, setDirection] = useState<Direction>(vscode.getState()?.direction ?? "down");
  const [mode, setMode] = useState<Mode>(vscode.getState()?.mode ?? "control");
  // The same graph again (an edit that moved nothing) keeps its object, so the drawing and its selection stay.
  const lastGraph = useRef<string>("");

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const message = event.data;
      if (!message || message.type !== "state") return;
      const next = message.state as PreviewState;
      setState((previous) => {
        const text = JSON.stringify(next.graph);
        if (next.graph && previous.graph && text === lastGraph.current) return { ...next, graph: previous.graph };
        lastGraph.current = text;
        return next;
      });
    };
    window.addEventListener("message", onMessage);
    vscode.postMessage({ type: "ready" });
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return (
    <Preview state={state} direction={direction} mode={mode}
             onDirection={(d) => { setDirection(d); vscode.setState({ direction: d, mode }); }}
             onMode={(m) => { setMode(m); vscode.setState({ direction, mode: m }); }}
             onOpen={(item) => { if (item.line !== null) vscode.postMessage({ type: "open", line: item.line, name: item.name }); }} />
  );
}

createRoot(document.getElementById("root")!).render(<App />);
