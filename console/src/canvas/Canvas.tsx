// The card canvas: a procedure drawn from its graph. One card per step (its kind as a badge, its
// description as the title, what it reads and produces, one port per way out quoting where it leads),
// loops as frames around their cards, wires in a gutter on the right (under the cards when they are
// drawn as a row, `direction="right"`). Pan by dragging, zoom with the
// wheel or the buttons, "fit" shows it whole; clicking a card opens it beside the canvas with the lines
// of procedure.aip that wrote it.
//
// It is a component on its own: it takes the graph (and, to show source, the text) as props and keeps
// nothing but its view. The console's procedure page draws a revision with it, and the VS Code
// extension's preview bundles this folder (plan E2). With `editing` it is an editor (plan C2, the
// console's Studio): an open card is a form (CardForm.tsx), "+ card" adds one, a card dragged onto a
// loop's frame moves into it (or out, dropped outside), and `problems`, the compiler's diagnostics of
// what is written now, are drawn on the cards. Every change goes to the host as text edits (edit.ts);
// the host applies them, compiles, and passes the new graph back.

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { AddCardForm, CardForm, type Editing } from "./CardForm.tsx";
import { EditError, move } from "./edit.ts";
import { depthOf, layoutOf, SIZE, type Direction } from "./layout.ts";
import { modelOf, sliceOf, type Card, type Frame, type Graph, type Port } from "./model.ts";
import { withProblems, type Problem } from "./problems.ts";
import "./canvas.css";

export type { Editing } from "./CardForm.tsx";
export type { Problem } from "./problems.ts";

export interface CanvasProps {
  /** The bundle's graph: `graph` of `aip compile --json`, or what a server hands back for a revision. */
  graph: Graph;
  /** The text of procedure.aip. With it, an open card shows the lines that wrote it. */
  source?: string;
  /** How to draw a slice of the source (the console passes its highlighter); plain text without it. */
  renderCode?: (code: string, firstLine: number) => ReactNode;
  /** Names of steps and loops to mark, the ones a run went through. */
  visited?: ReadonlySet<string>;
  /** `down`: one column, the wires in a gutter on the right; `right`: one row, the wires under it. */
  direction?: Direction;
  /** The canvas's height, as CSS. */
  height?: string;
  /** Called with the step or loop opened (its name and first line), or null when it is closed. */
  onOpen?: (item: { name: string; line: number | null } | null) => void;
  /** The compiler's diagnostics to draw on the cards. */
  problems?: Problem[];
  /** Make it an editor; `source` is then required, and the graph must carry the compiler's spans. */
  editing?: Editing;
}

interface View { x: number; y: number; k: number }

const MIN_ZOOM = 0.2, MAX_ZOOM = 2;
const clamp = (k: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, k));

export function Canvas({ graph, source, renderCode, visited, direction = "down", height = "70vh", onOpen, problems, editing }: CanvasProps) {
  const model = useMemo(() => (problems ? withProblems(modelOf(graph), problems).model : modelOf(graph)), [graph, problems]);
  const layout = useMemo(() => layoutOf(model, direction), [model, direction]);
  const viewport = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 });
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const dragged = useRef(false);
  // A card being dragged to move it (editing only): where it started, and how far it has gone, in screen pixels.
  const [carry, setCarry] = useState<{ id: string; x: number; y: number; dx: number; dy: number } | null>(null);
  const [moveError, setMoveError] = useState("");
  const fitted = useRef(false);

  const fit = useCallback(() => {
    const el = viewport.current;
    if (!el || layout.width === 0 || layout.height === 0) return;
    // A row is far wider than any view: fit its height, from its first card, and let the rest be panned to.
    const k = direction === "right"
      ? clamp(Math.min(el.clientHeight / layout.height, 1))
      : clamp(Math.min(el.clientWidth / layout.width, el.clientHeight / layout.height, 1));
    setView({ k, x: Math.max(0, (el.clientWidth - layout.width * k) / 2), y: 0 });
  }, [layout, direction]);

  // An editor keeps its view across edits: only the first picture is fitted.
  useEffect(() => {
    if (editing && fitted.current) return;
    fitted.current = true;
    fit();
  }, [fit, editing]);

  const zoomAt = useCallback((factor: number, px?: number, py?: number) => {
    const el = viewport.current;
    const cx = px ?? (el ? el.clientWidth / 2 : 0), cy = py ?? (el ? el.clientHeight / 2 : 0);
    setView((v) => {
      const k = clamp(v.k * factor);
      return { k, x: cx - ((cx - v.x) * k) / v.k, y: cy - ((cy - v.y) * k) / v.k };
    });
  }, []);

  // The wheel zooms about the pointer; with a modifier-free trackpad scroll that is what a canvas does.
  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const box = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - box.left, e.clientY - box.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, moved: false };
    dragged.current = false;
  };
  const onCardDown = (e: ReactPointerEvent<HTMLDivElement>, card: Card) => {
    if (!editing || e.button !== 0 || card.kind === "Start" || card.kind === "End") return;
    if ((e.target as Element).closest("button, select, input, textarea")) return;
    e.stopPropagation();
    dragged.current = false;
    setCarry({ id: card.id, x: e.clientX, y: e.clientY, dx: 0, dy: 0 });
  };
  /** Drop a carried card: into the innermost frame under the pointer, or out of every frame. */
  const drop = (e: ReactPointerEvent<HTMLDivElement>) => {
    const c = carry;
    setCarry(null);
    if (!c || !editing || source === undefined || Math.abs(c.dx) + Math.abs(c.dy) < 6) return;
    dragged.current = true;
    const el = viewport.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    const wx = (e.clientX - box.left - view.x) / view.k, wy = (e.clientY - box.top - view.y) / view.k;
    const under = Object.values(model.frames)
      .filter((f) => { const b = layout.boxes[f.id]; return b && wx >= b.x && wx <= b.x + b.w && wy >= b.y && wy <= b.y + b.h; })
      .sort((a, b) => depthOf(model, b.id) - depthOf(model, a.id))[0];
    const into = under?.id ?? null;
    const card = model.cards[c.id];
    if (!card || into === card.parent) return;
    // Out of a loop means out of the innermost one it is in: one level at a time, as the source nests.
    try {
      editing.onEdit(move(source, graph, c.id, into), into ? `move ${card.name} into ${model.frames[into]?.name}` : `move ${card.name} out`);
      setMoveError("");
    } catch (err) {
      if (err instanceof EditError) setMoveError(err.message);
      else throw err;
    }
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (carry) {
      setCarry({ ...carry, dx: e.clientX - carry.x, dy: e.clientY - carry.y });
      return;
    }
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!d.moved && Math.abs(dx) + Math.abs(dy) < 4) return;
    d.moved = true;
    dragged.current = true;
    d.x = e.clientX;
    d.y = e.clientY;
    setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    drag.current = null;
    if (carry) drop(e);
  };

  const show = (id: string | null) => {
    if (dragged.current) return;   // the click that ends a pan opens nothing
    setOpen(id);
    setAdding(false);
    const item = id === null ? null : model.cards[id] ?? model.frames[id];
    onOpen?.(item ? { name: item.name, line: item.line } : null);
  };

  /** Open a port's target and bring it into view. */
  const follow = (port: Port) => {
    if (port.target === "") return;   // a way out the compiler finds missing leads nowhere yet
    const el = viewport.current;
    const box = layout.boxes[port.target];
    if (el && box) setView((v) => ({ ...v, x: el.clientWidth / 2 - (box.x + box.w / 2) * v.k, y: Math.max(20, el.clientHeight / 3) - box.y * v.k }));
    dragged.current = false;
    show(port.target);
  };

  const frames = Object.values(model.frames).sort((a, b) => depthOf(model, a.id) - depthOf(model, b.id));
  const cards = Object.values(model.cards);
  const opened: Card | Frame | null = open === null ? null
    : (model.cards[open] as Card | undefined) ?? (model.frames[open] as Frame | undefined) ?? null;
  const targetName = (id: string) => (model.cards[id] ?? model.frames[id])?.name ?? id;

  const portRow = (owner: string, port: Port, i: number) => (
    <button type="button" key={i} className={`aipc-port aipc-port-${port.kind}${port.problem ? " aipc-bad" : ""}`} data-testid="canvas-port"
            data-port={port.label} data-kind={port.kind} data-target={targetName(port.target)} data-problem={port.problem ? "true" : undefined}
            title={port.problem ? `${port.label}: ${port.problem}` : `${port.label} → ${port.quote}`}
            onClick={(e) => { e.stopPropagation(); follow(port); }} aria-label={`${owner}: ${port.label} leads to ${targetName(port.target)}`}>
      <span className="aipc-port-label">{port.label}</span>
      <span className="aipc-port-arrow" aria-hidden="true">→</span>
      <span className="aipc-port-quote">{port.quote}</span>
    </button>
  );

  return (
    <div className="aipc" data-testid="canvas" data-direction={direction}>
      <div className="aipc-tools">
        <button type="button" onClick={() => zoomAt(1 / 1.25)} aria-label="zoom out">−</button>
        <span className="aipc-zoom" data-testid="canvas-zoom">{Math.round(view.k * 100)}%</span>
        <button type="button" onClick={() => zoomAt(1.25)} aria-label="zoom in">+</button>
        <button type="button" onClick={fit} data-testid="canvas-fit">fit</button>
        {editing && <button type="button" onClick={() => { setAdding(true); }} data-testid="canvas-add">+ card</button>}
        <span className="aipc-hint">
          {editing ? "click a card to change it · drag a card onto a loop to move it in, off it to move it out" : "drag to pan · wheel to zoom · click a card to open it"}
        </span>
        {moveError && <span className="aipc-error" role="alert">{moveError}</span>}
      </div>
      <div className="aipc-body" style={{ height }}>
        <div className="aipc-view" ref={viewport} onPointerDown={onPointerDown} onPointerMove={onPointerMove}
             onPointerUp={onPointerUp} onPointerLeave={onPointerUp}>
          <div className="aipc-world" data-testid="canvas-world"
               style={{ width: layout.width, height: layout.height, transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
            {frames.map((frame) => {
              const box = layout.boxes[frame.id];
              if (!box) return null;
              return (
                <div key={frame.id} className={`aipc-frame${open === frame.id ? " open" : ""}${visited?.has(frame.name) ? " visited" : ""}${frame.problems?.length ? " aipc-bad" : ""}`}
                     data-testid="canvas-frame" data-loop={frame.name} data-kind={frame.kind}
                     style={{ left: box.x, top: box.y, width: box.w, height: box.h }}>
                  <button type="button" className="aipc-frame-head" style={{ height: SIZE.frameHead }} onClick={() => show(frame.id)}
                          title={frame.problems?.length ? frame.problems.join("\n") : `${frame.kind} ${frame.name} ${frame.header}`}>
                    <span className="aipc-kind">{frame.kind}</span> <code>{frame.name}</code> <span className="aipc-frame-header">{frame.header}</span>
                  </button>
                  <div className="aipc-frame-foot" style={{ top: (layout.portY[frame.id]?.[0] ?? box.y + box.h) - box.y - SIZE.port / 2 }}>
                    {frame.ports.map((port, i) => portRow(frame.name, port, i))}
                  </div>
                </div>
              );
            })}
            <svg className="aipc-wires" width={layout.width} height={layout.height} aria-hidden="true">
              <defs>
                <marker id="aipc-arrow" viewBox="0 0 8 8" refX="1" refY="4" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
                  <path d="M 0 0 L 8 4 L 0 8 z" />
                </marker>
              </defs>
              {layout.wires.map((wire, i) => (
                <path key={i} d={wire.path} className={`aipc-wire aipc-wire-${wire.kind}${open === wire.from || open === wire.to ? " lit" : ""}`}
                      markerEnd="url(#aipc-arrow)" data-from={targetName(wire.from)} data-to={targetName(wire.to)} />
              ))}
            </svg>
            {cards.map((card) => {
              const box = layout.boxes[card.id];
              if (!box) return null;
              const carried = carry?.id === card.id;
              return (
                <div key={card.id} role="button" tabIndex={0}
                     className={`aipc-card aipc-kind-${card.kind}${open === card.id ? " open" : ""}${visited?.has(card.name) ? " visited" : ""}${card.problems?.length ? " aipc-bad" : ""}${carried ? " carried" : ""}`}
                     data-testid="canvas-card" data-step={card.name} data-kind={card.kind} data-problems={card.problems?.length || undefined}
                     style={{ left: box.x, top: box.y, width: box.w, height: box.h,
                              ...(carried ? { transform: `translate(${carry.dx / view.k}px, ${carry.dy / view.k}px)`, zIndex: 5 } : {}) }}
                     onPointerDown={(e) => onCardDown(e, card)}
                     onClick={() => show(card.id)}
                     onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); dragged.current = false; show(card.id); } }}>
                  <div className="aipc-head"><span className="aipc-kind">{card.kind}</span> <code>{card.name}</code></div>
                  <div className="aipc-title" title={card.title}>{card.title}</div>
                  {card.sections.map((section) => (
                    <div key={section.label} className="aipc-section" data-section={section.label}>
                      <div className="aipc-label">{section.label}</div>
                      {section.rows.map((row, i) => <div key={i} className="aipc-row" title={row}>{row}</div>)}
                    </div>
                  ))}
                  {card.ports.length > 0 && <div className="aipc-ports">{card.ports.map((port, i) => portRow(card.name, port, i))}</div>}
                </div>
              );
            })}
          </div>
        </div>
        {editing && source !== undefined && adding && (
          <AddCardForm graph={graph} model={model} source={source} editing={editing} after={open}
                       onAdded={(name) => { setAdding(false); setOpen(`step:${name}`); }} onClose={() => setAdding(false)} />
        )}
        {editing && source !== undefined && !adding && opened && (
          <CardForm key={opened.id} item={opened} graph={graph} model={model} source={source} editing={editing}
                    onClose={() => { dragged.current = false; show(null); }}>
            <SourceSlice source={source} first={opened.line} last={opened.endLine} renderCode={renderCode} />
          </CardForm>
        )}
        {!editing && opened && (
          <aside className="aipc-detail" data-testid="canvas-detail" data-name={opened.name}>
            <div className="aipc-detail-head">
              <span className="aipc-kind">{opened.kind}</span> <code>{opened.name}</code>
              <button type="button" onClick={() => { dragged.current = false; show(null); }} aria-label="close">×</button>
            </div>
            {"title" in opened
              ? <p className="aipc-detail-title">{opened.title}</p>
              : <p className="aipc-detail-title"><code>{opened.header}</code></p>}
            {"sections" in opened && opened.sections.map((section) => (
              <div key={section.label} className="aipc-detail-section">
                <div className="aipc-label">{section.label}</div>
                <ul>{section.rows.map((row, i) => <li key={i}><code>{row}</code></li>)}</ul>
              </div>
            ))}
            {opened.ports.length > 0 && (
              <div className="aipc-detail-section">
                <div className="aipc-label">then</div>
                <ul>
                  {opened.ports.map((port, i) => (
                    <li key={i}>
                      <span className="aipc-port-label">{port.label}</span> → <button type="button" className="aipc-link" onClick={() => follow(port)}>{targetName(port.target)}</button>
                      <span className="aipc-detail-quote"> {port.quote}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <SourceSlice source={source} first={opened.line} last={opened.endLine} renderCode={renderCode} />
          </aside>
        )}
      </div>
    </div>
  );
}

function SourceSlice({ source, first, last, renderCode }:
                     { source?: string; first: number | null; last: number | null; renderCode?: CanvasProps["renderCode"] }) {
  if (source === undefined) return null;
  const slice = sliceOf(source, first, last);
  if (!slice) return null;
  return (
    <div className="aipc-detail-section aipc-source" data-testid="canvas-source" data-first-line={slice.first}>
      <div className="aipc-label">procedure.aip, from line {slice.first}</div>
      {renderCode ? renderCode(slice.text, slice.first) : <pre>{slice.text}</pre>}
    </div>
  );
}
