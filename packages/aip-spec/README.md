# aip-spec

The Agent Instruction Protocol format as a Python package: the pydantic models that define
a procedure, the validator (`aip-spec validate`), the JSON Schema generated from the models
(`aip-spec schema`), the runtime block every skill carries (`aip-spec runtime`), and the
commands that copy the authoring skill and the bundled example out of an install
(`aip-spec skill install`, `aip-spec example`).

**The format is specified in [`docs/specification.md`](docs/specification.md)**: the skill
folder, the `SKILL.md` frontmatter and body, the procedure's data model and its YAML, the
state rules, the type vocabulary, and everything the validator checks. The pydantic models in
[`src/aip_spec/models.py`](src/aip_spec/models.py) are the source of truth; the JSON Schema is
generated from them.

This is a workspace member of [zach-blumenfeld/aip](https://github.com/zach-blumenfeld/aip);
the repository's [README](../../README.md) covers installation and the walkthrough. The files
the wheel bundles live once, at the repository root: the `aip-compile` skill at
[`skills/aip-compile/`](../../skills/aip-compile/) and the example at
[`examples/billing-support/`](../../examples/billing-support/).

`aip_spec` imports only pydantic and pyyaml:

```python
from aip_spec import validate_skill, ProcedureSpec, json_schema, runtime_text, example_dir, skill_dir

loaded, issues = validate_skill("./billing-support")   # LoadedSkill | None, list[Issue]
```

Tests run from the repository root with `uv run pytest -q`, which covers both packages.
