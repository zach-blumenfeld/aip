"""A whole agent harness with aip: one model call a turn, and runah for everything else.

    uv run python examples/harness/assist.py "Triage the 40 emails in ./inbox"

The loop at the bottom is the harness. `model` is one chat call: it is shown the task, what the
last run came to and what the catalog has for the task (`client.search`), and answers with the
procedure to run next and its inputs, or with the answer. When nothing in the catalog fits it
runs `build_procedure`, which is in the catalog like any procedure, so building is not a special
case. Every run, the builder's included, is runah's: recorded, and answered by runah's model
except where a procedure stops for a person. `runah` publishes what `build_procedure` built
under its new name, so the next task like this one finds it, and never publishes over a name
the catalog has.

The same loop is a procedure, `assist` (examples/language/assist), so the top loop can be
recorded and audited too: `aip runah assist -i '{"task": "...", "outcome": ""}'`.

It speaks to the chat endpoint `aip config runah` names (Anthropic's by default) and records
runs on the server `aip config` names.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import aip
from aip.model.answerer import ChatClient, parse_answer

PROMPT = """You plan an agent's next move. The agent does its work only by running procedures:
small programs an AIP runtime runs step by step and records. You choose the next procedure and
its inputs, read what it came to, and choose again until the task is done.

Task: {task}

What the last run came to (none on the first turn):
{outcome}

The catalog's procedures that may fit, best first:
{catalog}

Answer with one JSON object and nothing else:
- {{"run": "<name, folder, or a paused run's run_id>", "inputs": {{...}}}} to run a procedure on its
  Start inputs, every input it lists; to answer a run that is paused, {{"run": "<run_id>",
  "answers": {{...}}}} with the answers its hint asks for.
- {{"done": "<the answer, from what the runs came to, with their run ids>"}} when the task is done,
  or when only the person can say what comes next (then the answer is the question for them).
When nothing fits, run build_procedure with {{"brief": "<what the procedure should do and take>",
"documents": "", "out": "<a folder name>", "title": "<a snake_case name>"}}; then run what it built.
Never build what the catalog has."""


def catalog(client: aip.Client, task: str) -> str:
    """What `client.search` finds for the task, with each procedure's inputs; build_procedure last."""
    lines, names = [], [hit.name for hit in client.search(task, limit=8)]
    for name in names + ([] if "build_procedure" in names else ["build_procedure"]):
        if name == "assist":
            continue
        d = client.describe(name)
        described = d.data.get("input_descriptions") or {}
        inputs = "; ".join(f"{k} ({t}): {described.get(k) or ''}".rstrip(": ") for k, t in d.inputs.items()) or "none"
        lines.append(f"- {name}: {' '.join(d.description.split())}\n    inputs: {inputs}")
    return "\n".join(lines)


def shown(outcome: Any) -> str:
    """A run's stop as the model reads it."""
    if outcome is None or isinstance(outcome, str):
        return outcome or "(none)"
    return json.dumps(outcome.to_json() if hasattr(outcome, "to_json") else outcome, indent=1)[:20_000]


def model(task: str, outcome: Any) -> dict:
    """One chat call: the next move, as {"run", "inputs"} / {"run", "answers"} or {"done"}."""
    s = aip.settings()
    reply = ChatClient(s.runah_model_endpoint, s.runah_model_key).complete(
        s.runah_model, [{"role": "user", "content": PROMPT.format(task=task, outcome=shown(outcome), catalog=catalog(client, task))}])
    step = parse_answer(reply.content)
    print(f"assist: {json.dumps(step)[:400]}", file=sys.stderr, flush=True)
    return step


def runah(client: aip.Client, step: dict) -> Any:
    """`client.runah` on the model's move; an error is an outcome too. A build that is done is
    published under its new name (a draft when the catalog has the name), so it can be run next."""
    try:
        outcome = client.runah(step["run"], inputs=step.get("inputs"), answers=step.get("answers"))
    except aip.AipError as error:
        return {"error": error.kind, "message": str(error), **(error.to_json() if isinstance(error, aip.RunError) else {})}
    if isinstance(outcome, aip.Done) and step["run"].split("@")[0] == "build_procedure" and client.server is not None:
        folder, name = outcome.result["path"], outcome.result["procedure"]
        if name in {entry.name for entry in client.list()}:
            return {"done": outcome.to_json(), "published": f"{name} is taken; uploaded as a draft: run it by its folder {folder}",
                    "draft": client.publish(folder, draft=True).bundle_id}
        published = client.publish(folder)
        return {"done": outcome.to_json(), "published": f"{published.name}@{published.revision}: run it by that name"}
    return outcome


if __name__ == "__main__":
    client, task, outcome = aip.Client(), " ".join(sys.argv[1:]) or "Triage the 40 emails in ./inbox", None
    while True:
        step = model(task, outcome)        # one model call: {"run": name, "inputs": {...}} or {"done": answer}
        if "done" in step: break
        outcome = runah(client, step)      # client.runah, and a build published under its new name
    print(step["done"])
