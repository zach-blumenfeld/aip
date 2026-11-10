// What the graph preview draws: the console's step graph over the graph of the last compile, with a
// line above it saying whether the buffer compiles. Two modes, control flow and data flow, and two
// directions, down and right; no run traffic, since the editor has no server. While the buffer has
// errors the graph stays the last one that compiled, as the markdown preview keeps its last render,
// and the line names the first error. No `vscode` here: main.tsx wires it to the webview,
// test/preview.test.js renders it on the server.

import { useEffect, useMemo, useState } from "react";
import type { Graph } from "../../../../console/src/canvas/model.ts";
import { dataEdges, dataKeys } from "../../../../console/src/graph/dataflow.ts";
import type { Direction } from "../../../../console/src/graph/layout.ts";
import { stepGraphOf } from "../../../../console/src/graph/model.ts";
import { StepGraph } from "../../../../console/src/views/StepGraph.tsx";

/** A diagnostic as the extension forwards it. */
export interface Problem { severity: string; message: string; line: number | null; code: string }

export interface PreviewState {
  /** The procedure's name, or the file's when nothing has compiled yet. */
  title: string;
  /** The last graph that compiled, or null before the first clean compile. */
  graph: Graph | null;
  /** The current buffer's diagnostics. */
  problems: Problem[];
  /** True when `graph` is from an earlier text than the buffer's (the buffer has errors). */
  stale: boolean;
  /** A message in place of a report: aip not found, or the compiler failed to answer. */
  status?: string;
}

/** Control flow: which step follows which. Data flow: who produces and who reads each key. */
export type Mode = "control" | "data";

export interface PreviewProps {
  state: PreviewState;
  direction: Direction;
  onDirection: (direction: Direction) => void;
  mode: Mode;
  onMode: (mode: Mode) => void;
  /** A step, a loop or the first problem was clicked: move the cursor to its line. */
  onOpen: (item: { name: string; line: number | null }) => void;
}

export function Preview({ state, direction, onDirection, mode, onMode, onOpen }: PreviewProps) {
  const model = useMemo(() => (state.graph ? stepGraphOf(state.graph) : null), [state.graph]);
  const keys = useMemo(() => (state.graph ? dataKeys(state.graph) : []), [state.graph]);
  const flow = useMemo(() => dataEdges(keys), [keys]);
  // What data flow draws: the arrows of the node clicked last, or of the key picked.
  const [selected, setSelected] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  useEffect(() => {
    if (selected && model && !(selected in model.nodes)) setSelected(null);
    if (focusKey && !keys.some((k) => k.key === focusKey)) setFocusKey(null);
  }, [model, keys, selected, focusKey]);

  const errors = state.problems.filter((p) => p.severity === "error");
  const warnings = state.problems.filter((p) => p.severity === "warning");
  const first = errors[0] ?? warnings[0];
  let summary: string;
  if (state.status) summary = state.status;
  else if (errors.length) summary = `${errors.length} error${errors.length === 1 ? "" : "s"}` + (state.graph ? ": showing the last graph that compiled" : "");
  else if (warnings.length) summary = `compiles, ${warnings.length} warning${warnings.length === 1 ? "" : "s"}`;
  else summary = state.graph ? "compiles" : "waiting for the compiler";

  return (
    <div className="aipv" data-testid="preview" data-stale={state.stale ? "true" : "false"} data-mode={mode}>
      <div className="aipv-bar">
        <strong className="aipv-title">{state.title}</strong>
        <span className={`aipv-summary${errors.length || state.status ? " bad" : ""}`} data-testid="preview-summary">{summary}</span>
        <span className="aipv-toggle mode" role="group" aria-label="mode">
          {([["control", "control flow"], ["data", "data flow"]] as const).map(([m, label]) => (
            <button key={m} type="button" aria-pressed={mode === m} onClick={() => onMode(m)}>{label}</button>
          ))}
        </span>
        <span className="aipv-toggle" role="group" aria-label="direction">
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
      {mode === "data" && model && (
        <div className="aipv-keys" role="group" aria-label="keys" data-testid="preview-keys">
          <span className="aipv-hint">Pick a key, or click a step, to draw who produces it and who reads it:</span>
          {keys.map((k) => (
            <button key={k.key} type="button" aria-pressed={focusKey === k.key}
                    onClick={() => { setSelected(null); setFocusKey((f) => (f === k.key ? null : k.key)); }}>
              <code>{k.key}</code>
            </button>
          ))}
        </div>
      )}
      {model
        ? (
          <div className="aipv-scroll">
            <StepGraph graph={model} direction={direction} flow={mode === "data" ? flow : undefined}
                       selected={selected} focusKey={mode === "data" ? focusKey : null}
                       onSelect={(id) => {
                         const node = model.nodes[id];
                         setFocusKey(null);
                         setSelected((s) => (s === id ? null : id));
                         if (node) onOpen({ name: node.name, line: node.line });
                       }} />
          </div>
        )
        : <p className="aipv-empty">{errors.length ? "The procedure has not compiled yet; the graph appears with its first clean compile." : ""}</p>}
    </div>
  );
}
