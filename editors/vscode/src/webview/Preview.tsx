// What the graph preview draws: the console's card canvas over the graph of the last compile, with
// a line above it saying whether the buffer compiles. While the buffer has errors the canvas keeps
// the last graph that compiled, as the markdown preview keeps its last render, and the line names the
// first error. No `vscode` here: main.tsx wires it to the webview, test/preview.test.js renders
// it on the server.

import { Canvas } from "../../../../console/src/canvas/Canvas.tsx";
import type { Graph } from "../../../../console/src/canvas/model.ts";
import type { Direction } from "../../../../console/src/canvas/layout.ts";

/** A diagnostic as the extension forwards it. */
export interface Problem { severity: string; message: string; line: number | null; code: string }

export interface PreviewState {
  /** The procedure's name, or the file's when nothing has compiled yet. */
  title: string;
  /** The last graph that compiled, or null before the first clean compile. */
  graph: Graph | null;
  /** The text the graph was compiled from, for the open card's source slice. */
  source?: string;
  /** The current buffer's diagnostics. */
  problems: Problem[];
  /** True when `graph` is from an earlier text than the buffer's (the buffer has errors). */
  stale: boolean;
  /** A message in place of a report: aip not found, or the compiler failed to answer. */
  status?: string;
}

export interface PreviewProps {
  state: PreviewState;
  direction: Direction;
  onDirection: (direction: Direction) => void;
  /** A card, a loop or the first problem was clicked: jump to its line. */
  onOpen: (item: { name: string; line: number | null }) => void;
  /** The canvas's height, as CSS. */
  height?: string;
}

export function Preview({ state, direction, onDirection, onOpen, height = "calc(100vh - 6.5rem)" }: PreviewProps) {
  const errors = state.problems.filter((p) => p.severity === "error");
  const warnings = state.problems.filter((p) => p.severity === "warning");
  const first = errors[0] ?? warnings[0];
  let summary: string;
  if (state.status) summary = state.status;
  else if (errors.length) summary = `${errors.length} error${errors.length === 1 ? "" : "s"}` + (state.graph ? ": showing the last graph that compiled" : "");
  else if (warnings.length) summary = `compiles, ${warnings.length} warning${warnings.length === 1 ? "" : "s"}`;
  else summary = state.graph ? "compiles" : "waiting for the compiler";
  return (
    <div className="aipv" data-testid="preview" data-stale={state.stale ? "true" : "false"}>
      <div className="aipv-bar">
        <strong className="aipv-title">{state.title}</strong>
        <span className={`aipv-summary${errors.length || state.status ? " bad" : ""}`} data-testid="preview-summary">{summary}</span>
        <span className="aipv-direction" role="group" aria-label="direction">
          {(["down", "right"] as const).map((d) => (
            <button key={d} type="button" aria-pressed={direction === d} onClick={() => onDirection(d)}>{d}</button>
          ))}
        </span>
      </div>
      {first && !state.status && (
        <button type="button" className="aipv-problem" data-testid="preview-problem"
                onClick={() => onOpen({ name: first.code, line: first.line })}>
          {first.line !== null ? `line ${first.line}: ` : ""}{first.message}
        </button>
      )}
      {state.graph
        ? <Canvas graph={state.graph} source={state.source} direction={direction} height={height}
                  onOpen={(item) => { if (item) onOpen(item); }} />
        : <p className="aipv-empty">{errors.length ? "The procedure has not compiled yet; the graph appears with its first clean compile." : ""}</p>}
    </div>
  );
}
