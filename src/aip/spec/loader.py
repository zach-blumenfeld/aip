"""Build the runtime Procedure from a validated skill.

Imports the runtime model lazily so validation (`aip.spec.skill`) stays light:
it needs only pydantic and pyyaml, not the decision-model SDK.
"""

from pathlib import Path
from typing import Any

from aip.spec import models as spec
from aip.spec.skill import LoadedSkill, VERSION_KEY, load_skill


def _split(path: str) -> tuple[str, str]:
    """'assets/sub/x.md' -> ('assets', 'sub/x.md')."""
    folder, _, rest = path.partition("/")
    return folder, rest


def build_procedure(loaded: LoadedSkill, client: Any = None, python: Path | None = None):
    """Turn a LoadedSkill into an executable aip.model.Procedure.

    client: optional TypeSafe client injected into every Decision (tests, connection reuse)
    python: interpreter for Execution scripts; defaults to the server's own
    """
    from aip import model

    aip_id = loaded.skill_dir.resolve().name
    fm = loaded.frontmatter
    meta = model.Meta(name=fm["name"], description=fm.get("description", ""), version=fm.get("metadata", {}).get(VERSION_KEY, spec.FORMAT_VERSION))

    def asset(path: str) -> model.Asset:
        return model.Asset(aip_id, _split(path)[1])

    def inputs(items: list[spec.IOItem]) -> dict[str, model.DataType]:
        return {item.name: model.DataType(item.type.value) for item in items}

    nodes: dict[str, Any] = {}
    for step in loaded.spec.steps:
        match step:
            case spec.DecisionStep():
                from typesafe_sdk import Choice, Noul, Score
                sdk = {"noul": Noul, "choice": Choice, "score": Score}
                nodes[step.name] = model.Decision(
                    name=step.name,
                    inputs=inputs(step.inputs),
                    questions={name: sdk[q.type](**q.model_dump(exclude={"type"}, exclude_none=True)) for name, q in step.questions.items()},
                    thresholds=dict(step.thresholds),
                    client=client,
                )
            case spec.ExecutionStep():
                nodes[step.name] = model.Execution(
                    name=step.name,
                    inputs=inputs(step.inputs),
                    script=model.Script(aip_id, _split(step.script)[1]),
                    assets=[asset(a) for a in step.assets],
                    timeout=step.timeout if step.timeout is not None else 60.0,
                )
            case spec.ClientTaskStep():
                nodes[step.name] = model.ClientTask(
                    name=step.name,
                    inputs=inputs(step.inputs),
                    template=asset(step.template),
                    assets=[asset(a) for a in step.assets],
                    references=[model.Reference(aip_id, _split(r.path)[1], r.description) for r in step.references],
                    include_framing=step.framing,
                )
            case spec.RouterStep():
                nodes[step.name] = model.Router(name=step.name, branch_on=step.branch_on, branches={})
            case spec.EndStep():
                nodes[step.name] = model.EndStep(name=step.name, inputs=inputs(step.inputs))

    # Wire edges by name now that every node exists.
    for step in loaded.spec.steps:
        node = nodes[step.name]
        if isinstance(step, spec.RouterStep):
            node.branches = {value: nodes[target] for value, target in step.branches.items()}
        elif not isinstance(step, spec.EndStep):
            node.inputsTo = nodes[step.inputs_to]

    return model.Procedure(
        meta=meta,
        start=nodes[loaded.spec.start.name],
        loader=model.ResourceLoader(loaded.skill_dir.resolve().parent),
        python=python,
    )


def load_procedure(skill_dir: Path, client: Any = None, python: Path | None = None):
    """Validate a skill folder and build its runtime Procedure in one call."""
    return build_procedure(load_skill(Path(skill_dir)), client=client, python=python)
