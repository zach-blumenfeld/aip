"""The smallest agent that reaches aip over MCP: no framework and no model of its own.

    uv run python examples/agents/mcp-smoke/run.py [folder | bundle.rl | name]

It starts `aip mcp` over stdio, as any MCP client does, describes `dynamic-policy` (or the
target given), runs it on a small task with two policies, and answers every pause with canned
text where a real agent would do the work. The procedure's `Decide` steps are the decision
model's, so one must be configured (`aip config --decision-model-key KEY`); the run is recorded
where `aip config` points (`aip config server local` records on this machine), under this
client's name:

    aip runs --agent mcp-smoke

What a framework does differently is only who answers the pauses: its MCP client lists the same
six tools and its model reads the same objects (`docs/mcp.md`, `docs/cli-json.md`).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

from mcp import Client, Implementation, StdioServerParameters

NAME = "mcp-smoke"
EXAMPLE = Path(__file__).resolve().parents[2] / "language" / "dynamic-policy"
INPUTS = {
    "task": "Write a two-sentence welcome note for a new customer of Acme Billing.",
    "policies": ["The note is written in English.", "The note does not mention any price or discount."],
}
# What this "agent" answers with, by the key a task asks for: the draft, then the same note again
# should a check send it back for a fix.
CANNED = {"work": "Welcome to Acme Billing, and thank you for joining us. Our support team is here whenever you have a question."}


def aip_mcp() -> StdioServerParameters:
    """The command an MCP client is given: `aip mcp`. The whole environment is passed on, since
    it says where the client's config and its home are."""
    aip = shutil.which("aip")
    command, args = (aip, ["mcp"]) if aip else (sys.executable, ["-m", "aip.client.cli", "mcp"])
    return StdioServerParameters(command=command, args=args, env=dict(os.environ))


def answer(task: dict) -> dict:
    """One task's answer: every key of `answer_with`, from the canned text."""
    return {key: CANNED.get(key, f"(canned {key})") for key in task["answer_with"]}


async def main(target: str) -> int:
    session = f"{NAME}-{int(time.time())}"
    async with Client(aip_mcp(), client_info=Implementation(name=NAME, version="0.9.0")) as client:
        async def call(tool: str, **arguments) -> dict:
            result = await client.call_tool(tool, arguments)
            if result.is_error:
                raise SystemExit(f"{tool} failed: {result.content}")
            return result.structured_content or json.loads(result.content[0].text)

        print("tools:", ", ".join(tool.name for tool in (await client.list_tools()).tools))
        described = await call("describe", target=target)
        if "error" in described:
            print(json.dumps(described, indent=2))
            return 1
        print(f"procedure: {described['name']}  inputs {described['inputs']}")

        stop = await call("run", target=target, inputs=INPUTS, session=session)
        while "paused" in stop:
            tasks = stop["tasks"]
            print(f"paused at {stop['step']}: {len(tasks)} task(s), answering with canned text")
            stop = await call("resume", run_id=stop["run_id"], answers=[answer(task) for task in tasks])
        print(json.dumps(stop, indent=2))
        if "error" in stop:
            return 1
        if stop.get("recorded"):
            print(f"recorded as {stop['run_id']}; see it with: aip runs --agent {NAME}")
        else:
            print(f"run {stop['run_id']} is done and not recorded: run `aip config server local` to record runs on this machine")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else str(EXAMPLE))))
