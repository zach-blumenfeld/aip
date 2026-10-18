"""The AIP procedure format, as the runtime sees it.

The format itself (pydantic spec models, skill-folder validation, the runtime block every
skill carries) is the `aip-spec` distribution, which also bundles the authoring skill and
the example. This package re-exports it so `from aip.spec import ...` keeps working here,
and adds the one piece that is protocol: `aip.spec.loader`, which builds the executable
`aip.model.Procedure` from a validated skill."""

from aip_spec import (
    FORMAT_VERSION, SCHEMA_ID, SPEC_URL, DataType, Issue, LoadedSkill, ProcedureSpec, check_graph, example_dir,
    json_schema, load_skill, parse_skill_md, parse_spec, runtime_text, skill_dir, validate_skill,
)

__all__ = [
    "FORMAT_VERSION", "SCHEMA_ID", "SPEC_URL", "DataType", "ProcedureSpec", "json_schema", "runtime_text",
    "Issue", "LoadedSkill", "check_graph", "load_skill", "parse_skill_md", "parse_spec", "validate_skill",
    "skill_dir", "example_dir",
]
