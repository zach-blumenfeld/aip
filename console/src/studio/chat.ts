// What the Studio's chat says while build_procedure or edit_procedure runs (plan C4): the CLI's
// `--progress` lines (aip docs/cli-json.md) in plain words, the questions a human step asks, and the
// boundary the Studio shows rather than hides: a step whose script the draft does not have, and the scripts
// the model wrote, which a person reads before the draft runs. No DOM, no
// imports but types: it runs under node as it is (test/studio.test.ts).

import type { Diagnostic, RefusedEvent, StepEvent, ToolEvent } from "../api/console.ts";

/** The last part of a path, which is what a person recognises: `refund-policy.md`. */
const base = (p: string) => p.replace(/\/+$/, "").split("/").pop() || p;

/** A tool call of runah's model, in plain words: "reading refund-policy.md", "compiling refund_handling". `args` is
 *  the CLI's summary: a path, `pattern=...`, or a written file's path and size. */
export function toolWords(e: ToolEvent | RefusedEvent): string {
  if (e.event === "refused") return `its answer at ${e.step} was refused, and went back to it`;
  const args = `${e.args ?? ""}`.trim();
  const path = args.replace(/\s*\(\d+ bytes\)$/, "").replace(/^path=/, "");
  const said = (() => {
    switch (e.tool) {
      case "read_file": return `reading ${base(path) || "a file"}`;
      case "list_files": return path ? `listing the files in ${base(path)}` : "listing the files";
      case "search": return `searching for ${args.replace(/^pattern=/, "") || "a pattern"}`;
      case "write_file": return `writing ${base(path) || "a file"}`;
      case "compile": return `compiling ${base(path) || "the procedure"}`;
      default: return `${e.tool} ${args}`.trim();
    }
  })();
  return e.error ? `${said}: ${e.error}` : said;
}

/** What each step of build_procedure and edit_procedure is doing, for the chat; another step is named as it is. */
const STEP_WORDS: Record<string, string> = {
  prepare: "listed the documents",
  snapshot: "kept the procedure as it was",
  read_documents: "read the documents",
  extract_rules: "worked out the rules",
  ask_user: "took your answers",
  draft: "wrote the procedure",
  rewrite: "made the change",
  compile: "compiled it",
  fix: "fixed what the compiler said",
  test_run: "tried a run",
  review: "reviewed it against the rules",
  diff: "compared it with what it was",
};

/** A step's line of `--progress`, in words: "wrote the procedure", "compiled it". A loop's exit line says how many passes. */
export function stepWords(e: StepEvent): string | null {
  if (e.kind === "Start" || e.kind === "End") return null;
  if (e.kind === "Loop" || e.kind === "For") {
    return e.iterations !== undefined ? `${e.step}: ${e.iterations} pass${e.iterations === 1 ? "" : "es"}` : null;
  }
  return STEP_WORDS[e.step] ?? e.step;
}

/** The questions a human step was given (build_procedure's `ask_user` reads `questions`), as a list. */
export function questionsOf(state: Record<string, unknown>): string[] {
  const q = state.questions;
  if (Array.isArray(q)) return q.map((x) => (typeof x === "string" ? x : JSON.stringify(x)));
  return typeof q === "string" && q.trim() ? [q] : [];
}

/** The steps whose `Run_Script` names a file the draft does not have, by step name, with the path: the compiler's
 *  `missing_file` on a `Run_Script` clause. A person who does not code cannot write it; the Studio says so. */
export function missingScripts(diagnostics: Diagnostic[]): Map<string, string> {
  const out = new Map<string, string>();
  for (const d of diagnostics) {
    const m = /^Run_Script ([^\s:]+)/.exec(d.message);
    if (d.code === "missing_file" && d.step && m) out.set(d.step, m[1]);
  }
  return out;
}

/** The scripts a run wrote: the files under `scripts/` it added or changed, from the draft's text files before the run
 *  and after it, sorted. The Studio shows them, with their text, before the draft can be run or published. */
export function scriptsWritten(before: Record<string, string>, after: Record<string, string>): string[] {
  return Object.keys(after).filter((p) => p.startsWith("scripts/") && after[p] !== before[p]).sort();
}
