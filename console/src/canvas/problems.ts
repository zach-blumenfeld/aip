// The compiler's diagnostics drawn on the cards (plan C2): while a change is half done the Studio
// compiles what is written with `--partial`, and every diagnostic lands on the card or the loop it is
// about, in the compiler's words. A way out the compiler finds missing (a step with no `Next_Step`, a
// route with no branch for a value) is drawn as a red port that leads nowhere; a port whose line the
// compiler faults is red too. No imports but the model, no DOM: it runs under node (test/edit.test.ts).

import type { Card, Frame, Model, Port } from "./model.ts";

/** One diagnostic of `aip compile --json`, the fields the canvas reads. */
export interface Problem { code: string; severity: string; message: string; line: number | null; step: string | null }

/** The model with each problem on its card or loop, and the problems that are about neither (the header,
 *  a named string), for the host to list. */
export function withProblems(model: Model, problems: Problem[]): { model: Model; loose: Problem[] } {
  const cards: Record<string, Card> = Object.fromEntries(Object.entries(model.cards).map(([id, c]) => [id, { ...c, ports: [...c.ports], sections: [...c.sections] }]));
  const frames: Record<string, Frame> = Object.fromEntries(Object.entries(model.frames).map(([id, f]) => [id, { ...f, ports: [...f.ports] }]));
  const items: (Card | Frame)[] = [...Object.values(cards), ...Object.values(frames)];
  const byName = new Map(items.map((i) => [i.name, i]));
  const loose: Problem[] = [];
  const found = new Map<string, Problem[]>();

  for (const p of problems) {
    // By the step the compiler names; else the innermost card or loop whose lines hold the line.
    let item: Card | Frame | undefined = p.step ? byName.get(p.step) : undefined;
    if (!item && p.line !== null) {
      item = items.filter((i) => i.line !== null && i.endLine !== null && i.line <= p.line! && p.line! <= i.endLine)
        .sort((a, b) => (a.endLine! - a.line!) - (b.endLine! - b.line!))[0];
    }
    if (!item) { loose.push(p); continue; }
    found.set(item.id, [...(found.get(item.id) ?? []), p]);
  }

  for (const [id, list] of found) {
    const item = cards[id] ?? frames[id];
    item.problems = list.map((p) => p.message);
    item.ports = item.ports.map((port): Port => {
      const fault = list.find((p) => p.line !== null && p.line === port.line && p.code !== "unreachable_step");
      return fault ? { ...port, problem: fault.message } : port;
    });
    for (const p of list) {
      if (p.code === "missing_next_step" || p.code === "missing_loop_exit") {
        item.ports.push({ kind: "next", label: "next", target: "", quote: "nowhere yet", line: null, problem: p.message });
      } else if (p.code === "missing_branch") {
        const m = /has no branch for (.+?); /.exec(p.message);
        const labels = m ? m[1].split(/, | and /) : ["a value"];
        for (const label of labels) item.ports.push({ kind: "branch", label, target: "", quote: "nowhere yet", line: null, problem: p.message });
      }
    }
    if ("sections" in item) (item as Card).sections.push({ label: "problems", rows: list.map((p) => `${p.code}: ${p.message}`) });
  }
  return { model: { ...model, cards, frames }, loose };
}
