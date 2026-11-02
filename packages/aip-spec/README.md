# aip-spec

The Agent Instruction Protocol format as a Python package: the pydantic models that define
a procedure, the validator (`aip-spec validate`), the JSON Schema generated from the models
(`aip-spec schema`), the runtime block every skill carries (`aip-spec runtime`), and the
commands that copy the authoring skill and the bundled example out of an install
(`aip-spec skill install`, `aip-spec example`).

This is a workspace member of [zach-blumenfeld/aip](https://github.com/zach-blumenfeld/aip);
the repository's [README](../../README.md) covers installation, the format, and the
walkthrough. The files the wheel bundles live once, at the repository root: the authoring
skill at [`skills/aip-compile/`](../../skills/aip-compile/) and the example at
[`examples/billing-support/`](../../examples/billing-support/).

`aip_spec` imports only pydantic and pyyaml:

```python
from aip_spec import validate_skill, ProcedureSpec, json_schema, runtime_text, example_dir, skill_dir

loaded, issues = validate_skill("./billing-support")   # LoadedSkill | None, list[Issue]
```

Tests run from the repository root with `uv run pytest -q`, which covers both packages.
