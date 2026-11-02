"""The AIP procedure format: pydantic spec models, skill-folder validation, the runtime block
every skill carries, and the bundled authoring skill and example. Needs only pydantic and pyyaml.

The runtime (`Procedure.run`, the client, the server) is the `aip` package, which depends
on this one."""

from aip_spec.models import FORMAT_VERSION, SCHEMA_ID, SPEC_URL, DataType, ProcedureSpec, json_schema, runtime_text
from aip_spec.resources import example_dir, skill_dir
from aip_spec.skill import Issue, LoadedSkill, check_graph, load_skill, parse_skill_md, parse_spec, validate_skill

__all__ = [
    "FORMAT_VERSION", "SCHEMA_ID", "SPEC_URL", "DataType", "ProcedureSpec", "json_schema", "runtime_text",
    "Issue", "LoadedSkill", "check_graph", "load_skill", "parse_skill_md", "parse_spec", "validate_skill",
    "skill_dir", "example_dir",
]
