// What a step of each kind is, in words a person who does not write procedures reads, and a small
// glyph for it (issue #25: the graph was hard to read for someone who does not know the keywords).
// The keyword stays on the node as its tooltip, its aria-label and its `data-kind`; this is how the
// graph says it, not a second list of the language's keywords: a kind it does not know is shown by
// its keyword, with no glyph. No DOM, no imports: it runs under node as it is (test/kinds.test.ts).

/** A step kind as the graph shows it: `words` under the name, `icon` an SVG path in a 14 by 14 box,
 *  stroked in the kind's colour (`filled` paths are filled with it too). */
export interface KindLook { words: string; icon: string; filled?: boolean }

const STEPS: Record<string, KindLook> = {
  // a play mark: where a run begins, with its inputs
  Start: { words: "inputs", icon: "M4 2.5 L11.5 7 L4 11.5 Z", filled: true },
  // a gauge: the decision model answers, and how sure it is comes with the answer
  Decide: { words: "model decides", icon: "M1.5 10.5 A5.5 5.5 0 0 1 12.5 10.5 M7 10.5 L9.8 5.6" },
  // one way in, two ways out
  Route: { words: "branches", icon: "M1.5 7 H5.5 L11.5 2.5 M5.5 7 L11.5 11.5" },
  // several answers into one
  Aggregate: { words: "combines answers", icon: "M2 2.5 L7 7 M2 11.5 L7 7 M2 7 H12.5" },
  // a prompt and a cursor: a script runs
  Execute: { words: "runs a script", icon: "M2 3.5 L6 7 L2 10.5 M7.5 11 H12.5" },
  // a speech bubble: handed to whoever is running, an agent or a person
  Task_Agent: { words: "agent task", icon: "M1.5 2.5 H12.5 V9 H7 L4 12 V9 H1.5 Z" },
  // a tick: the result
  End: { words: "result", icon: "M2.5 7.5 L5.5 10.5 L11.5 3.5" },
};

/** A loop's words by how it repeats (`Over` a list, `Until` an answer holds, a number of `Times`). */
const LOOPS: Record<string, string> = { Over: "for each item", Until: "repeats until", Times: "repeats" };

/** How the graph shows a step of `kind`; an unknown kind is its own keyword, with no glyph. */
export function kindLook(kind: string): KindLook {
  return STEPS[kind] ?? { words: kind, icon: "" };
}

/** The words under a loop's name: by its mode when the graph gives one, else by its kind (`For`, `Loop`). */
export function loopWords(kind: string, mode?: string): string {
  return (mode && LOOPS[mode]) || (kind === "For" ? LOOPS.Over : kind === "Loop" ? LOOPS.Until : kind);
}

/** The pixels `words` take at the kind line's size, near enough to centre a glyph beside them. */
export function wordsWidth(words: string): number {
  return Math.round(words.length * 6);
}
