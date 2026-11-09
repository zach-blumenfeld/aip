// The launcher's reading of what `aip` prints: its version line and the `server:` line of `aip config`.
// The lines below are the ones aip 0.9.0 prints (src/aip/client/cli.py in this repository).
import assert from "node:assert/strict";
import { test } from "node:test";
import { AGENT, MINIMUM_AIP, compareVersions, parseConfiguredServer, parseVersionLine, versionKey } from "../bin/aip-console.mjs";

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
