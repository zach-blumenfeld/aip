// What the Studio's chat says while build_procedure or edit_procedure runs (plan C4): the CLI's
// `--progress` lines (aip docs/cli-json.md) in plain words, the questions of the person's step, and the
// boundary the Studio shows rather than hides: a step whose script the draft does not have, and the scripts
// the model wrote, which a person reads before the draft runs. No DOM, no
// imports but types: it runs under node as it is (test/studio.test.ts).

import type { Diagnostic, ModelEvent, StepEvent } from "../api/console.ts";

/** The last part of a path, which is what a person recognises: `refund-policy.md`. */
const base = (p: string) => p.replace(/\/+$/, "").split("/").pop() || p;

/** A call of the model that answers a driven run's pauses (`aip agent --answer --progress`, plan C6), in plain words:
 *  "answered draft (1200 tokens)", "its answer at draft was refused, and went back to it". */
export function modelWords(e: ModelEvent): string {
  if (e.event === "refused") return `its answer at ${e.step} was refused, and went back to it${e.reason ? `: ${e.reason}` : ""}`;
  if (e.event === "gave_up") return `gave up at ${e.step}${e.reason ? `: ${e.reason}` : ""}`;
  return `answered ${e.step}${e.tokens !== undefined ? ` (${e.tokens} tokens)` : ""}`;
}

/** What each step of build_procedure and edit_procedure is doing, for the chat; another step is named as it is. */
const STEP_WORDS: Record<string, string> = {
  prepare: "listed the documents",
  snapshot: "kept the procedure as it was",
  read_documents: "read the documents",
  extract_rules: "worked out the rules",
  ask_user: "took your answers",
  draft: "wrote the procedure",
  write: "saved the files",
  apply: "saved the fixes",
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

/** The questions the person's step was given (build_procedure's `ask_user` reads `questions`), as a list. */
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

/** What the reviews of the chat's runs say each script touches: for each path, the last line of a review that names it
 *  (build_procedure's review and edit_procedure's changes list the scripts under `Scripts:`, one line each). A script
 *  no review names is left out. */
export function scriptNotes(reviews: string[], paths: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const review of reviews) {
    for (const line of review.split("\n").map((l) => l.trim())) {
      for (const p of paths) {
        if (line.startsWith(p) || line.startsWith(base(p))) out[p] = line.slice(line.startsWith(p) ? p.length : base(p).length).replace(/^[:\s-]+/, "");
      }
    }
  }
  return out;
}

/** The scripts a run wrote: the files under `scripts/` it added or changed, from the draft's text files before the run
 *  and after it, sorted. The Studio shows them, with their text, before the draft can be run or published. */
export function scriptsWritten(before: Record<string, string>, after: Record<string, string>): string[] {
  return Object.keys(after).filter((p) => p.startsWith("scripts/") && after[p] !== before[p]).sort();
}
