// The launcher's reading of what `aip` prints: its version line, and the `server:` and model lines of `aip config`.
// The lines below are the ones aip 0.9.0 prints (src/aip/client/cli.py in this repository).
import assert from "node:assert/strict";
import { test } from "node:test";
import { AGENT, MINIMUM_AIP, STUDIO_AGENT, compareVersions, parseConfiguredServer, parseModels, parseVersionLine, versionKey } from "../bin/aip-console.mjs";

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
    "agent model: none (`--answer-with model` needs one; `aip config --agent-model-key KEY` (...))\nbatch: 10\n";
  assert.deepEqual(parseModels(none), { agent: null, decision: null });
  const file = "decision model: https://api.typesafe.ai  (TypeSafe's, the default)  key: set  (from /home/x/.aip/config.json)\n" +
    "agent model: https://api.anthropic.com/v1  model: claude-opus-5-5  key: set  (from /home/x/.aip/config.json); per task at most 40 tool calls, 500000 tokens\n";
  assert.deepEqual(parseModels(file), {
    agent: { endpoint: "https://api.anthropic.com/v1", model: "claude-opus-5-5", key: true, source: "/home/x/.aip/config.json" },
    decision: { endpoint: "https://api.typesafe.ai", model: null, key: true, source: "/home/x/.aip/config.json" },
  });
  const env = "decision model: http://127.0.0.1:8  key: none  (from AIP_DECISION_MODEL)\n" +
    "agent model: http://127.0.0.1:9/v1  model: stand-in-1  key: set  (from AIP_AGENT_MODEL, AIP_AGENT_MODEL_KEY, AIP_AGENT_MODEL_NAME); per task at most 40 tool calls, 500000 tokens\n";
  const read = parseModels(env);
  assert.equal(read.decision.key, false);
  assert.equal(read.agent.source, "AIP_AGENT_MODEL, AIP_AGENT_MODEL_KEY, AIP_AGENT_MODEL_NAME");
  assert.equal(STUDIO_AGENT, "studio");
});
