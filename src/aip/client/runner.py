"""Drive a procedure from the command line: run, pause, resume.

The runner is the client. It posts each step's input, follows `suggested` when nothing
needs a human or agent decision, and pauses when something does:

- `client_task`: the step handed work to the client; the next input must be produced
- `review`: a decision answered below its threshold; the client confirms or overrides
- `decision`: no decision model is available; the client answers the questions itself

A pause writes a run file and exits with PAUSED. `resume` continues from it. In
interactive mode a pause becomes prompts on the terminal instead.
"""

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

from aip.client.backend import Backend

JSON = Dict[str, Any]

EXIT_DONE = 0
EXIT_ERROR = 1
EXIT_PAUSED = 3


@dataclass
class RunFile:
    """Everything needed to continue a paused run."""
    skill_dir: str
    after: str | None            # the step whose output the next input answers (None = start)
    suggested: JSON              # the server's proposed next input; resume input is merged over it
    history: List[JSON]
    pause: JSON                  # {"kind": "client_task"|"review"|"decision", ...details}
    thresholds: Dict[str, float] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    # set when the run is on a server: `resume` rebuilds an HttpBackend from these
    server: str | None = None
    name: str | None = None
    revision: str | None = None
    run_id: str | None = None

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        return path

    @classmethod
    def load(cls, path: Path) -> "RunFile":
        return cls(**json.loads(Path(path).read_text()))


def backend_for(run: RunFile, token: str | None = None, session: Any = None) -> Backend:
    """The backend a run file was written against: the server it names, else the local folder."""
    if run.server:
        from aip.client.backend import HttpBackend

        ref = f"{run.name}@{run.revision}" if run.revision else (run.name or run.skill_dir)
        return HttpBackend(run.server, token, ref, run_id=run.run_id, session=session)
    from aip.client.backend import LocalBackend

    return LocalBackend(Path(run.skill_dir))


@dataclass
class Outcome:
    code: int
    payload: JSON                # final state when done, the pause block when paused
    run_file: Path | None = None


Prompter = Callable[[str], str]


class Runner:
    def __init__(self, backend: Backend, skill_dir: Path, run_file: Path | None = None,
                 interactive: bool = False, prompter: Prompter = input, out=None):
        self.backend = backend
        self.skill_dir = Path(skill_dir)
        self.run_file = run_file or self._default_run_file()
        self.interactive = interactive
        self.prompt = prompter
        self.out = out or sys.stdout

    def _default_run_file(self) -> Path:
        return Path(".aip") / "runs" / f"{self.skill_dir.resolve().name}-{int(time.time())}.json"

    # ------------------------------------------------------------------ entry points

    def start(self, payload: JSON | None, thresholds: Dict[str, float] | None = None) -> Outcome:
        if payload is None:
            start = self.backend.describe()["start"]
            if not self.interactive:
                return self._error(f"no input given; start step {start['step']!r} expects {start['inputs']}")
            payload = self._prompt_inputs(start["inputs"], {})
        return self._drive(after=None, payload=payload, history=[], thresholds=thresholds or {})

    def resume(self, run: RunFile, payload: JSON | None) -> Outcome:
        kind = run.pause["kind"]
        if kind == "decision":
            answers = payload if payload is not None else (
                self._prompt_answers(run.pause["questions"]) if self.interactive else None)
            if answers is None:
                return self._error("resume needs answers for the paused decision")
            response = self.backend.answer_decision(run.after, run.suggested, run.history, answers)
            return self._after_response(response, run.thresholds)
        merged = {**run.suggested, **(payload or {})}
        if payload is None and self.interactive:
            merged = self._prompt_inputs(run.pause["expects"], run.suggested)
        elif payload is None:
            return self._error("resume needs an input for the paused step")
        return self._drive(after=run.after, payload=merged, history=run.history, thresholds=run.thresholds)

    # ------------------------------------------------------------------------- loop

    def _drive(self, after: str | None, payload: JSON, history: List[JSON], thresholds: Dict[str, float]) -> Outcome:
        while True:
            node = self.backend.peek(after, payload)
            if node is not None and node["kind"] == "decision" and not self.backend.has_decision_model():
                pause = {"kind": "decision", "step": node["step"], "questions": node["questions"],
                         "expects": node["inputs"]}
                if self.interactive:
                    answers = self._prompt_answers(node["questions"])
                    response = self.backend.answer_decision(after, payload, history, answers)
                else:
                    return self._pause(self._run_file(after, payload, history, pause, thresholds))
            else:
                response = self.backend.run(after, payload, history, thresholds)
            outcome = self._continue(response, thresholds)
            if outcome is not None:
                return outcome
            after, payload, history = response["ran"], response["suggested"], response["history"]

    def _continue(self, response: JSON, thresholds: Dict[str, float]) -> Outcome | None:
        """Decide what to do with a step response. None means keep going with `suggested`."""
        history = response["history"]
        if response["next"] is None:
            self.out.write(json.dumps({"done": True, "state": response["result"], "history": history}, indent=2) + "\n")
            return Outcome(EXIT_DONE, response["result"])

        if response["kind"] == "client_task":
            pause = {"kind": "client_task", "step": response["ran"], "task": response["result"]["task"],
                     "references": response["result"]["references"], "expects": _expects(response["next"])}
            if self.interactive:
                self.out.write("\n" + response["result"]["task"] + "\n\n")
                payload = self._prompt_inputs(pause["expects"], response["suggested"])
                return self._drive_from(response, payload, thresholds)
            return self._pause(self._run_file(response["ran"], response["suggested"], history, pause, thresholds))

        if response["review"]:
            pause = {"kind": "review", "step": response["ran"], "review": response["review"],
                     "expects": _expects(response["next"])}
            if self.interactive:
                payload = self._prompt_review(response["review"], response["suggested"])
                return self._drive_from(response, payload, thresholds)
            return self._pause(self._run_file(response["ran"], response["suggested"], history, pause, thresholds))
        return None

    def _drive_from(self, response: JSON, payload: JSON, thresholds: Dict[str, float]) -> Outcome:
        return self._drive(after=response["ran"], payload=payload, history=response["history"], thresholds=thresholds)

    def _after_response(self, response: JSON, thresholds: Dict[str, float]) -> Outcome:
        """Continue a run from a response obtained outside the loop (a resumed manual decision)."""
        outcome = self._continue(response, thresholds)
        if outcome is not None:
            return outcome
        return self._drive_from(response, response["suggested"], thresholds)

    # ---------------------------------------------------------------------- outcomes

    def _run_file(self, after: str | None, suggested: JSON, history: List[JSON], pause: JSON,
                  thresholds: Dict[str, float]) -> RunFile:
        fields = getattr(self.backend, "run_file_fields", lambda: {})()
        return RunFile(str(self.skill_dir), after, suggested, history, pause, thresholds, **fields)

    def _pause(self, run: RunFile) -> Outcome:
        path = run.save(self.run_file)
        block = {"paused": run.pause["kind"], "step": run.pause["step"], **{k: v for k, v in run.pause.items() if k not in ("kind", "step")},
                 "suggested": run.suggested, "resume": f"aip resume {path} --input <answer.json>", "run_file": str(path)}
        self.out.write(json.dumps(block, indent=2) + "\n")
        return Outcome(EXIT_PAUSED, block, path)

    def _error(self, message: str) -> Outcome:
        print(f"aip: {message}", file=sys.stderr)
        return Outcome(EXIT_ERROR, {"error": message})

    # ------------------------------------------------------------------- interactive

    def _prompt_inputs(self, expects: JSON, suggested: JSON) -> JSON:
        """One prompt per declared input, typed from the vocabulary, prefilled from `suggested`."""
        result = dict(suggested)
        for name, dtype in expects.items():
            default = suggested.get(name)
            hint = f" [{json.dumps(default)}]" if default is not None else ""
            while True:
                raw = self.prompt(f"{name} ({dtype}){hint}: ").strip()
                if not raw and default is not None:
                    result[name] = default
                    break
                try:
                    result[name] = _coerce(raw, dtype)
                    break
                except ValueError as exc:
                    self.out.write(f"  {exc}\n")
        return result

    def _prompt_answers(self, questions: JSON) -> JSON:
        answers: JSON = {}
        for name, q in questions.items():
            self.out.write(f"\n{name}: {q.get('instructions', '')}\n")
            if q["type"] == "noul":
                if q.get("criteria"):
                    self.out.write(f"  yes: {q['criteria'].get('true', '')}\n  no: {q['criteria'].get('false', '')}\n")
                answers[name] = _coerce(self.prompt("  yes/no: "), "boolean")
            elif q["type"] == "choice":
                for label, desc in q["criteria"].items():
                    self.out.write(f"  {label}: {desc or ''}\n")
                while (label := self.prompt("  choice: ").strip()) not in q["criteria"]:
                    self.out.write(f"  pick one of {list(q['criteria'])}\n")
                answers[name] = label
            else:
                for i, desc in enumerate(q["criteria"]):
                    self.out.write(f"  {i}: {desc}\n")
                while True:
                    level = int(_coerce(self.prompt("  level: "), "integer"))
                    if 0 <= level < len(q["criteria"]):
                        break
                    self.out.write(f"  pick 0..{len(q['criteria']) - 1}\n")
                answers[name] = level
        return answers

    def _prompt_review(self, review: List[JSON], suggested: JSON) -> JSON:
        payload = dict(suggested)
        for item in review:
            name = item["question"]
            self.out.write(f"\n{name}: {item['reason']}  (model says {json.dumps(suggested.get(name))})\n")
            if "probabilities" in item:
                self.out.write("  " + json.dumps(item["probabilities"]) + "\n")
            raw = self.prompt(f"  keep {json.dumps(suggested.get(name))}? enter to keep, or a new value: ").strip()
            if raw:
                current = suggested.get(name)
                dtype = "boolean" if isinstance(current, bool) else "integer" if isinstance(current, int) else "string"
                payload[name] = _coerce(raw, dtype)
        return payload


def _expects(next_node: JSON | None) -> JSON:
    """The input keys the client must produce for what comes next. A router's are the union of its branches'."""
    if next_node is None:
        return {}
    if next_node["kind"] == "router":
        merged: JSON = {}
        for branch in next_node["branches"].values():
            merged.update(_expects(branch))
        return merged
    return dict(next_node.get("inputs", {}))


def _coerce(raw: str, dtype: str) -> Any:
    raw = raw.strip()
    match dtype:
        case "string":
            return raw
        case "integer":
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"expected an integer, got {raw!r}") from None
        case "float":
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f"expected a number, got {raw!r}") from None
        case "boolean":
            if raw.lower() in ("y", "yes", "true", "1"):
                return True
            if raw.lower() in ("n", "no", "false", "0"):
                return False
            raise ValueError(f"expected yes/no, got {raw!r}")
        case _:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                raise ValueError(f"expected JSON for {dtype}, got {raw!r}") from None
