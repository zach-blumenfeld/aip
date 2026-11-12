"""`aip mcp`: the SDK as an MCP server (`docs/mcp.md`), for the agent frameworks and coding
agents that reach tools over the Model Context Protocol.

    aip mcp                  over stdio, the process an MCP client starts
    aip mcp --http 8765      over streamable HTTP, at http://127.0.0.1:8765/mcp

It is `aip.Client` in a process and nothing more: seven tools, each one SDK call, each answering
with the object the CLI prints for the same thing (`docs/cli-json.md`).

    search    published procedures by what they do          Client.search
    describe  what a procedure does and what to give it     Client.describe
    compile   check a program directory, write its bundle   Client.compile
    run       run a procedure until it pauses or is done    Client.run
    resume    answer a pause, or retry a failed step        Client.resume
    runah     run ahead: a chat model answers the tasks     Client.runah
    pull      put a published procedure in the cache        Client.pull, pull_all

A run that pauses, a run that fails and a call that cannot be made all answer with an ordinary
result, not an MCP error: the object's first key says which (`paused`, `done`, `error`), exactly
as on the command line, so the caller's model reads one contract and a framework that raises on
a tool error does not lose the pause to an exception. Arguments that do not fit a tool (one
missing, `answers` given as a string) are answered the same way, in a plain sentence (`Server`).
Only a bug in this server is an MCP error.

Who ran it (`docs/language/runtime.md`, The record): the run's `agent` is the name the MCP
client gave for itself when it connected (`claude-code`, `langgraph`, ...), unless `aip mcp
--agent` names one; with neither, `AIP_AGENT`, else `mcp`. The client's own version is kept
beside it as `agent_version`; runs are filtered by the name alone. Its `session` is the `session` the
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
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, TextContent
from pydantic import ValidationError

from aip.client.config import AGENT_ENV, SESSION_ENV
from aip.client.runs import error_outcome
from aip.errors import AipError
from aip.sdk import Client, CompileError, RunError

JSON = dict[str, Any]
MCP_AGENT = "mcp"                  # the record's `agent` when nobody says who is calling
TOOLS = ("search", "describe", "compile", "run", "resume", "runah", "pull")

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
     exactly the keys of the task's `answer_with` (several tasks: a list of those objects in
     task order, all in one call). Repeat until the run is done.
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


def _client_info(ctx: Context, field: str) -> str | None:
    try:
        params = ctx.session.client_params
    except (AttributeError, ValueError):
        return None
    value = getattr(getattr(params, "client_info", None), field, None)
    return value.strip() or None if isinstance(value, str) else None


def client_name(ctx: Context) -> str | None:
    """The name the MCP client gave for itself (`clientInfo.name`), or None when it gave none."""
    return _client_info(ctx, "name")


def client_version(ctx: Context) -> str | None:
    """The version the MCP client gave for itself (`clientInfo.version`), or None."""
    return _client_info(ctx, "version")


def step_message(line: JSON) -> str:
    """One progress notification's text for a step: its kind and name, and inside loops which
    pass of which loop, innermost first (`Execute check: revise pass 1 of each_ticket pass 2`),
    so two tasks at one step in different passes do not read as one step repeated."""
    passes = line.get("passes") or []
    where = ": " + " of ".join(f"{p['loop']} pass {p['pass']}" for p in reversed(passes)) if passes else ""
    return f"{line.get('kind')} {line.get('step')}{where}"


def stop_message(stop: JSON) -> str:
    """The last progress notification of a call: where the run stopped."""
    if "paused" in stop:
        return f"paused at {stop.get('step')}: {len(stop.get('tasks') or [])} task(s) to answer"
    if stop.get("done"):
        return "done"
    return f"error {stop.get('error')}" + (f" at {stop['step']}" if stop.get("step") else "")


_A = {"object": "an object", "array": "a list", "string": "a string", "integer": "an integer", "number": "a number",
      "boolean": "true or false", "null": "nothing"}
_GOT = {dict: "an object", list: "a list", str: "a string", bool: "a boolean", int: "an integer", float: "a number", type(None): "null"}


def _expected(schema: JSON) -> str:
    """What a tool's argument is, in words, from its JSON schema."""
    kinds = [s.get("type") for s in schema.get("anyOf") or [schema]]
    words = list(dict.fromkeys(_A[k] for k in kinds if k in _A and k != "null"))
    return " or ".join(words) or "another kind of value"


def argument_errors(tool: str, schema: JSON, arguments: JSON, errors: list[JSON]) -> str:
    """One plain sentence for arguments that do not fit a tool: each missing one, each one of
    the wrong kind with what it should be, each one the tool does not take."""
    properties = schema.get("properties") or {}
    said: dict[str, str] = {}
    for error in errors:
        name = str(error["loc"][0]) if error.get("loc") else ""
        if name in said:
            continue
        if error.get("type") == "missing":
            said[name] = f"`{name}` is missing"
        elif name in properties:
            said[name] = f"`{name}` is {_expected(properties[name])}, not {_GOT.get(type(arguments.get(name)), 'that')}"
        else:
            said[name] = f"`{name}`: {error.get('msg')}" if name else str(error.get("msg"))
    takes = ", ".join(f"`{p}`" for p in properties)
    return f"{tool} was not called: " + "; ".join(said.values()) + f". Its arguments are {takes}."


class Server(MCPServer):
    """`MCPServer`, with arguments that do not fit a tool answered as the tools answer everything
    else: an ordinary result holding the CLI's error object (`invalid_input`, kind
    `invalid_arguments`) and a plain sentence, where the SDK would answer an MCP error carrying
    the validator's own text. A model that hands `resume` a string for `answers` reads what
    `answers` is, and a framework that raises on a tool error does not raise here."""

    async def call_tool(self, name: str, arguments: JSON, context: Any = None) -> Any:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            cause, tool = exc.__cause__, self._tool_manager.get_tool(name)
            if not isinstance(cause, ValidationError) or tool is None:
                raise
            message = argument_errors(name, tool.parameters, arguments or {}, cause.errors())
            body = failure(AipError(message, "invalid_arguments"))
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(body, indent=2))], structured_content=body)


def build(client: Client | None = None, *, agent: str | None = None, session: str | None = None) -> MCPServer:
    """The MCP server over `client` (default: the configured one, `aip config`). `agent`
    replaces the MCP client's own name in the record; `session` is the session of every run a
    call does not give one (default `AIP_SESSION`, else an id made here)."""
    from aip.client.cli import version_line

    client = client if client is not None else Client()
    default_session = session or os.environ.get(SESSION_ENV) or f"mcp-{uuid.uuid4().hex[:8]}"
    server = Server("aip", title="Agent Instruction Protocol", instructions=INSTRUCTIONS,
                    version=version_line().split()[1], log_level="WARNING")

    def who(ctx: Context) -> str:
        return agent or client_name(ctx) or os.environ.get(AGENT_ENV) or MCP_AGENT

    def version_of(ctx: Context) -> str | None:
        """The MCP client's version, recorded as the run's `agent_version` when the run's
        `agent` is that client's own name."""
        return client_version(ctx) if who(ctx) == client_name(ctx) else None

    def reporter(ctx: Context):
        """Progress for a run, for a client that asked for it: `on_step` sends each history entry
        as an MCP progress notification, and `stopped` one last notification saying where the
        run stopped (paused at a step, done, or an error), so a client that shows progress need
        not read the result to learn why the stream ended. The tool runs on a worker thread,
        so a notification crosses back to the event loop; a client or a transport that takes
        none ends the reporting, never the run."""
        import anyio.from_thread

        sent = {"n": 0, "on": True}

        def send(message: str) -> None:
            if not sent["on"]:
                return
            sent["n"] += 1
            try:
                anyio.from_thread.run(ctx.report_progress, float(sent["n"]), None, message)
            except Exception:
                sent["on"] = False

        def stopped(stop: JSON) -> JSON:
            send(stop_message(stop))
            return stop
        return (lambda line: send(step_message(line))), stopped

    def driven(ctx: Context, call) -> JSON:
        """One `run` or `resume`: where the run stopped, as the CLI's object. A stop the
        configured server did not take is said on stderr, as the CLI says it; the object's
        `recorded` is false."""
        on_step, stopped = reporter(ctx)
        try:
            result = call(on_step)
        except RunError as exc:
            return stopped(failure(exc))
        except AipError as exc:
            return failure(exc)
        if result.recorded is False:
            print(f"aip mcp: not recorded: {client.recording_error or 'the server did not take it'}; the next stop will try again",
                  file=sys.stderr)
        return stopped(result.to_json())

    @server.tool()
    def search(query: str, limit: int = 10) -> dict[str, Any]:
        """Find published procedures by what they do. Returns `hits`, best first: each has the
        `name` to give `describe` and `run`, its `revision`, its `bundle_id`, a `score` and its
        `description`. The `score` orders the hits of this search and nothing more: a query
        that fits nothing still ranks whatever shares a word with it, so read the first hit's
        `description` (and `describe` it) before taking it for a match.
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
        its `steps` and the keys of its `result`; `result_on_some_paths` lists the result keys
        a run has only when the path it took produced them. A `warning` says so when the
        procedure asks a decision model and none is configured here."""
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
        With `output`, a path ending in `.rl`, the bundle is written there; any other name is
        refused."""
        try:
            c = client.compile(folder, output)
        except AipError as exc:
            return failure(exc)
        except OSError as exc:
            return failure(AipError(f"{folder} cannot be read as a program directory: {exc.strerror or exc}", "not_found"))
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
        `batch` is how many passes of a loop over a list run at once (default 10). A `warning`
        in the reply is something to know before going on (no decision model is configured and
        the procedure asks one). A retired `name@revision` is refused (`kind: "retired"`)."""
        return driven(ctx, lambda on_step: client.run(target, inputs or {}, batch=batch, agent=who(ctx),
                                                      session=session or default_session, workdir=workdir, on_step=on_step,
                                                      agent_version=version_of(ctx)))

    @server.tool()
    def resume(ctx: Context, run_id: str, answers: dict[str, Any] | list[Any] | None = None,
               work: dict[str, Any] | list[Any] | None = None) -> dict[str, Any]:
        """Answer a paused run, or retry a failed one. `run_id` is the one `run` returned.
        `answers` answers every task of the pause at once: for a pause with one task, the answer
        object itself, with exactly the keys of the task's `answer_with` (`{"reply": "..."}`);
        for several tasks, a list of answer objects in task order, or an object keyed by task
        `index` (`{"0": {...}, "1": {...}}`). A `true_or_false` key takes true or false, a
        `choice` or `score` key one of the task's `labels`. An answer that does not fit is
        refused as `invalid_output` naming what is wrong, and the pause stands: answer again.
        With no `answers`, retry the step a failed run stopped at, once its cause is fixed.
        `work`, optional, is what answering cost you, for the record, which keeps it marked
        `reported`: `{"model": "<your model id>", "tool_calls": 3, "tokens": 12000, "seconds":
        40}`, any of them (several tasks: keyed by index like `answers`). Returns what `run`
        returns."""
        return driven(ctx, lambda on_step: client.resume(run_id, answers, agent=who(ctx), on_step=on_step, work=work))

    @server.tool()
    def runah(ctx: Context, target: str, inputs: dict[str, Any] | None = None, answers: dict[str, Any] | list[Any] | None = None,
              human: list[str] | None = None, session: str | None = None, workdir: str | None = None) -> dict[str, Any]:
        """Run ahead: like `run`, but this server's own chat model (`aip config runah`)
        answers each `Task_Agent` task and the run keeps going, stopping at a human step (the
        run pauses there for you, as `run` would: the steps named in `human`, `["none"]` for
        none, or without it the steps written for a person), at the end, at an error, or when
        the model gives up (`answerer` in the reply says why). Use it when the user wants the
        procedure carried through without you doing each task. `target` is what `run` takes, or
        the `run_id` of a run to carry on, with `answers` for its standing pause. Returns what
        `run` returns; refused when no chat model is configured on this server."""
        return driven(ctx, lambda on_step: client.runah(target, inputs, answers, human=human, agent=who(ctx),
                                                        session=session or default_session, workdir=workdir, on_step=on_step,
                                                        agent_version=version_of(ctx)))

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


__all__ = ["INSTRUCTIONS", "MCP_AGENT", "TOOLS", "Server", "argument_errors", "build", "client_name", "client_version", "failure",
           "result_object", "serve", "step_message", "stop_message"]
