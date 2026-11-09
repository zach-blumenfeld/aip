#!/usr/bin/env node
// aip-console (also installed as aip-inspector): serve the console's page from this machine and run
// procedures through the `aip` CLI.
//
//   aip-console [--server URL | FOLDER] [--port N] [--workdir DIR] [--aip PATH]
//
// The page calls the AIP server directly for the catalog, the runs and the audit queries; nothing is
// proxied. Runs go through the CLI, next to the data: the page posts to this process, which spawns
// `aip run --progress` or `aip resume --progress` and relays each JSON line it prints to the page as a
// server-sent event, so scripts run here, the decision model is the one this machine's `aip config`
// names, and the run is recorded on the server by the CLI itself. With a FOLDER (a program directory,
// one holding procedure.aip) instead of a server, runs are local and unrecorded and the server pages
// are hidden.
//
// Endpoints, all under /console/ and only for this machine (loopback Host, same-origin posts):
//   GET  /console/config          {mode, server, local, folder, workdir, aip: {version, language}, minimum}
//   GET  /console/procedure?ref=  `aip info <ref> --json` (the folder's, in folder mode)
//   GET  /console/graph           folder mode: `aip compile --check --json` on the folder, with `source`,
//                                 the text of its procedure.aip
//   POST /console/run             {ref, inputs, session}      -> event stream of `aip run --progress`
//   POST /console/resume          {run_id, answers?, session} -> event stream of `aip resume --progress`
//   POST /console/cancel          {process}                   kills that `aip` and its scripts
//   GET  /console/record?run_id=  `aip runs <run_id> --json`: the run, from this machine's run file or the server
//   GET  /console/runs            `aip runs --json`; in folder mode, this machine's runs of the folder
//   POST /console/wake            starts the local server when the console's server is `aip config server local`
//
// An event stream sends `event: process` (its id, to cancel by) first, then one `data:` event per line
// the CLI printed (step lines, then the final paused, done or error object), then `event: exit` with
// the exit code, signal and stderr. Closing the stream kills the subprocess too. Every run the console
// starts is recorded with `agent: console` and the page's `session`.

import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** The oldest `aip` this console speaks to: 0.9.0, language 0.9: bundles, `aip run` of a folder or a name,
 *  pauses that carry tasks, `aip runs <id> --json`, `aip compile --json` (aip docs/cli-json.md). */
export const MINIMUM_AIP = "0.9.0";

/** Who the console's runs are recorded as (`aip run --agent`). */
export const AGENT = "console";

const DIST = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "dist");
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
  ".woff2": "font/woff2", ".map": "application/json",
};
const STDERR_LIMIT = 64 * 1024;

// ------------------------------------------------------------------ versions (PEP 440, the subset aip uses)

/** A comparable key for `N(.N)*[(a|b|rc)N][.postN][.devN]`, or null when the text is not one. */
export function versionKey(text) {
  const m = /^(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?(?:\.post(\d+))?(?:\.dev(\d+))?$/.exec(text.trim());
  if (!m) return null;
  const release = m[1].split(".").map(Number);
  while (release.length < 4) release.push(0);
  const [, , pre, preN, post, dev] = m;
  // 1.0.dev0 < 1.0a0 < 1.0b0 < 1.0rc0 < 1.0 < 1.0.post0; a .devN sorts before the same version without it.
  const preRank = pre ? { a: 0, b: 1, rc: 2 }[pre] : (dev !== undefined && post === undefined ? -1 : 3);
  return [...release, preRank, pre ? Number(preN) : 0, post !== undefined ? Number(post) : -1,
          dev !== undefined ? Number(dev) : Infinity];
}

export function compareVersions(a, b) {
  const ka = versionKey(a), kb = versionKey(b);
  for (let i = 0; i < ka.length; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
  return 0;
}

/** What `aip --version` printed, read: `{version, language}`, or null when the line is not the 0.9 one
 *  (`aip <version> language <language>`; through 0.8 it said `format`). */
export function parseVersionLine(line) {
  const m = /^aip (\S+) language (\S+)$/.exec(line.trim());
  return m && versionKey(m[1]) !== null ? { version: m[1], language: m[2] } : null;
}

/** `aip --version`: `{version, language}`, or `{problem}` saying why this aip cannot be used. */
export function checkAip(bin) {
  const out = spawnSync(bin, ["--version"], { encoding: "utf8" });
  const install = "Install or upgrade it: `uv tool install --upgrade 'agent-instruction-protocol[server]'` (or the installer, " +
                  "`curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash`), " +
                  "or point --aip (or AIP_BIN) at one.";
  if (out.error) {
    return { problem: `aip-console needs the aip CLI (${MINIMUM_AIP} or newer), and \`${bin}\` could not be run ` +
                      `(${out.error.code ?? out.error.message}). ${install}` };
  }
  const line = `${out.stdout ?? ""}`.trim().split("\n")[0] ?? "";
  const found = out.status === 0 ? parseVersionLine(line) : null;
  if (!found) {
    const said = (line || `${out.stderr ?? ""}`.trim().split("\n")[0] || `exit ${out.status}`);
    return { problem: `aip-console needs aip ${MINIMUM_AIP} or newer; \`${bin} --version\` said "${said}", ` +
                      `which is older than the console's CLI contract. ${install}` };
  }
  if (compareVersions(found.version, MINIMUM_AIP) < 0) {
    return { problem: `aip-console needs aip ${MINIMUM_AIP} or newer; \`${bin}\` is aip ${found.version}. ${install}` };
  }
  return found;
}

/** The `server:` line of `aip config`, read: `{server, local}`. `server` is null for `none`; `local` says it is
 *  the one a command starts on this machine (`server: local  http://127.0.0.1:8247, started when ...`). */
export function parseConfiguredServer(text) {
  const m = /^server: (\S+)(?:[ \t]+(\S+))?/m.exec(text ?? "");
  if (!m || m[1] === "none") return { server: null, local: false };
  if (m[1] === "local") return { server: (m[2] ?? "").replace(/,$/, "") || null, local: true };
  return { server: m[1], local: false };
}

function configuredServer(bin) {
  return parseConfiguredServer(spawnSync(bin, ["config"], { encoding: "utf8" }).stdout);
}

// ------------------------------------------------------------------ arguments

const USAGE = `usage: aip-console [--server URL | FOLDER] [--port N] [--workdir DIR] [--aip PATH]

  --server URL   the AIP server the page reads and the runs are recorded on (default: what \`aip config\` names;
                 \`local\` is the server aip starts on this machine when a command needs it)
  FOLDER         a program directory (procedure.aip) instead: runs are local and unrecorded, and the catalog,
                 history and audit pages are hidden
  --port N       where to serve the console (default 4280; 0 picks a free port)
  --workdir DIR  the runs' working directory, where scripts read and write files (default the current one)
  --aip PATH     the aip CLI to run (default $AIP_BIN, else \`aip\` on PATH); needs ${MINIMUM_AIP} or newer`;

function parseArgs(argv) {
  const args = { port: 4280, workdir: process.cwd(), aip: process.env.AIP_BIN || "aip" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const value = () => {
      if (i + 1 >= argv.length) fail(`${a} needs a value`);
      return argv[++i];
    };
    if (a === "--server") args.server = value();
    else if (a === "--port") args.port = Number(value());
    else if (a === "--workdir") args.workdir = path.resolve(value());
    else if (a === "--aip") args.aip = value();
    else if (a === "-h" || a === "--help") { console.log(USAGE); process.exit(0); }
    else if (a.startsWith("-")) fail(`unknown option ${a}`);
    else if (args.target === undefined) args.target = a;
    else fail(`unexpected argument ${a}`);
  }
  if (!Number.isInteger(args.port) || args.port < 0) fail("--port must be a number");
  return args;
}

function fail(message) {
  console.error(`aip-console: ${message}\n\n${USAGE}`);
  process.exit(2);
}

// ------------------------------------------------------------------ the subprocesses

/** Running `aip` processes by id, so a page can cancel one. */
const running = new Map();

const SESSION = /^[A-Za-z0-9_.-]{1,64}$/;

/** The environment of one `aip`: the console's, with who is running. */
function envFor(setup, session) {
  const env = { ...setup.env, AIP_AGENT: AGENT };
  if (typeof session === "string" && SESSION.test(session)) env.AIP_SESSION = session;
  return env;
}

/** Spawn `aip <args>` and stream what it prints to `res` as server-sent events. */
function stream(res, setup, args, input, session) {
  const id = randomBytes(8).toString("hex");
  res.writeHead(200, { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store", Connection: "keep-alive" });
  const send = (event, data) => res.write(`${event ? `event: ${event}\n` : ""}data: ${data}\n\n`);
  send("process", JSON.stringify({ process: id }));

  // Its own process group, so cancelling stops the scripts it started as well.
  const child = spawn(setup.aip, args, { cwd: setup.cwd, env: envFor(setup, session), detached: true, stdio: ["pipe", "pipe", "pipe"] });
  const entry = { child, done: false, cancelled: false };
  running.set(id, entry);
  let stderr = "";
  let buffered = "";
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    buffered += chunk;
    let nl;
    while ((nl = buffered.indexOf("\n")) >= 0) {
      const line = buffered.slice(0, nl).trim();
      buffered = buffered.slice(nl + 1);
      if (line) send(null, line);
    }
  });
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => { if (stderr.length < STDERR_LIMIT) stderr += chunk; });
  const finish = (code, signal, error) => {
    if (entry.done) return;
    entry.done = true;
    running.delete(id);
    if (buffered.trim()) send(null, buffered.trim());
    send("exit", JSON.stringify({ code, signal, cancelled: entry.cancelled, stderr: stderr.slice(0, STDERR_LIMIT),
                                  ...(error ? { error } : {}) }));
    res.end();
  };
  child.on("error", (e) => finish(null, null, `could not run ${setup.aip}: ${e.message}`));
  child.on("close", (code, signal) => finish(code, signal));
  child.stdin.on("error", () => {});
  child.stdin.end(input === undefined ? "" : JSON.stringify(input));
  // The page went away: nobody will read the outcome, so stop the run where it is.
  res.on("close", () => { if (!entry.done) kill(entry); });
}

function kill(entry) {
  entry.cancelled = true;
  try { process.kill(-entry.child.pid, "SIGTERM"); } catch { entry.child.kill("SIGTERM"); }
}

/** `aip <args>` run to its end: `{status, stdout, stderr}`. */
function aip(setup, args) {
  const out = spawnSync(setup.aip, args, { cwd: setup.cwd, env: envFor(setup), encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  return { status: out.error ? null : out.status, stdout: `${out.stdout ?? ""}`, stderr: `${out.stderr ?? ""}${out.error ? out.error.message : ""}` };
}

/** What a failed `aip` said, for an error envelope. */
function said(out, what) {
  return (out.stderr.trim() || out.stdout.trim() || `${what} exited with ${out.status}`).replace(/^aip: /, "");
}

// ------------------------------------------------------------------ http

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  res.end(JSON.stringify(body));
}

function problem(res, status, kind, message) {
  json(res, status, { error: { kind, message } });
}

async function readJson(req) {
  let text = "";
  for await (const chunk of req) {
    text += chunk;
    if (text.length > 4 * 1024 * 1024) throw new Error("body too large");
  }
  const body = text ? JSON.parse(text) : {};
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("the body must be a JSON object");
  return body;
}

function serveFile(req, res) {
  const url = new URL(req.url, "http://console");
  let rel = decodeURIComponent(url.pathname);
  if (rel === "/" || rel === "") rel = "/index.html";
  const file = path.resolve(DIST, "." + rel);
  if (!file.startsWith(DIST + path.sep) || !existsSync(file) || !statSync(file).isFile()) {
    return problem(res, 404, "not_found", `no file ${url.pathname}`);
  }
  const type = TYPES[path.extname(file)] ?? "application/octet-stream";
  res.writeHead(200, { "Content-Type": type, "Cache-Control": file.endsWith("index.html") ? "no-store" : "public, max-age=3600" });
  res.end(readFileSync(file));
}

const RUN_ID = /^[0-9a-zA-Z_-]{4,64}$/;

function handler(setup, port) {
  const hosts = new Set([`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`]);
  return async (req, res) => {
    // Only pages on this machine: a foreign Host is DNS rebinding, a foreign Origin a cross-site post.
    if (!hosts.has(req.headers.host ?? "")) return problem(res, 403, "forbidden", "the console answers loopback hosts only");
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (!url.pathname.startsWith("/console/")) {
      if (req.method !== "GET" && req.method !== "HEAD") return problem(res, 405, "method_not_allowed", req.method);
      return serveFile(req, res);
    }
    if (req.method === "POST") {
      const origin = req.headers.origin;
      if ((origin && origin !== `http://${req.headers.host}`) || !`${req.headers["content-type"]}`.startsWith("application/json")) {
        return problem(res, 403, "forbidden", "posts come from the console's own page, as JSON");
      }
    }
    try {
      const route = `${req.method} ${url.pathname}`;
      if (route === "GET /console/config") {
        return json(res, 200, { mode: setup.mode, server: setup.server, local: setup.local, folder: setup.folder, workdir: setup.workdir,
                                aip: setup.aipVersion, minimum: MINIMUM_AIP });
      }
      if (route === "GET /console/procedure") {
        const ref = setup.folder ?? url.searchParams.get("ref");
        if (!ref) return problem(res, 400, "invalid_input", "ref is required");
        const out = aip(setup, ["info", ref, "--json"]);
        return out.status === 0 ? json(res, 200, JSON.parse(out.stdout)) : problem(res, 422, "invalid_input", said(out, "aip info"));
      }
      if (route === "GET /console/graph") {
        if (!setup.folder) return problem(res, 404, "not_found", "the graph of a published procedure comes from the server (GET /catalog/{ref}/graph)");
        // Exit 1 with a report is a program with errors: the page shows the diagnostics.
        const out = aip(setup, ["compile", "--check", "--json", setup.folder]);
        let report;
        try { report = JSON.parse(out.stdout); } catch { return problem(res, 422, "invalid_input", said(out, "aip compile")); }
        return json(res, 200, { ok: report.ok === true, bundle_id: report.bundle_id ?? null, diagnostics: report.diagnostics ?? [],
                                graph: report.graph ?? null, source: readFileSync(path.join(setup.folder, "procedure.aip"), "utf8") });
      }
      if (route === "POST /console/run") {
        const body = await readJson(req);
        const ref = setup.folder ?? body.ref;
        if (typeof ref !== "string" || !ref) return problem(res, 400, "invalid_input", "ref is required");
        return stream(res, setup, ["run", ref, "--progress", "--inputs", "-", "--workdir", setup.workdir], body.inputs ?? {}, body.session);
      }
      if (route === "POST /console/resume") {
        const body = await readJson(req);
        if (typeof body.run_id !== "string" || !RUN_ID.test(body.run_id)) return problem(res, 400, "invalid_input", "run_id is required");
        const args = ["resume", body.run_id, "--progress"];
        const answered = body.answers !== undefined && body.answers !== null;
        if (answered) args.push("--answers", "-");
        return stream(res, setup, args, answered ? body.answers : undefined, body.session);
      }
      if (route === "POST /console/cancel") {
        const body = await readJson(req);
        const entry = running.get(body.process);
        if (!entry) return problem(res, 404, "not_found", "no running aip with that id");
        kill(entry);
        return json(res, 200, { cancelled: body.process });
      }
      if (route === "GET /console/record") {
        const id = url.searchParams.get("run_id") ?? "";
        if (!RUN_ID.test(id)) return problem(res, 400, "invalid_input", "run_id is required");
        const out = aip(setup, ["runs", id, "--json"]);
        return out.status === 0 ? json(res, 200, JSON.parse(out.stdout)) : problem(res, 404, "not_found", said(out, "aip runs"));
      }
      if (route === "GET /console/runs") {
        const out = aip(setup, ["runs", "--json", "--limit", "200"]);
        if (out.status !== 0) return problem(res, 502, "server", said(out, "aip runs"));
        const runs = JSON.parse(out.stdout);
        return json(res, 200, setup.folder ? runs.filter((r) => r.target === setup.folder) : runs);
      }
      if (route === "POST /console/wake") {
        if (!setup.local) return problem(res, 404, "not_found", "the console's server is not a local one");
        // Any command that asks the server something starts it when nothing answers (aip docs/server-design.md).
        const out = aip(setup, ["list"]);
        return out.status === 0 ? json(res, 200, { awake: true }) : problem(res, 502, "server", said(out, "aip list"));
      }
      return problem(res, 404, "not_found", `no endpoint ${route}`);
    } catch (e) {
      return problem(res, 400, "invalid_input", e instanceof Error ? e.message : String(e));
    }
  };
}

// ------------------------------------------------------------------ main

function main() {
  const args = parseArgs(process.argv.slice(2));
  const aipVersion = checkAip(args.aip);
  if (aipVersion.problem) {
    console.error(aipVersion.problem);
    process.exit(1);
  }
  if (!existsSync(path.join(DIST, "index.html"))) {
    console.error(`aip-console: no built page at ${DIST}; run \`npm run build\` in the console's folder`);
    process.exit(1);
  }

  let mode, server = null, local = false, folder = null;
  if (args.server !== undefined && args.target !== undefined) fail("give --server or a FOLDER, not both");
  if (args.target !== undefined) {
    if (!existsSync(args.target)) fail(`${args.target} does not exist`);
    folder = realpathSync(path.resolve(args.target));
    if (!existsSync(path.join(folder, "procedure.aip"))) fail(`${args.target} is not a program directory (no procedure.aip)`);
    mode = "folder";
  } else {
    const found = args.server === undefined || args.server === "local" ? configuredServer(args.aip) : { server: args.server, local: false };
    if (args.server === "local" && !found.local) fail("`aip config` does not name a local server; run `aip config server local` first");
    server = found.server;
    local = found.local;
    if (!server) fail("no server: pass --server URL or a program FOLDER, or set one with `aip config server local` (or `aip config server URL`)");
    server = server.replace(/\/+$/, "");
    mode = "server";
  }
  if (!existsSync(args.workdir) || !statSync(args.workdir).isDirectory()) fail(`--workdir ${args.workdir} is not a directory`);

  // What the CLI records on: the console's server (`local` by name, so the CLI starts it when it has
  // stopped), and nothing in folder mode.
  const env = { ...process.env, AIP_SERVER: mode === "folder" ? "none" : local ? "local" : server };
  // `aip` runs from an empty directory, never the workdir: `aip run billing_support` runs ./billing_support when
  // that path exists, so a folder of the name in the workdir would turn a served run into a local one. The
  // workdir reaches the run as `--workdir` (AIP_WORKDIR for its scripts).
  const cwd = mkdtempSync(path.join(tmpdir(), "aip-console-"));
  process.on("exit", () => rmSync(cwd, { recursive: true, force: true }));
  const setup = { mode, server, local, folder, workdir: path.resolve(args.workdir), cwd, aip: args.aip, aipVersion, env };
  // A local server that has stopped is started before the page asks it anything.
  if (local) aip(setup, ["list"]);

  const http = createServer();
  // Loopback only: the page can start runs on this machine.
  http.listen(args.port, "127.0.0.1", () => {
    const port = http.address().port;
    http.on("request", handler(setup, port));
    console.log(`aip-console: http://localhost:${port}/  (${mode === "folder" ? `folder ${folder}` : `server ${server}${local ? " (local)" : ""}`}; ` +
                `aip ${aipVersion.version}; workdir ${args.workdir})`);
  });
  const stop = () => {
    for (const entry of running.values()) kill(entry);
    http.close();
    process.exit(0);
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}

// Run when executed (also through npm's bin symlinks), not when a test imports the version helpers.
if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) main();
