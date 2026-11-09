import type { Requires as RequiresBlock } from "../api/types";

/** The interpreter with its minimum version, as one line: `python ≥ 3.10`. */
export function interpreterText(r: RequiresBlock): string {
  return r.interpreter.version ? `${r.interpreter.name} ≥ ${r.interpreter.version}` : r.interpreter.name;
}

/** One line for a table cell: the interpreter, then packages and tools. */
export function requiresText(r: RequiresBlock | null | undefined): string {
  if (!r) return "—";
  return [interpreterText(r), ...r.packages, ...r.tools].join(", ");
}

/** The `requires` block as a list: what the machine that runs the scripts must have. The client checks it
 *  before the first execution step, so the scripts run on the machine of whoever runs the procedure. */
export function Requires({ requires }: { requires: RequiresBlock | null }) {
  if (!requires) return <p className="muted" data-testid="requires">No execution steps: nothing to install.</p>;
  return (
    <ul className="requires-list" data-testid="requires">
      <li>interpreter <code data-testid="requires-interpreter">{interpreterText(requires)}</code></li>
      <li>packages {requires.packages.length
        ? requires.packages.map((p, i) => <span key={p}>{i ? ", " : ""}<code>{p}</code></span>)
        : <span className="muted">none</span>}</li>
      <li>tools {requires.tools.length
        ? requires.tools.map((t, i) => <span key={t}>{i ? ", " : ""}<code>{t}</code></span>)
        : <span className="muted">none</span>}</li>
    </ul>
  );
}
