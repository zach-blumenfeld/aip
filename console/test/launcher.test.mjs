// The launcher's reading of what `aip` prints: its version line, and the `server:` and model lines of `aip config`.
// The lines below are the ones aip 0.9.0 prints (src/aip/client/cli.py in this repository).
import assert from "node:assert/strict";
import { test } from "node:test";
import { AGENT, MAX_MODEL_ANSWERS, MINIMUM_AIP, STUDIO_AGENT, STUDIO_PERSON, compareVersions, nextOf, parseConfiguredServer, parseModels, parseVersionLine, versionKey } from "../bin/aip-console.mjs";

test("the version line is 0.9's: `aip <version> language <language>`", () => {
  assert.deepEqual(parseVersionLine("aip 0.9.0 language 0.9\n"), { version: "0.9.0", language: "0.9" });
  assert.deepEqual(parseVersionLine("aip 0.10.1.dev3 language 0.10"), { version: "0.10.1.dev3", language: "0.10" });
  assert.equal(parseVersionLine("aip 0.8.1 format 0.8"), null);          // through 0.8 the second word was `format`
  assert.equal(parseVersionLine("aip: unknown command '--version'"), null);
  assert.equal(parseVersionLine(""), null);
  assert.equal(MINIMUM_AIP, "0.9.0");
  assert.equal(AGENT, "console");
});

test("versions compare as PEP 440 orders them", () => {
  assert.equal(compareVersions("0.9.0", "0.9.0"), 0);
  assert.equal(compareVersions("0.9", "0.9.0"), 0);
  assert.equal(compareVersions("0.8.1", "0.9.0"), -1);
  assert.equal(compareVersions("0.10.0", "0.9.0"), 1);
  assert.equal(compareVersions("0.9.0.dev1", "0.9.0"), -1);
  assert.equal(compareVersions("0.9.0a1", "0.9.0"), -1);
  assert.equal(compareVersions("0.9.0rc1", "0.9.0a2"), 1);
  assert.equal(compareVersions("0.9.0.post1", "0.9.0"), 1);
  assert.equal(versionKey("not a version"), null);
});

test("the server `aip config` names: none, the local one, or a URL", () => {
  assert.deepEqual(
    parseConfiguredServer("server: none (runs are not recorded; run `aip config server local` to record runs on this machine, or `aip config server URL` for a server elsewhere)\ndecision model: none\nbatch: 10\n"),
    { server: null, local: false });
  assert.deepEqual(
    parseConfiguredServer("server: local  http://127.0.0.1:8247, started when a command needs it; its store is /home/you/.local/share/aip/server/store.rl  (from /home/you/.config/aip/config.json)\nbatch: 10\n"),
    { server: "http://127.0.0.1:8247", local: true });
  assert.deepEqual(
    parseConfiguredServer("server: https://aip.example.com  (from AIP_SERVER)\ndecision model: https://api.typesafe.ai (key set)\n"),
    { server: "https://aip.example.com", local: false });
  assert.deepEqual(parseConfiguredServer(""), { server: null, local: false });
  assert.deepEqual(parseConfiguredServer(undefined), { server: null, local: false });
});

test("the models `aip config` names, for the Studio's settings: where, which, whether a key is set, from where", () => {
  const none = "server: none (runs are not recorded; ...)\n" +
    "decision model: none (a Decide fails the run with no_decision_model; run `aip config --decision-model-key KEY`, ...)\n" +
    "batch: 10\nscript timeout: 300 seconds per script\n" +
    "agent:\n  model uri:   https://api.anthropic.com/v1\n  model name:  claude-opus-5-5\n" +
    "  model key:   none (`aip agent` refuses to start; `aip config agent --model-key KEY` (...))\n";
  assert.deepEqual(parseModels(none), {
    agent: { endpoint: "https://api.anthropic.com/v1", model: "claude-opus-5-5", key: false, source: null },
    decision: null,
  });
  const file = "decision model: https://api.typesafe.ai  (TypeSafe's, the default)  key: set  (from /home/x/.aip/config.json)\n" +
    "batch: 10\nscript timeout: 300 seconds per script\n" +
    "agent:  (from /home/x/.aip/config.json)\n  model uri:   https://api.anthropic.com/v1\n  model name:  claude-opus-5-5\n" +
    "  model key:   set\n";
  assert.deepEqual(parseModels(file), {
    agent: { endpoint: "https://api.anthropic.com/v1", model: "claude-opus-5-5", key: true, source: "/home/x/.aip/config.json" },
    decision: { endpoint: "https://api.typesafe.ai", model: null, key: true, source: "/home/x/.aip/config.json" },
  });
  const env = "decision model: http://127.0.0.1:8  key: none  (from AIP_DECISION_MODEL)\n" +
    "agent:  (from AIP_AGENT_MODEL_URI, AIP_AGENT_MODEL_NAME, AIP_AGENT_MODEL_KEY)\n  model uri:   http://127.0.0.1:9/v1\n" +
    "  model name:  stand-in-1\n  model key:   set";
  const read = parseModels(env);
  assert.equal(read.decision.key, false);
  assert.equal(read.agent.model, "stand-in-1");
  assert.equal(read.agent.source, "AIP_AGENT_MODEL_URI, AIP_AGENT_MODEL_NAME, AIP_AGENT_MODEL_KEY");
  // `aip config agent` prints the block alone
  assert.equal(parseModels(env.split("\n").slice(1).join("\n")).agent.endpoint, "http://127.0.0.1:9/v1");
  assert.equal(parseModels("").agent, null);
  assert.equal(STUDIO_AGENT, "studio");
});

test("a driven run: the model answers every pause but a person's step, and the stream ends where it cannot go on", () => {
  const paused = (step, extra = {}) => ({ paused: "task", step, tasks: [], hint: "", run_id: "r1", run_file: "/x", ...extra });
  // Not driven: every pause is the page's, as `aip run` prints it.
  assert.deepEqual(nextOf(paused("summarize"), null), { final: paused("summarize") });
  // Driven: the model answers a step that is not the person's; the person's comes to the page, marked.
  assert.deepEqual(nextOf(paused("summarize"), ["approve"]), { answer: "r1" });
  assert.deepEqual(nextOf(paused("approve"), ["approve"]),
                   { final: paused("approve", { answerer: { person: true, reason: "approve is a step for a person" } }) });
  assert.deepEqual(STUDIO_PERSON, ["ask_user"]);
  // Done or failed ends the stream as it is.
  const done = { done: true, result: {}, run_id: "r1" };
  assert.deepEqual(nextOf(done, ["approve"], paused("summarize")), { final: done });
  const failed = { error: "script_failed", step: "check", message: "boom", run_id: "r1", resumable: true };
  assert.deepEqual(nextOf(failed, []), { final: failed });
  // The model gave up: the run waits, with why.
  const left = nextOf(paused("summarize", { gave_up: "refused 4 times" }), [], paused("summarize"));
  assert.deepEqual(left, { final: paused("summarize", { answerer: { person: false, reason: "refused 4 times" } }) });
  // `aip agent --answer` could not start (no key): the pause it was given stands, with the message.
  const nokey = { error: "invalid_input", step: null, message: "aip agent needs a chat model", run_id: null, resumable: false };
  assert.deepEqual(nextOf(nokey, [], paused("summarize")),
                   { final: paused("summarize", { answerer: { person: false, reason: "aip agent needs a chat model" } }) });
  // A bound on the model's answers per stream.
  assert.equal(nextOf(paused("summarize"), [], null, MAX_MODEL_ANSWERS).final.answerer.person, false);
});
