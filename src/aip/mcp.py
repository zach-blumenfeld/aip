"""`aip mcp`: the SDK as an MCP server (`docs/mcp.md`), for the agent frameworks and coding
agents that reach tools over the Model Context Protocol.

    aip mcp                  over stdio, the process an MCP client starts
    aip mcp --http 8765      over streamable HTTP, at http://127.0.0.1:8765/mcp

It is `aip.Client` in a process and nothing more: six tools, each one SDK call, each answering
with the object the CLI prints for the same thing (`docs/cli-json.md`).

    search    published procedures by what they do          Client.search
    describe  what a procedure does and what to give it     Client.describe
    compile   check a program directory, write its bundle   Client.compile
    run       run a procedure until it pauses or is done    Client.run
    resume    answer a pause, or retry a failed step        Client.resume
    pull      put a published procedure in the cache        Client.pull, pull_all

A run that pauses, a run that fails and a call that cannot be made all answer with an ordinary
result, not an MCP error: the object's first key says which (`paused`, `done`, `error`), exactly
as on the command line, so the caller's model reads one contract and a framework that raises on
a tool error does not lose the pause to an exception. Only a bug in this server is an MCP error.

Who ran it (`docs/language/runtime.md`, The record): the run's `agent` is the name the MCP
client gave for itself when it connected (`claude-code`, `langgraph`, ...), unless `aip mcp
--agent` names one; with neither, `AIP_AGENT`, else `mcp`. Its `session` is the `session` the
`run` call was given, else `aip mcp --session` or `AIP_SESSION`, else an id made when this
server started, so the runs of one connection are found together.

This module imports the MCP SDK (`mcp` 2.x: `MCPServer`, where 1.x had `FastMCP`), so the rest
of the package imports it only to serve.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from aip.client.config import AGENT_ENV, SESSION_ENV
from aip.client.runs import error_outcome
from aip.errors import AipError
from aip.sdk import Client, CompileError, RunError

JSON = dict[str, Any]
MCP_AGENT = "mcp"                  # the record's `agent` when nobody says who is calling
TOOLS = ("search", "describe", "compile", "run", "resume", "pull")

INSTRUCTIONS = """\
AIP runs procedures: reviewed, step-by-step instructions (a runbook, a workflow, a decision
process) that the runtime walks so that you do not improvise them. Use a procedure when one
fits the task.

1. Find one with `search` (the published catalog), or take a path you were given: a program
   directory holding `procedure.aip`, or an `.rl` bundle.
2. `describe` it to see what it does and the inputs it expects.
3. `run` it with those inputs. The reply's first key says where it stopped:
   - `"done": true`: `result` is the outcome.
   - `"paused": "task"`: the procedure needs you. Do what each task's `prompt` asks, using its
     `state`, then call `resume` with the `run_id` and one answer per task: an object with
     exactly the keys of the task's `answer_with`. Repeat until the run is done.
   - `"error": <kind>`: read `message`. When `resumable` is true, fix the cause and call
     `resume` (with no answers to retry a failed step, with corrected answers after a refused
     one).
Never skip a pause or invent a procedure's result: the run is recorded step by step.
"""


def failure(exc: AipError) -> JSON:
    """A call that failed, as the object the CLI prints: a run's own error object, or
    `invalid_input` with `kind` saying which (`not_found`, `no_server`, `compile_error`, ...)
    for a target, a reference or an argument that cannot be used. A program directory that does
    not compile carries the compiler's `diagnostics`, which the CLI prints on stderr."""
    if isinstance(exc, RunError):
        return exc.to_json()
    detail: JSON = {"kind": exc.kind} if exc.kind not in ("invalid_input", "error") else {}
    if isinstance(exc, CompileError):
        detail["diagnostics"] = [d.to_dict() for d in exc.diagnostics]
    return error_outcome({"error": "invalid_input", "step": None, "message": str(exc), **detail}, None, None, None, False)


def client_name(ctx: Context) -> str | None:
    """The name the MCP client gave for itself (`clientInfo.name`), or None when it gave none."""
    try:
        params = ctx.session.client_params
    except (AttributeError, ValueError):
        return None
    info = getattr(params, "client_info", None)
    name = getattr(info, "name", None)
    return name.strip() or None if isinstance(name, str) else None


def build(client: Client | None = None, *, agent: str | None = None, session: str | None = None) -> MCPServer:
    """The MCP server over `client` (default: the configured one, `aip config`). `agent`
    replaces the MCP client's own name in the record; `session` is the session of every run a
    call does not give one (default `AIP_SESSION`, else an id made here)."""
    from aip.client.cli import version_line

    client = client if client is not None else Client()
    default_session = session or os.environ.get(SESSION_ENV) or f"mcp-{uuid.uuid4().hex[:8]}"
    server = MCPServer("aip", title="Agent Instruction Protocol", instructions=INSTRUCTIONS,
                       version=version_line().split()[1], log_level="WARNING")

    def who(ctx: Context) -> str:
        return agent or client_name(ctx) or os.environ.get(AGENT_ENV) or MCP_AGENT

    def stopped(result: Any) -> JSON:
        """Where a run stopped, as the CLI's object. A stop the configured server did not take
        is said on stderr, as the CLI says it; the object's `recorded` is false."""
        if result.recorded is False:
            print(f"aip mcp: not recorded: {client.recording_error or 'the server did not take it'}; the next stop will try again",
                  file=sys.stderr)
        return result.to_json()

    def reporter(ctx: Context):
        """`on_step` for a run: each history entry as an MCP progress notification, for a client
        that asked for them. The tool runs on a worker thread, so the notification crosses back
        to the event loop; a client or a transport that takes none ends the reporting, never the run."""
        import anyio.from_thread

        sent = {"n": 0, "on": True}

        def on_step(line: JSON) -> None:
            if not sent["on"]:
                return
            sent["n"] += 1
            where = f"{line.get('kind')} {line.get('step')}" + (f" (pass {line['pass']})" if line.get("pass") is not None else "")
            try:
                anyio.from_thread.run(ctx.report_progress, float(sent["n"]), None, where)
            except Exception:
                sent["on"] = False
        return on_step

    @server.tool()
    def search(query: str, limit: int = 10) -> dict[str, Any]:
        """Find published procedures by what they do. Returns `hits`, best first: each has the
        `name` to give `describe` and `run`, its `revision`, a `score` and its `description`.
        Needs a configured server; a procedure on disk needs no search, give its path to
        `describe` or `run`."""
        try:
            return {"hits": [h.data for h in client.search(query, limit)]}
        except AipError as exc:
            return failure(exc)

    @server.tool()
    def describe(target: str) -> dict[str, Any]:
        """What a procedure does and what to give it. `target` is a published name (`name` or
        `name@revision`), a program directory (the folder holding `procedure.aip`) or an `.rl`
        bundle. Returns its `description`, when to use it (`use_when`, `avoid`), its `inputs`
        (key to type, with `input_descriptions`), `example_inputs` to edit and pass to `run`,
        its `steps` and the keys of its `result`."""
        try:
            d = client.describe(target)
            return {**d.data, "example_inputs": d.example_inputs}
        except AipError as exc:
            return failure(exc)

    @server.tool()
    def compile(folder: str, output: str | None = None) -> dict[str, Any]:
        """Check a program directory (the folder holding `procedure.aip`). Returns `ok`, the
        procedure's `name`, its `bundle_id` when it compiles, and every diagnostic (`code`,
        `severity`, `message`, `line`, `column`, `step`): fix the errors and compile again.
        With `output`, a path ending in `.rl`, the bundle is written there."""
        try:
            c = client.compile(folder, output)
        except AipError as exc:
            return failure(exc)
        except OSError as exc:
            return failure(AipError(f"{folder}: {exc}", "not_found"))
        return {"ok": c.ok, "name": c.name, "bundle_id": c.bundle_id, "diagnostics": [d.to_dict() for d in c.diagnostics],
                "output": str(c.output) if c.output else None}

    @server.tool()
    def run(ctx: Context, target: str, inputs: dict[str, Any] | None = None, session: str | None = None,
            batch: int | None = None, workdir: str | None = None) -> dict[str, Any]:
        """Run a procedure until it pauses or is done. `target` is a published name (`name` or
        `name@revision`), a program directory or an `.rl` bundle; `inputs` is the object
        `describe` shows under `inputs`. The reply's first key says where the run stopped:
        `"done": true` with `result`; `"paused": "task"` with `run_id` and `tasks`, to answer
        with `resume`; or `"error": <kind>` with `message` and `resumable`. `session` is an id
        of your choosing that groups this run with others in the record; `workdir` is the
        directory the procedure's scripts read and write files in (default: this server's);
        `batch` is how many passes of a loop over a list run at once (default 10)."""
        try:
            return stopped(client.run(target, inputs or {}, batch=batch, agent=who(ctx), session=session or default_session,
                                      workdir=workdir, on_step=reporter(ctx)))
        except AipError as exc:
            return failure(exc)

    @server.tool()
    def resume(ctx: Context, run_id: str, answers: dict[str, Any] | list[Any] | None = None) -> dict[str, Any]:
        """Answer a paused run, or retry a failed one. `run_id` is the one `run` returned.
        `answers` answers every task of the pause at once: for a pause with one task, the answer
        object itself, with exactly the keys of the task's `answer_with` (`{"reply": "..."}`);
        for several tasks, a list of answer objects in task order, or an object keyed by task
        `index` (`{"0": {...}, "1": {...}}`). A `true_or_false` key takes true or false, a
        `choice` or `score` key one of the task's `labels`. An answer that does not fit is
        refused as `invalid_output` naming what is wrong, and the pause stands: answer again.
        With no `answers`, retry the step a failed run stopped at, once its cause is fixed.
        Returns what `run` returns."""
        try:
            return stopped(client.resume(run_id, answers, agent=who(ctx), on_step=reporter(ctx)))
        except AipError as exc:
            return failure(exc)

    @server.tool()
    def pull(ref: str | None = None) -> dict[str, Any]:
        """Put a published procedure's bundle in this machine's cache, so `run` works on it
        when the server cannot be reached. `ref` is `name` or `name@revision`; with none, every
        published name. Returns `pulled`: each `name`, `revision`, `bundle_id`, the `path` of
        the cached bundle and whether it was `fetched` now or already there."""
        try:
            pulled = [client.pull(ref)] if ref else client.pull_all()
        except AipError as exc:
            return failure(exc)
        return {"pulled": [{"ref": p.ref, "name": p.name, "revision": p.revision, "bundle_id": p.bundle_id, "path": str(p.path),
                            "fetched": p.fetched} for p in pulled]}

    return server


def serve(client: Client | None = None, *, http: int | None = None, host: str = "127.0.0.1", agent: str | None = None,
          session: str | None = None) -> None:
    """Serve until the client goes away: over stdio, or with `http` (a port) over streamable
    HTTP at `http://<host>:<port>/mcp`. Over stdio, stdout is the protocol's: this process
    prints nothing else there."""
    server = build(client, agent=agent, session=session)
    if http is None:
        server.run("stdio")
    else:
        print(f"aip mcp: http://{host}:{http}/mcp", file=sys.stderr)
        server.run("streamable-http", host=host, port=http)


def result_object(result: Any) -> JSON:
    """The object a tool answered with, from an MCP `CallToolResult`: its structured content,
    or its text read as JSON. For clients written against the MCP SDK, the example under
    `examples/agents/mcp-smoke/` among them."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    text = "".join(getattr(block, "text", "") for block in getattr(result, "content", None) or [])
    return json.loads(text)


__all__ = ["INSTRUCTIONS", "MCP_AGENT", "TOOLS", "build", "client_name", "failure", "result_object", "serve"]
