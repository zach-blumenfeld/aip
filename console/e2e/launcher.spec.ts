import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { chmodSync, cpSync, mkdirSync, writeFileSync } from "node:fs";
import { request as httpRequest } from "node:http";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { AGENT, CLI_ENV, CONSOLE_PORT, E2E, FIRST_REVISION_DIR, SERVER } from "./aip";

// The console's process itself (bin/aip-console.mjs): which `aip` it accepts, where it finds the server when
// not told, what it asks the CLI, and that it answers only pages on this machine. No browser.

const LAUNCHER = path.resolve(import.meta.dirname, "..", "bin", "aip-console.mjs");

function launch(args: string[], env: NodeJS.ProcessEnv = {}) {
  return spawnSync(process.execPath, [LAUNCHER, ...args], { env: { ...process.env, ...CLI_ENV, ...env }, encoding: "utf8", timeout: 30_000 });
}

/** A directory holding an `aip` that runs `script`, as another install on the PATH would. */
function fakeAip(name: string, script: string): string {
  const dir = path.join(E2E, name);
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "aip"), `#!/bin/sh\n${script}\n`);
  chmodSync(path.join(dir, "aip"), 0o755);
  return dir;
}

/** The console started on a free port: its address, once it has printed it. */
async function started(args: string[], env: NodeJS.ProcessEnv = {}): Promise<{ child: ChildProcess; url: string }> {
  const child = spawn(process.execPath, [LAUNCHER, ...args, "--port", "0"], { env: { ...process.env, ...CLI_ENV, ...env } });
  const url = await new Promise<string>((resolve, reject) => {
    let out = "", err = "";
    child.stdout!.on("data", (d) => {
      out += d;
      const m = /http:\/\/localhost:\d+\//.exec(out);
      if (m) resolve(m[0]);
    });
    child.stderr!.on("data", (d) => { err += d; });
    child.on("exit", (code) => reject(new Error(`the console exited with ${code}: ${err}`)));
  });
  return { child, url };
}

test("an aip older than 0.9 is refused with the version the console needs", () => {
  // 0.8 printed `format` where 0.9 prints `language`: its line is not the contract's.
  const old = fakeAip("old-aip", 'echo "aip 0.8.1 format 0.8"');
  const out = launch(["--server", SERVER, "--port", "0"], { PATH: `${old}:${process.env.PATH}` });
  expect(out.status).toBe(1);
  expect(out.stderr).toContain("aip-console needs aip 0.9.0 or newer");
  expect(out.stderr).toContain("aip 0.8.1 format 0.8");

  const pre = fakeAip("pre-aip", 'echo "aip 0.9.0.dev1 language 0.9"');
  const before = launch(["--server", SERVER, "--port", "0"], { PATH: `${pre}:${process.env.PATH}` });
  expect(before.status).toBe(1);
  expect(before.stderr).toContain("is aip 0.9.0.dev1");
});

test("a missing aip is named", () => {
  const out = launch(["--server", SERVER, "--port", "0", "--aip", path.join(E2E, "nowhere", "aip")]);
  expect(out.status).toBe(1);
  expect(out.stderr).toContain("needs the aip CLI");
  expect(out.stderr).toContain("could not be run");
});

test("a folder that is not a program directory is refused", () => {
  const out = launch([path.join(E2E, "work"), "--port", "0"]);
  expect(out.status).toBe(2);
  expect(out.stderr).toContain("not a program directory (no procedure.aip)");
});

test("with no --server the console uses the server `aip config` names", async () => {
  const config = path.join(E2E, "launcher-config.json");
  writeFileSync(config, JSON.stringify({ server: SERVER }));
  const { child, url } = await started([], { AIP_CONFIG: config });
  try {
    const res = await fetch(`${url}console/config`);
    const language = /language (\S+)/.exec(spawnSync("aip", ["--version"], { env: { ...process.env, ...CLI_ENV }, encoding: "utf8" }).stdout)![1];
    expect(await res.json()).toMatchObject({ mode: "server", server: SERVER, local: false, aip: { language }, minimum: "0.9.0" });
  } finally {
    child.kill();
  }
});

test("a published name runs as published even when the working directory has a folder of that name", async () => {
  // `aip run billing_support_agent` runs ./billing_support_agent when it exists; the console runs `aip` elsewhere,
  // so the run page still runs the catalog's revision, recorded as a run of it and not of a draft.
  const workdir = path.join(E2E, "decoy-work");
  cpSync(FIRST_REVISION_DIR, path.join(workdir, AGENT), { recursive: true });
  const { child, url } = await started(["--server", SERVER, "--workdir", workdir]);
  try {
    const origin = url.replace(/\/$/, "");
    const res = await fetch(`${url}console/run`, {
      method: "POST", headers: { Origin: origin, "Content-Type": "application/json" },
      body: JSON.stringify({ ref: AGENT, inputs: { message: "Was I billed twice? [decoy]" }, session: "launcher-spec" }),
    });
    const text = await res.text();
    expect(text).toContain("event: process");
    const lines = text.split("\n").filter((l) => l.startsWith('data: {"paused"')).map((l) => JSON.parse(l.slice(6)) as { run_id: string; recorded: boolean });
    expect(lines).toHaveLength(1);
    expect(lines[0].recorded).toBe(true);
    const run = (await (await fetch(`${SERVER}/runs/${lines[0].run_id}`)).json()) as { name: string; revision: string; draft: boolean; identity: { agent: string; session: string } };
    expect(run).toMatchObject({ name: AGENT, revision: "2", draft: false, identity: { agent: "console", session: "launcher-spec" } });

    // The same run, through the launcher, from this machine's run file.
    const record = (await (await fetch(`${url}console/record?run_id=${lines[0].run_id}`)).json()) as { status: string; pause: { step: string } };
    expect(record).toMatchObject({ status: "paused", pause: { step: "triage" } });
    const about = (await (await fetch(`${url}console/procedure?ref=${AGENT}`)).json()) as { revision: string | null; inputs: Record<string, string> };
    expect(about.revision).toBe("2");                              // the published revision, not the folder's null
    expect(about.inputs).toEqual({ message: "string" });
    expect((await fetch(`${url}console/record?run_id=nosuchrun`)).status).toBe(404);
    expect((await fetch(`${url}console/graph`)).status).toBe(404);  // a published procedure's graph is the server's to give
  } finally {
    child.kill();
  }
});

/** A raw request to the running console, with headers a browser would not let a page set. */
function raw(method: string, headers: Record<string, string>, body?: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const req = httpRequest({ host: "127.0.0.1", port: CONSOLE_PORT, path: method === "GET" ? "/console/config" : "/console/run", method, headers },
                            (res) => { res.resume(); resolve(res.statusCode ?? 0); });
    req.on("error", reject);
    req.end(body);
  });
}

test("the console answers only pages on this machine", async () => {
  expect(await raw("GET", { Host: `localhost:${CONSOLE_PORT}` })).toBe(200);
  expect(await raw("GET", { Host: `evil.example.com:${CONSOLE_PORT}` })).toBe(403);       // DNS rebinding
  const body = JSON.stringify({ ref: AGENT, inputs: { message: "x" } });
  expect(await raw("POST", { Host: `localhost:${CONSOLE_PORT}`, Origin: "https://evil.example.com", "Content-Type": "application/json" }, body)).toBe(403);
  expect(await raw("POST", { Host: `localhost:${CONSOLE_PORT}`, "Content-Type": "text/plain" }, body)).toBe(403);   // a form post
});
