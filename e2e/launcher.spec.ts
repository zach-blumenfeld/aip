import { spawn, spawnSync } from "node:child_process";
import { chmodSync, cpSync, mkdirSync, writeFileSync } from "node:fs";
import { request as httpRequest } from "node:http";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { CLI_ENV, CONSOLE_PORT, E2E, SERVER } from "./aip";

// The console's process itself (bin/aip-console.mjs): which `aip` it accepts, where it finds the server when
// not told, and that it answers only pages on this machine. No browser.

const LAUNCHER = path.resolve(import.meta.dirname, "..", "bin", "aip-console.mjs");

function launch(args: string[], env: NodeJS.ProcessEnv = {}) {
  return spawnSync(process.execPath, [LAUNCHER, ...args], { env: { ...process.env, ...CLI_ENV, ...env }, encoding: "utf8", timeout: 30_000 });
}

/** A directory holding an `aip` that prints `version`, as an old install on the PATH would. */
function fakeAip(name: string, script: string): string {
  const dir = path.join(E2E, name);
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "aip"), `#!/bin/sh\n${script}\n`);
  chmodSync(path.join(dir, "aip"), 0o755);
  return dir;
}

test("an old aip on the PATH is refused with the version it needs", () => {
  const old = fakeAip("old-aip", 'echo "aip 0.5a1 format 0.5a1"');
  const out = launch(["--server", SERVER, "--port", "0"], { PATH: `${old}:${process.env.PATH}` });
  expect(out.status).toBe(1);
  expect(out.stderr).toContain("aip-console needs aip 0.8.0 or newer");
  expect(out.stderr).toContain("is aip 0.5a1");

  // 0.5a1 itself had no --version at all: refused the same way.
  const older = fakeAip("older-aip", "echo \"aip: unknown command '$1'\" >&2; exit 1");
  const before = launch(["--server", SERVER, "--port", "0"], { PATH: `${older}:${process.env.PATH}` });
  expect(before.status).toBe(1);
  expect(before.stderr).toContain("aip-console needs aip 0.8.0 or newer");
  expect(before.stderr).toContain("unknown command");
});

test("a missing aip is named", () => {
  const out = launch(["--server", SERVER, "--port", "0", "--aip", path.join(E2E, "nowhere", "aip")]);
  expect(out.status).toBe(1);
  expect(out.stderr).toContain("needs the aip CLI");
  expect(out.stderr).toContain("could not be run");
});

test("with no --server the console uses the server `aip config` names", async () => {
  const config = path.join(E2E, "launcher-config.json");
  writeFileSync(config, JSON.stringify({ server: SERVER }));
  const child = spawn(process.execPath, [LAUNCHER, "--port", "0"], { env: { ...process.env, ...CLI_ENV, AIP_CONFIG: config } });
  try {
    const url = await new Promise<string>((resolve, reject) => {
      let out = "";
      child.stdout.on("data", (d) => {
        out += d;
        const m = /http:\/\/localhost:\d+\//.exec(out);
        if (m) resolve(m[0]);
      });
      child.on("exit", (code) => reject(new Error(`the console exited with ${code}`)));
    });
    const res = await fetch(`${url}console/config`);
    const format = /format (\S+)/.exec(spawnSync("aip", ["--version"], { env: { ...process.env, ...CLI_ENV }, encoding: "utf8" }).stdout)![1];
    expect(await res.json()).toMatchObject({ mode: "server", server: SERVER, aip: { format }, minimum: "0.8.0" });
  } finally {
    child.kill();
  }
});

test("a published name runs on the server even when the working directory has a folder of that name", async () => {
  // `aip run billing-support` runs ./billing-support when it exists; the console runs `aip` elsewhere, so the
  // catalog's run page still starts a served run, recorded in the server's history.
  const workdir = path.join(E2E, "decoy-work");
  cpSync(path.join(E2E, "v1", "billing-support"), path.join(workdir, "billing-support"), { recursive: true });
  const child = spawn(process.execPath, [LAUNCHER, "--server", SERVER, "--port", "0", "--workdir", workdir],
                      { env: { ...process.env, ...CLI_ENV } });
  try {
    const url = await new Promise<string>((resolve, reject) => {
      let out = "";
      child.stdout.on("data", (d) => {
        out += d;
        const m = /http:\/\/localhost:\d+\//.exec(out);
        if (m) resolve(m[0]);
      });
      child.on("exit", (code) => reject(new Error(`the console exited with ${code}`)));
    });
    const origin = url.replace(/\/$/, "");
    const res = await fetch(`${url}console/run`, {
      method: "POST", headers: { Origin: origin, "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "billing-support", input: { message: "Was I billed twice? [decoy]" } }),
    });
    const lines = (await res.text()).split("\n").filter((l) => l.startsWith("data: {\"paused\"")).map((l) => JSON.parse(l.slice(6)));
    expect(lines).toHaveLength(1);
    const run = await fetch(`${SERVER}/runs/${lines[0].run_id}`);
    expect(run.status).toBe(200);
    expect(((await run.json()) as { name: string }).name).toBe("billing-support");
    const info = (await (await fetch(`${url}console/skill?ref=billing-support`)).json()) as { info: { revision: string | null } };
    expect(info.info.revision).toBeTruthy();                      // the published revision, not the folder's null
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
  const body = JSON.stringify({ ref: "billing-support", input: { message: "x" } });
  expect(await raw("POST", { Host: `localhost:${CONSOLE_PORT}`, Origin: "https://evil.example.com", "Content-Type": "application/json" }, body)).toBe(403);
  expect(await raw("POST", { Host: `localhost:${CONSOLE_PORT}`, "Content-Type": "text/plain" }, body)).toBe(403);   // a form post
});
