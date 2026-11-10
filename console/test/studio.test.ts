// The Studio's chat in words (src/studio/chat.ts): the `--progress` lines of build_procedure and
// edit_procedure as aip docs/cli-json.md prints them, the questions of a human step, the scripts a draft
// lacks, and a new procedure's name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { missingScripts, nameFromBrief, questionsOf, stepWords, toolWords } from "../src/studio/chat.ts";

const tool = (name: string, args: string, error?: string) => ({ event: "tool" as const, step: "draft", task: 0, tool: name, args, ...(error ? { error } : {}) });
const step = (name: string, kind: string, extra: Record<string, unknown> = {}) => ({ event: "step" as const, step: name, kind, pass: null, passes: [], ...extra });

test("the model's tool calls in plain words: what it reads, writes, searches and compiles", () => {
  assert.equal(toolWords(tool("read_file", "docs/refund-policy.md")), "reading refund-policy.md");
  assert.equal(toolWords(tool("read_file", "bundle:assets/draft.md")), "reading draft.md");
  assert.equal(toolWords(tool("write_file", "refund_handling/procedure.aip (1240 bytes)")), "writing procedure.aip");
  assert.equal(toolWords(tool("list_files", "")), "listing the files");
  assert.equal(toolWords(tool("list_files", "docs")), "listing the files in docs");
  assert.equal(toolWords(tool("search", "pattern=refund")), "searching for refund");
  assert.equal(toolWords(tool("compile", "refund_handling")), "compiling refund_handling");
  assert.equal(toolWords(tool("read_file", "../secret", "outside the working directory")), "reading secret: outside the working directory");
  assert.equal(toolWords({ event: "refused", step: "draft", task: 0, errors: ["path: missing"] }), "its answer at draft was refused, and went back to it");
});

test("the steps of build_procedure and edit_procedure in words; Start and End say nothing", () => {
  assert.equal(stepWords(step("draft", "Task_Agent")), "wrote the procedure");
  assert.equal(stepWords(step("compile", "Execute")), "compiled it");
  assert.equal(stepWords(step("rewrite", "Task_Agent")), "made the change");
  assert.equal(stepWords(step("start", "Start")), null);
  assert.equal(stepWords(step("end", "End")), null);
  assert.equal(stepWords(step("revise", "Loop", { exit: "until", iterations: 2 })), "revise: 2 passes");
  assert.equal(stepWords(step("other_step", "Task_Agent")), "other_step");
});

test("a human step's questions, the scripts a draft lacks, a name from a brief", () => {
  assert.deepEqual(questionsOf({ questions: ["Who approves above 100?", "Which areas?"], rules: "..." }), ["Who approves above 100?", "Which areas?"]);
  assert.deepEqual(questionsOf({ rules: "..." }), []);
  const missing = missingScripts([
    { code: "missing_file", severity: "error", message: "Run_Script scripts/open_ticket.py: the file does not exist", line: 57, column: 3, step: "escalate" },
    { code: "missing_file", severity: "error", message: "Use assets/config.json: the file does not exist", line: 58, column: 3, step: "escalate" },
    { code: "unreachable_step", severity: "error", message: "reply is unreachable", line: 64, column: 1, step: "reply" },
  ]);
  assert.deepEqual([...missing], [["escalate", "scripts/open_ticket.py"]]);
  assert.equal(nameFromBrief("A support inbox procedure: refund requests checked against a 100 limit"), "support_inbox_refund");
  assert.equal(nameFromBrief("!!!"), "new_procedure");
  assert.equal(nameFromBrief("100 refunds a day"), "p_100_refunds_day");
});
