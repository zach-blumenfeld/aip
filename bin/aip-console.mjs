#!/usr/bin/env node
// aip-console (also installed as aip-inspector): serve the console's page from this machine and run
// procedures through the `aip` CLI.
//
//   aip-console [--server URL | FOLDER] [--port N] [--workdir DIR] [--aip PATH] [--aip-spec PATH]
//
// The page calls the AIP server directly for catalog, history and governance; nothing is proxied.
// Interactive runs go through the CLI, next to the data: the page posts to this process, which
// spawns `aip run --progress` or `aip resume --progress` and relays each JSON line it prints to
// the page as a server-sent event, so scripts run here and their files land in the working
// directory. With a FOLDER instead of a server, runs are local and the server pages are hidden.
//
// Endpoints, all under /console/ and only for this machine (loopback Host, same-origin posts):
//   GET  /console/config       {mode, server, folder, workdir, aip: {version, format}, minimum}
//   GET  /console/skill?ref=   `aip info --json` and `--example-input` for the ref (or the folder)
//   POST /console/run          {ref, input}            -> event stream of `aip run --progress`
//   POST /console/resume       {run_id, input?}        -> event stream of `aip resume --progress`
//   POST /console/cancel       {session}               kills that session's `aip` and its scripts
//   POST /console/validate     {name, files}           `aip-spec validate` on those files: {status, valid, issues}
//   POST /console/upgrade      {name, files}           `aip upgrade` on those files: {status, valid, issues, output, skillMd}
//   POST /console/probe        {name, files, script, stdin, timeout}
//                                                      runs one Python script of those files: {code, stdout, stderr, ...}
//   POST /console/handoff      {name, files}           writes the scaffold to <workdir>/studio/<name>/ for an agent: {dir}
//   POST /console/handoff/read {name}                  that folder's files and a hash of them: {dir, files, hash}
// These are the Studio's agent fill-in (docs/plans/STUDIO-PLAN.md, S6). validate and probe write the files to a fresh
// temporary folder `<name>/` and remove it after. `files` is [{path, mode, b64}]. Without `aip-spec` the validate
// endpoint answers 503 `aip_spec_missing` saying how to install it. A handoff never deletes: a folder already at
// the path is moved to <workdir>/studio/.previous/ first.
//
// An event stream sends `event: session` (its id) first, then one `data:` event per line the CLI
// printed (step lines, then the final pause, done or error object), then `event: exit` with the
// exit code, signal and stderr. Closing the stream kills the subprocess too.

import { spawn, spawnSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { chmodSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** The oldest `aip` this console speaks to: 0.8.0, format 0.8 (`agent-instruction-protocol`, with `aip-spec` beside
 *  it): the `start` step, decision `confidence` and `fallback`, the router's confidence check and the
 *  `no_decision_model` stop in the CLI JSON contract (docs/cli-json.md) all date from it. */
export const MINIMUM_AIP = "0.8.0";

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

/** `aip --version`: `{version, format}`, or `{problem}` saying why this aip cannot be used. */
export function checkAip(bin) {
  const out = spawnSync(bin, ["--version"], { encoding: "utf8" });
  const install = "Install or upgrade it: `uv tool install --upgrade agent-instruction-protocol` (or the installer, " +
                  "`curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash`), " +
                  "or point --aip (or AIP_BIN) at one.";
  if (out.error) {
    return { problem: `aip-console needs the aip CLI (${MINIMUM_AIP} or newer), and \`${bin}\` could not be run ` +
                      `(${out.error.code ?? out.error.message}). ${install}` };
  }
  const line = `${out.stdout ?? ""}`.trim().split("\n")[0] ?? "";
  const m = /^aip (\S+) format (\S+)$/.exec(line);
  if (out.status !== 0 || !m || versionKey(m[1]) === null) {
    const said = (line || `${out.stderr ?? ""}`.trim().split("\n")[0] || `exit ${out.status}`);
    return { problem: `aip-console needs aip ${MINIMUM_AIP} or newer; \`${bin} --version\` said "${said}", ` +
                      `which is older than the console's CLI contract. ${install}` };
  }
  if (compareVersions(m[1], MINIMUM_AIP) < 0) {
    return { problem: `aip-console needs aip ${MINIMUM_AIP} or newer; \`${bin}\` is aip ${m[1]}. ${install}` };
  }
  return { version: m[1], format: m[2] };
}

/** The server `aip config` points at, or null. */
function configuredServer(bin) {
  const out = spawnSync(bin, ["config"], { encoding: "utf8" });
  const m = /^server: (\S+)/m.exec(out.stdout ?? "");
  return m ? m[1] : null;
}

// ------------------------------------------------------------------ arguments

const USAGE = `usage: aip-console [--server URL | FOLDER] [--port N] [--workdir DIR] [--aip PATH] [--aip-spec PATH]

  --server URL   the AIP server the page and the runs use (default: what \`aip config\` names)
  FOLDER         a skill folder instead: runs are local, the catalog, history and governance are hidden
  --port N       where to serve the console (default 4280; 0 picks a free port)
  --workdir DIR  the runs' working directory, where scripts read and write files (default the current one)
  --aip PATH     the aip CLI to run (default $AIP_BIN, else \`aip\` on PATH); needs ${MINIMUM_AIP} or newer
  --aip-spec PATH
                 the validator the Studio checks an agent's fill-in with (default $AIP_SPEC_BIN, else \`aip-spec\`)`;

function parseArgs(argv) {
  const args = { port: 4280, workdir: process.cwd(), aip: process.env.AIP_BIN || "aip", aipSpec: process.env.AIP_SPEC_BIN || "aip-spec" };
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
    else if (a === "--aip-spec") args.aipSpec = value();
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

/** Running `aip` sessions by id, so a page can cancel one. */
const sessions = new Map();

/** Spawn `aip <args>` and stream what it prints to `res` as server-sent events. */
function stream(res, setup, args, input) {
  const id = randomBytes(8).toString("hex");
  res.writeHead(200, { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store", Connection: "keep-alive" });
  const send = (event, data) => res.write(`${event ? `event: ${event}\n` : ""}data: ${data}\n\n`);
  send("session", JSON.stringify({ session: id }));

  // Its own process group, so cancelling stops the scripts it started as well.
  const child = spawn(setup.aip, args, { cwd: setup.cwd, env: setup.env, detached: true, stdio: ["pipe", "pipe", "pipe"] });
  const session = { child, done: false, cancelled: false };
  sessions.set(id, session);
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
    if (session.done) return;
    session.done = true;
    sessions.delete(id);
    if (buffered.trim()) send(null, buffered.trim());
    send("exit", JSON.stringify({ code, signal, cancelled: session.cancelled, stderr: stderr.slice(0, STDERR_LIMIT),
                                  ...(error ? { error } : {}) }));
    res.end();
  };
  child.on("error", (e) => finish(null, null, `could not run ${setup.aip}: ${e.message}`));
  child.on("close", (code, signal) => finish(code, signal));
  child.stdin.on("error", () => {});
  child.stdin.end(input === undefined ? "" : JSON.stringify(input));
  // The page went away: nobody will read the outcome, so stop the run where it is.
  res.on("close", () => { if (!session.done) kill(session); });
}

function kill(session) {
  session.cancelled = true;
  try { process.kill(-session.child.pid, "SIGTERM"); } catch { session.child.kill("SIGTERM"); }
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

/** `aip info <ref> --json` and `--example-input`, for the run page's start form. */
function skill(setup, ref) {
  const run = (flag) => spawnSync(setup.aip, ["info", ref, flag], { cwd: setup.cwd, env: setup.env, encoding: "utf8" });
  const info = run("--json");
  if (info.error || info.status !== 0) {
    return { error: `${info.stderr || info.stdout || info.error?.message || ""}`.trim() || `aip info exited with ${info.status}` };
  }
  const example = run("--example-input");
  return { info: JSON.parse(info.stdout), example_input: example.status === 0 ? JSON.parse(example.stdout) : {} };
}

// ------------------------------------------------------------------ the Studio's checks (S6a)

const SKILL_NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const PROBE_LIMIT = 1024 * 1024;

/** `files` ([{path, mode, b64}]) written under a fresh temporary `<name>/`; the caller removes `root`. Throws on a
 *  path that would leave the folder. */
function writeSkill(name, files) {
  const folder = typeof name === "string" && SKILL_NAME.test(name) ? name : "skill";
  const root = mkdtempSync(path.join(tmpdir(), "aip-console-check-"));
  const dir = path.join(root, folder);
  try {
    writeFiles(dir, files);
  } catch (e) {
    rmSync(root, { recursive: true, force: true });
    throw e;
  }
  return { root, dir };
}

/** `files` written under `dir`; throws on a path that would leave it. */
function writeFiles(dir, files) {
  if (!Array.isArray(files) || files.length === 0) throw new Error("files must be a non-empty list");
  for (const f of files) {
    const rel = `${f?.path ?? ""}`;
    if (!rel || rel.startsWith("/") || rel.split("/").some((p) => p === "" || p === "." || p === "..")) throw new Error(`unsafe path ${rel}`);
    const file = path.join(dir, rel);
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, Buffer.from(`${f.b64 ?? ""}`, "base64"));
    chmodSync(file, Number.isInteger(f.mode) ? f.mode & 0o777 : 0o644);
  }
}

// What a skill folder's snapshot leaves out (as zip.ts does): tool droppings, not the skill's files.
const SKIP_DIRS = new Set([".git", "__pycache__", ".aip", "__MACOSX", "node_modules", ".venv"]);
const SKIP_FILES = new Set([".DS_Store", ".aip-manifest.json"]);
const HANDOFF_LIMIT = 3 * 1024 * 1024;

/** The folder a handoff of skill `name` lives in. */
function handoffDir(setup, name) {
  if (typeof name !== "string" || !SKILL_NAME.test(name)) throw new Error("name must be the skill's kebab-case name");
  return path.join(setup.workdir, "studio", name);
}

/** The scaffold written to <workdir>/studio/<name>/ for an agent to edit in place. What was there is moved aside. */
function handoff(setup, body) {
  const dir = handoffDir(setup, body.name);
  let previous = null;
  if (existsSync(dir)) {
    previous = path.join(setup.workdir, "studio", ".previous", `${body.name}-${new Date().toISOString().replace(/[:.]/g, "-")}`);
    mkdirSync(path.dirname(previous), { recursive: true });
    renameSync(dir, previous);
  }
  writeFiles(dir, body.files);
  return { dir, previous };
}

/** The handoff folder's files (regular files only, no links), and a hash of paths, modes and bytes so the page can
 *  tell when the agent has changed something. */
function readHandoff(setup, body) {
  const dir = handoffDir(setup, body.name);
  if (!existsSync(dir)) return { dir, files: [], hash: null, missing: true };
  const files = [];
  let total = 0;
  const walk = (rel) => {
    for (const item of readdirSync(path.join(dir, rel)).sort()) {
      const sub = rel ? `${rel}/${item}` : item;
      const st = lstatSync(path.join(dir, sub));
      if (st.isDirectory()) { if (!SKIP_DIRS.has(item)) walk(sub); continue; }
      if (!st.isFile() || SKIP_FILES.has(item) || item.endsWith(".pyc")) continue;
      total += st.size;
      if (total > HANDOFF_LIMIT) throw new Error(`the folder holds more than ${HANDOFF_LIMIT / 1024 / 1024} MB`);
      files.push({ path: sub, mode: st.mode & 0o777, b64: readFileSync(path.join(dir, sub)).toString("base64") });
    }
  };
  walk("");
  const hash = createHash("sha256");
  for (const f of files) hash.update(`${f.path}\0${f.mode}\0${f.b64}\0`);
  return { dir, files, hash: hash.digest("hex") };
}

/** Whether `aip-spec` runs here; a working one is remembered, a missing one is looked for again next time. */
let specChecked = false;
function aipSpecProblem(setup) {
  if (specChecked) return null;
  const out = spawnSync(setup.aipSpec, ["--version"], { env: setup.env, encoding: "utf8" });
  if (!out.error && out.status === 0) { specChecked = true; return null; }
  return `The Studio checks an agent's result with the real validator, and \`${setup.aipSpec}\` could not be run ` +
         `(${out.error ? out.error.code ?? out.error.message : `exit ${out.status}`}). Install it with ` +
         "`uv tool install aip-spec` (or the installer, `curl -sSfL https://raw.githubusercontent.com/zach-blumenfeld/aip/main/install.sh | bash`), " +
         "or point --aip-spec (or AIP_SPEC_BIN) at one.";
}

/** `aip-spec validate` on the files: its exit status and the issues it printed on stderr, one JSON object a line. */
function validate(setup, body) {
  const { root, dir } = writeSkill(body.name, body.files);
  try {
    const out = spawnSync(setup.aipSpec, ["validate", dir], { env: setup.env, encoding: "utf8" });
    const issues = `${out.stderr ?? ""}`.split("\n").filter((l) => l.startsWith("{")).flatMap((l) => {
      try {
        const i = JSON.parse(l);
        return [{ ...i, path: typeof i.path === "string" && i.path.startsWith(dir) ? path.relative(dir, i.path) || "SKILL.md" : i.path }];
      } catch { return []; }
    });
    return { status: out.status, valid: out.status === 0, issues, output: `${out.stdout ?? ""}`.replaceAll(dir, body.name ?? "skill").trim() };
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

/** `aip upgrade` on the files (a skill in an earlier format moved to the current one): the command's exit status
 *  (0 valid, 1 written but still invalid, 2 refused and nothing written), what it printed, the validator's issues,
 *  and the rewritten SKILL.md when one was written. */
function upgrade(setup, body) {
  const { root, dir } = writeSkill(body.name, body.files);
  try {
    const before = readFileSync(path.join(dir, "SKILL.md"), "utf8");
    const out = spawnSync(setup.aip, ["upgrade", dir], { cwd: setup.cwd, env: setup.env, encoding: "utf8" });
    if (out.error) throw new Error(`\`${setup.aip} upgrade\` could not be run (${out.error.code ?? out.error.message})`);
    const issues = `${out.stderr ?? ""}`.split("\n").filter((l) => l.startsWith("{")).flatMap((l) => {
      try {
        const i = JSON.parse(l);
        return [{ ...i, path: typeof i.path === "string" && i.path.startsWith(dir) ? path.relative(dir, i.path) || "SKILL.md" : i.path }];
      } catch { return []; }
    });
    const after = readFileSync(path.join(dir, "SKILL.md"), "utf8");
    const noise = `${out.stderr ?? ""}`.split("\n").filter((l) => l && !l.startsWith("{")).join("\n");
    const output = `${out.stdout ?? ""}${noise ? `\n${noise}` : ""}`.replaceAll(dir, body.name ?? "skill").trim();
    return { status: out.status, valid: out.status === 0, issues, output, skillMd: after !== before ? after : null };
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

/** The program `name` resolves to on PATH, or null. */
function onPath(name, env) {
  for (const dir of `${env.PATH ?? ""}`.split(path.delimiter)) {
    if (dir && existsSync(path.join(dir, name)) && statSync(path.join(dir, name)).isFile()) return path.join(dir, name);
  }
  return null;
}

/** One script of the files run the way aip runs a `python` step: from the skill's folder, `python <script>`, the
 *  payload on stdin, AIP_WORKDIR an empty folder. Only Python: the Studio's scripts are Python (v1). */
function probe(setup, body) {
  const script = `${body.script ?? ""}`;
  if (!script.startsWith("scripts/")) throw new Error("script must be a path under scripts/");
  const python = onPath("python", setup.env) ?? onPath("python3", setup.env);
  if (!python) return Promise.resolve({ code: null, error: "no `python` (or `python3`) on this machine's PATH" });
  const timeout = Math.min(Math.max(Number(body.timeout) || 30, 1), 120) * 1000;
  const { root, dir } = writeSkill(body.name, body.files);
  const work = path.join(root, "work");
  mkdirSync(work);
  return new Promise((resolve) => {
    const child = spawn(python, [script], { cwd: dir, env: { ...setup.env, AIP_WORKDIR: work }, detached: true, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "", stderr = "", timedOut = false;
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (c) => { if (stdout.length < PROBE_LIMIT) stdout += c; });
    child.stderr.on("data", (c) => { if (stderr.length < STDERR_LIMIT) stderr += c; });
    const timer = setTimeout(() => { timedOut = true; try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); } }, timeout);
    const done = (out) => { clearTimeout(timer); rmSync(root, { recursive: true, force: true }); resolve(out); };
    child.on("error", (e) => done({ code: null, error: `could not run ${python}: ${e.message}` }));
    child.on("close", (code, signal) => done({ code, signal, timedOut, stdout, stderr: stderr.slice(0, STDERR_LIMIT) }));
    child.stdin.on("error", () => {});
    child.stdin.end(JSON.stringify(body.stdin ?? {}));
  });
}

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
        return json(res, 200, { mode: setup.mode, server: setup.server, folder: setup.folder, workdir: setup.workdir,
                                aip: setup.aipVersion, minimum: MINIMUM_AIP });
      }
      if (route === "GET /console/skill") {
        const ref = setup.folder ?? url.searchParams.get("ref");
        if (!ref) return problem(res, 400, "invalid_input", "ref is required");
        const out = skill(setup, ref);
        return out.error ? problem(res, 422, "invalid_input", out.error) : json(res, 200, out);
      }
      if (route === "POST /console/run") {
        const body = await readJson(req);
        const ref = setup.folder ?? body.ref;
        if (typeof ref !== "string" || !ref) return problem(res, 400, "invalid_input", "ref is required");
        return stream(res, setup, ["run", ref, "--progress", "--input", "-", "--workdir", setup.workdir], body.input ?? {});
      }
      if (route === "POST /console/resume") {
        const body = await readJson(req);
        if (typeof body.run_id !== "string" || !/^[0-9a-zA-Z_-]+$/.test(body.run_id)) {
          return problem(res, 400, "invalid_input", "run_id is required");
        }
        const args = ["resume", body.run_id, "--progress"];
        if (body.input !== undefined && body.input !== null) args.push("--input", "-");
        return stream(res, setup, args, body.input ?? undefined);
      }
      if (route === "POST /console/cancel") {
        const body = await readJson(req);
        const session = sessions.get(body.session);
        if (!session) return problem(res, 404, "not_found", "no running session with that id");
        kill(session);
        return json(res, 200, { cancelled: body.session });
      }
      if (route === "POST /console/validate") {
        const body = await readJson(req);
        const missing = aipSpecProblem(setup);
        if (missing) return problem(res, 503, "aip_spec_missing", missing);
        return json(res, 200, validate(setup, body));
      }
      if (route === "POST /console/upgrade") return json(res, 200, upgrade(setup, await readJson(req)));
      if (route === "POST /console/handoff") return json(res, 200, handoff(setup, await readJson(req)));
      if (route === "POST /console/handoff/read") return json(res, 200, readHandoff(setup, await readJson(req)));
      if (route === "POST /console/probe") {
        const body = await readJson(req);
        return json(res, 200, await probe(setup, body));
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
  const aip = checkAip(args.aip);
  if (aip.problem) {
    console.error(aip.problem);
    process.exit(1);
  }
  if (!existsSync(path.join(DIST, "index.html"))) {
    console.error(`aip-console: no built page at ${DIST}; run \`npm run build\` in the console's checkout`);
    process.exit(1);
  }

  let mode, server = null, folder = null;
  if (args.server !== undefined && args.target !== undefined) fail("give --server or a FOLDER, not both");
  if (args.target !== undefined) {
    folder = path.resolve(args.target);
    if (!existsSync(path.join(folder, "SKILL.md"))) fail(`${args.target} is not a skill folder (no SKILL.md)`);
    mode = "folder";
  } else {
    server = args.server ?? configuredServer(args.aip);
    if (!server) fail("no server: pass --server URL or a skill FOLDER, or set one with `aip config --server URL`");
    server = server.replace(/\/+$/, "");
    mode = "server";
  }
  if (!existsSync(args.workdir) || !statSync(args.workdir).isDirectory()) fail(`--workdir ${args.workdir} is not a directory`);

  const env = { ...process.env };
  if (server) env.AIP_SERVER = server;
  // `aip` runs from an empty directory, never the workdir: `aip run billing-support` runs ./billing-support when
  // that path exists, so a folder of the name in the workdir would turn a served run into a local one. The
  // workdir reaches the run as `--workdir` (AIP_WORKDIR for its scripts).
  const cwd = mkdtempSync(path.join(tmpdir(), "aip-console-"));
  process.on("exit", () => rmSync(cwd, { recursive: true, force: true }));
  const setup = { mode, server, folder, workdir: path.resolve(args.workdir), cwd, aip: args.aip, aipSpec: args.aipSpec, aipVersion: aip, env };

  const http = createServer();
  // Loopback only: the page can start runs on this machine.
  http.listen(args.port, "127.0.0.1", () => {
    const port = http.address().port;
    http.on("request", handler(setup, port));
    console.log(`aip-console: http://localhost:${port}/  (${mode === "folder" ? `folder ${folder}` : `server ${server}`}; ` +
                `aip ${aip.version}; workdir ${args.workdir})`);
  });
  const stop = () => {
    for (const session of sessions.values()) kill(session);
    http.close();
    process.exit(0);
  };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}

// Run when executed (also through npm's bin symlinks), not when a test imports the version helpers.
if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) main();
