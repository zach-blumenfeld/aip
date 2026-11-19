// The Studio's chat in words (src/studio/chat.ts): the `--progress` lines of build_procedure and
// edit_procedure as aip docs/cli-json.md prints them, the questions of a human step, the scripts a draft
// lacks, and the scripts a run wrote.
import assert from "node:assert/strict";
import { test } from "node:test";
import { missingScripts, modelWords, questionsOf, scriptsWritten, stepWords } from "../src/studio/chat.ts";

const model = (event: "answer" | "refused" | "gave_up", extra: Record<string, unknown> = {}) => ({ event, step: "draft", run_id: "r1", ...extra });
const step = (name: string, kind: string, extra: Record<string, unknown> = {}) => ({ event: "step" as const, step: name, kind, pass: null, passes: [], ...extra });

test("the model's calls in plain words: what it answered, what was refused, where it gave up", () => {
  assert.equal(modelWords(model("answer", { tokens: 1200 })), "answered draft (1200 tokens)");
  assert.equal(modelWords(model("answer")), "answered draft");
  assert.equal(modelWords(model("refused", { reason: "drafted: missing" })), "its answer at draft was refused, and went back to it: drafted: missing");
  assert.equal(modelWords(model("gave_up", { reason: "refused 4 times" })), "gave up at draft: refused 4 times");
});

test("the steps of build_procedure and edit_procedure in words; Start and End say nothing", () => {
  assert.equal(stepWords(step("draft", "Task_Agent")), "wrote the procedure");
  assert.equal(stepWords(step("compile", "Execute")), "compiled it");
  assert.equal(stepWords(step("write", "Execute")), "saved the files");
  assert.equal(stepWords(step("rewrite", "Task_Agent")), "made the change");
  assert.equal(stepWords(step("start", "Start")), null);
  assert.equal(stepWords(step("end", "End")), null);
  assert.equal(stepWords(step("revise", "Loop", { exit: "until", iterations: 2 })), "revise: 2 passes");
  assert.equal(stepWords(step("other_step", "Task_Agent")), "other_step");
});

test("a human step's questions, the scripts a draft lacks", () => {
  assert.deepEqual(questionsOf({ questions: ["Who approves above 100?", "Which areas?"], rules: "..." }), ["Who approves above 100?", "Which areas?"]);
  assert.deepEqual(questionsOf({ rules: "..." }), []);
  const missing = missingScripts([
    { code: "missing_file", severity: "error", message: "Run_Script scripts/open_ticket.py: the file does not exist", line: 57, column: 3, step: "escalate" },
    { code: "missing_file", severity: "error", message: "Use assets/config.json: the file does not exist", line: 58, column: 3, step: "escalate" },
    { code: "unreachable_step", severity: "error", message: "reply is unreachable", line: 64, column: 1, step: "reply" },
  ]);
  assert.deepEqual([...missing], [["escalate", "scripts/open_ticket.py"]]);
});

test("the scripts a run wrote: under scripts/, added or changed, nothing else", () => {
  const before = { "scripts/keep.py": "same", "scripts/old.py": "v1", "assets/prompt.md": "a" };
  const after = { "scripts/keep.py": "same", "scripts/old.py": "v2", "scripts/new.py": "new", "assets/prompt.md": "b", "assets/docs/p.md": "doc" };
  assert.deepEqual(scriptsWritten(before, after), ["scripts/new.py", "scripts/old.py"]);
  assert.deepEqual(scriptsWritten(after, after), []);
});
