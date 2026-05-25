#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jsonschema>=4.21",
#     "pyyaml>=6.0",
# ]
# ///
"""Unit tests for scripts/validate.py.

Run with: uv run tests/test_validate.py
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make scripts/ importable without packaging the project.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import validate as v  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def valid_frontmatter() -> dict:
    """Fresh, minimal valid frontmatter dict.

    `metadata.aip.spec` uses the validator's expected URL helper so the
    fixture stays in sync with the consuming aip skill's version.
    """
    spec_url = v._vs.expected_aip_spec_url() or "https://example.com/spec"
    return {
        "name": "test-skill",
        "description": "A test skill for validation.",
        "metadata": {
            "aip": {
                "spec": spec_url,
                "schemaId": "https://example.com/runbook.schema.json",
            },
        },
    }


def valid_schema_json() -> dict:
    """Fresh, minimal valid AIP schema matching the test skill's schemaId."""
    spec_url = v._vs.expected_aip_spec_url() or "https://example.com/spec"
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.com/runbook.schema.json",
        "title": "Test schema",
        "description": "Test schema for unit tests.",
        "aip": {"spec": spec_url, "version": "0.1"},
        "type": "object",
        "additionalProperties": False,
        "required": ["purpose", "trigger_when"],
        "properties": {
            "purpose": {
                "type": "string",
                "description": "Purpose.",
            },
            "trigger_when": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Triggers.",
            },
        },
    }


def valid_skill_md_content() -> str:
    """Full valid SKILL.md file content (frontmatter + body)."""
    spec_url = v._vs.expected_aip_spec_url() or "https://example.com/spec"
    return (
        "---\n"
        "name: test-skill\n"
        "description: A test skill for validation.\n"
        "metadata:\n"
        "  aip:\n"
        f"    spec: {spec_url}\n"
        "    schemaId: https://example.com/runbook.schema.json\n"
        "---\n"
        "\n"
        "```yaml\n"
        "purpose: Test skill purpose statement.\n"
        "trigger_when:\n"
        "  - A trigger condition.\n"
        "```\n"
    )


def write_skill(skill_dir: Path):
    """Write a full valid AIP skill folder at skill_dir."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(valid_skill_md_content())
    source = skill_dir / "source"
    source.mkdir(exist_ok=True)
    (source / "runbook.schema.json").write_text(json.dumps(valid_schema_json()))


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestParseSkillMd(unittest.TestCase):
    def test_valid(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            p.write_text(valid_skill_md_content())
            fm, body, errors = v.parse_skill_md(p)
            self.assertEqual(errors, [])
            self.assertEqual(fm["name"], "test-skill")
            self.assertIn("```yaml", body)

    def test_missing_file(self):
        _, _, errors = v.parse_skill_md(Path("/nonexistent/SKILL.md"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "missing_skill_md")

    def test_missing_frontmatter(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            p.write_text("no frontmatter here")
            _, _, errors = v.parse_skill_md(p)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].kind, "missing_frontmatter")

    def test_invalid_frontmatter_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            p.write_text("---\nname: [invalid yaml\n---\n\n```yaml\n```\n")
            _, _, errors = v.parse_skill_md(p)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].kind, "invalid_frontmatter")

    def test_non_dict_frontmatter(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            p.write_text("---\n- list_item\n---\n\n```yaml\n```\n")
            _, _, errors = v.parse_skill_md(p)
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].kind, "invalid_frontmatter")


class TestExtractBodyYaml(unittest.TestCase):
    def test_valid_yaml_tag(self):
        body = "```yaml\nkey: value\n```\n"
        data, errors = v.extract_body_yaml(body, Path("/test/SKILL.md"))
        self.assertEqual(errors, [])
        self.assertEqual(data, {"key": "value"})

    def test_valid_yml_tag(self):
        body = "```yml\nkey: value\n```\n"
        data, errors = v.extract_body_yaml(body, Path("/test/SKILL.md"))
        self.assertEqual(errors, [])
        self.assertEqual(data, {"key": "value"})

    def test_empty_body(self):
        _, errors = v.extract_body_yaml("", Path("/test/SKILL.md"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "empty_body")

    def test_whitespace_body(self):
        _, errors = v.extract_body_yaml("   \n\n  ", Path("/test/SKILL.md"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "empty_body")

    def test_no_fence(self):
        body = "just some prose, not a code block"
        _, errors = v.extract_body_yaml(body, Path("/test/SKILL.md"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_body_format")

    def test_wrong_language_tag(self):
        body = "```python\nkey = value\n```\n"
        _, errors = v.extract_body_yaml(body, Path("/test/SKILL.md"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_body_format")

    def test_invalid_yaml_inside(self):
        body = "```yaml\nkey: [unclosed\n```\n"
        _, errors = v.extract_body_yaml(body, Path("/test/SKILL.md"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_body_yaml")


class TestFindSchema(unittest.TestCase):
    @staticmethod
    def _write(source: Path, name: str, schema: dict):
        (source / name).write_text(json.dumps(schema))

    def test_valid(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            source.mkdir()
            schema = valid_schema_json()
            self._write(source, "runbook.schema.json", schema)
            result, path, errors = v.find_schema(source, schema["$id"])
            self.assertEqual(errors, [])
            self.assertEqual(result, schema)
            self.assertEqual(path.name, "runbook.schema.json")

    def test_missing_source_dir(self):
        _, _, errors = v.find_schema(Path("/nonexistent-dir"), "x")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "missing_source_dir")

    def test_no_schema_files(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            source.mkdir()
            _, _, errors = v.find_schema(source, "x")
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].kind, "missing_schema_file")

    def test_id_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            source.mkdir()
            self._write(source, "runbook.schema.json", valid_schema_json())
            _, _, errors = v.find_schema(source, "https://different.com/x")
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].kind, "schema_id_mismatch")

    def test_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            source.mkdir()
            schema = valid_schema_json()
            self._write(source, "a.schema.json", schema)
            self._write(source, "b.schema.json", schema)
            _, _, errors = v.find_schema(source, schema["$id"])
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].kind, "duplicate_schema_id")

    def test_ignores_malformed_schemas(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            source.mkdir()
            (source / "bad.schema.json").write_text("not valid json")
            self._write(source, "runbook.schema.json", valid_schema_json())
            result, _, errors = v.find_schema(
                source, valid_schema_json()["$id"]
            )
            self.assertEqual(errors, [])
            self.assertIsNotNone(result)


class TestCheckFrontmatterFields(unittest.TestCase):
    """Covers the big check_frontmatter_fields function branch-by-branch."""

    def _check(self, frontmatter: dict, folder_name: str = "test-skill"):
        skill_path = Path(tempfile.gettempdir()) / folder_name
        skill_md_path = skill_path / "SKILL.md"
        return v.check_frontmatter_fields(frontmatter, skill_md_path, skill_path)

    def _kinds(self, errors):
        return [e.kind for e in errors]

    # --- valid baseline
    def test_valid(self):
        sid, errors = self._check(valid_frontmatter())
        self.assertEqual(errors, [])
        self.assertEqual(sid, "https://example.com/runbook.schema.json")

    # --- name field
    def test_missing_name(self):
        fm = valid_frontmatter()
        del fm["name"]
        _, errors = self._check(fm)
        self.assertIn("missing_required_frontmatter", self._kinds(errors))

    def test_name_not_string(self):
        fm = valid_frontmatter()
        fm["name"] = 123
        _, errors = self._check(fm)
        self.assertIn("invalid_name", self._kinds(errors))

    def test_name_too_long(self):
        fm = valid_frontmatter()
        long_name = "a" * 65
        fm["name"] = long_name
        _, errors = self._check(fm, folder_name=long_name)
        self.assertIn("invalid_name", self._kinds(errors))

    def test_name_uppercase_rejected(self):
        fm = valid_frontmatter()
        fm["name"] = "Test-Skill"
        _, errors = self._check(fm, folder_name="Test-Skill")
        self.assertIn("invalid_name", self._kinds(errors))

    def test_name_leading_hyphen_rejected(self):
        fm = valid_frontmatter()
        fm["name"] = "-leading-hyphen"
        _, errors = self._check(fm, folder_name="-leading-hyphen")
        self.assertIn("invalid_name", self._kinds(errors))

    def test_name_trailing_hyphen_rejected(self):
        fm = valid_frontmatter()
        fm["name"] = "trailing-hyphen-"
        _, errors = self._check(fm, folder_name="trailing-hyphen-")
        self.assertIn("invalid_name", self._kinds(errors))

    def test_name_consecutive_hyphens_rejected(self):
        fm = valid_frontmatter()
        fm["name"] = "consecutive--hyphens"
        _, errors = self._check(fm, folder_name="consecutive--hyphens")
        self.assertIn("invalid_name", self._kinds(errors))

    def test_name_special_chars_rejected(self):
        fm = valid_frontmatter()
        fm["name"] = "has_underscore"
        _, errors = self._check(fm, folder_name="has_underscore")
        self.assertIn("invalid_name", self._kinds(errors))

    def test_name_mismatch_folder(self):
        fm = valid_frontmatter()
        _, errors = self._check(fm, folder_name="different-folder")
        self.assertIn("name_mismatch", self._kinds(errors))

    # --- description field
    def test_missing_description(self):
        fm = valid_frontmatter()
        del fm["description"]
        _, errors = self._check(fm)
        self.assertIn("missing_required_frontmatter", self._kinds(errors))

    def test_description_not_string(self):
        fm = valid_frontmatter()
        fm["description"] = 123
        _, errors = self._check(fm)
        self.assertIn("invalid_description", self._kinds(errors))

    def test_description_whitespace_only(self):
        fm = valid_frontmatter()
        fm["description"] = "   \t\n  "
        _, errors = self._check(fm)
        self.assertIn("invalid_description", self._kinds(errors))

    def test_description_too_long(self):
        fm = valid_frontmatter()
        fm["description"] = "a" * 1025
        _, errors = self._check(fm)
        self.assertIn("invalid_description", self._kinds(errors))

    # --- compatibility (optional)
    def test_compatibility_absent_ok(self):
        fm = valid_frontmatter()
        _, errors = self._check(fm)
        self.assertNotIn("invalid_compatibility", self._kinds(errors))

    def test_compatibility_valid(self):
        fm = valid_frontmatter()
        fm["compatibility"] = "Designed for Claude Code"
        _, errors = self._check(fm)
        self.assertNotIn("invalid_compatibility", self._kinds(errors))

    def test_compatibility_not_string(self):
        fm = valid_frontmatter()
        fm["compatibility"] = [1, 2, 3]
        _, errors = self._check(fm)
        self.assertIn("invalid_compatibility", self._kinds(errors))

    def test_compatibility_too_long(self):
        fm = valid_frontmatter()
        fm["compatibility"] = "a" * 501
        _, errors = self._check(fm)
        self.assertIn("invalid_compatibility", self._kinds(errors))

    # --- allowed-tools (optional)
    def test_allowed_tools_absent_ok(self):
        fm = valid_frontmatter()
        _, errors = self._check(fm)
        self.assertNotIn("invalid_allowed_tools", self._kinds(errors))

    def test_allowed_tools_valid_string(self):
        fm = valid_frontmatter()
        fm["allowed-tools"] = "Bash(git:*) Read"
        _, errors = self._check(fm)
        self.assertNotIn("invalid_allowed_tools", self._kinds(errors))

    def test_allowed_tools_not_string(self):
        fm = valid_frontmatter()
        fm["allowed-tools"] = ["Bash", "Read"]
        _, errors = self._check(fm)
        self.assertIn("invalid_allowed_tools", self._kinds(errors))

    # --- license (optional)
    def test_license_absent_ok(self):
        fm = valid_frontmatter()
        _, errors = self._check(fm)
        self.assertNotIn("invalid_license", self._kinds(errors))

    def test_license_valid_string(self):
        fm = valid_frontmatter()
        fm["license"] = "Apache-2.0"
        _, errors = self._check(fm)
        self.assertNotIn("invalid_license", self._kinds(errors))

    def test_license_not_string(self):
        fm = valid_frontmatter()
        fm["license"] = {"name": "MIT"}
        _, errors = self._check(fm)
        self.assertIn("invalid_license", self._kinds(errors))

    # --- metadata
    def test_metadata_not_object(self):
        fm = valid_frontmatter()
        fm["metadata"] = "not-an-object"
        _, errors = self._check(fm)
        self.assertIn("invalid_metadata", self._kinds(errors))

    def test_metadata_non_aip_string_ok(self):
        fm = valid_frontmatter()
        fm["metadata"]["author"] = "example-org"
        _, errors = self._check(fm)
        self.assertEqual(errors, [])

    def test_metadata_non_aip_non_string_rejected(self):
        fm = valid_frontmatter()
        fm["metadata"]["version"] = 1.0  # number, not string
        _, errors = self._check(fm)
        self.assertIn("invalid_metadata", self._kinds(errors))

    def test_metadata_aip_not_object(self):
        fm = valid_frontmatter()
        fm["metadata"]["aip"] = "not-an-object"
        sid, errors = self._check(fm)
        self.assertIn("invalid_aip_metadata", self._kinds(errors))
        self.assertIsNone(sid)

    # --- aip.spec
    def test_missing_aip_spec(self):
        fm = valid_frontmatter()
        del fm["metadata"]["aip"]["spec"]
        _, errors = self._check(fm)
        self.assertIn("missing_aip_spec", self._kinds(errors))

    def test_aip_spec_not_string(self):
        fm = valid_frontmatter()
        fm["metadata"]["aip"]["spec"] = 123
        _, errors = self._check(fm)
        self.assertIn("invalid_aip_spec", self._kinds(errors))

    def test_aip_spec_not_uri(self):
        fm = valid_frontmatter()
        fm["metadata"]["aip"]["spec"] = "no-colon-here"
        _, errors = self._check(fm)
        self.assertIn("invalid_aip_spec", self._kinds(errors))

    def test_aip_spec_urn_ok(self):
        """A URN-form spec passes the URI form check, but will fail the
        URL-match check if the helper can find SKILL.md. Verify only the
        URI-form check here."""
        fm = valid_frontmatter()
        fm["metadata"]["aip"]["spec"] = "urn:something:spec"
        _, errors = self._check(fm)
        self.assertNotIn("invalid_aip_spec", self._kinds(errors))

    def test_aip_spec_mismatch(self):
        """A different-version URL must trigger aip_spec_mismatch."""
        if v._vs.expected_aip_spec_url() is None:
            self.skipTest("SKILL.md not discoverable from validator")
        fm = valid_frontmatter()
        fm["metadata"]["aip"]["spec"] = "https://github.com/zach-blumenfeld/aip/tree/v999.0"
        _, errors = self._check(fm)
        self.assertIn("aip_spec_mismatch", self._kinds(errors))

    # --- aip.schemaId
    def test_missing_aip_schema_id(self):
        fm = valid_frontmatter()
        del fm["metadata"]["aip"]["schemaId"]
        sid, errors = self._check(fm)
        self.assertIn("missing_aip_schema_id", self._kinds(errors))
        self.assertIsNone(sid)

    def test_aip_schema_id_not_string(self):
        fm = valid_frontmatter()
        fm["metadata"]["aip"]["schemaId"] = 123
        sid, errors = self._check(fm)
        self.assertIn("invalid_aip_schema_id", self._kinds(errors))
        self.assertIsNone(sid)


class TestCheckBundledSchema(unittest.TestCase):
    """Delegates to validate_schema; verify the wiring works."""

    def test_valid_schema_passes(self):
        errors = v.check_bundled_schema(
            valid_schema_json(), Path("/test/source/x.schema.json")
        )
        # Only warnings are allowed for a valid schema; no errors.
        error_kinds = [e.kind for e in errors if e.severity == "error"]
        self.assertEqual(error_kinds, [])

    def test_broken_schema_surfaces_errors(self):
        schema = valid_schema_json()
        del schema["$id"]  # required root metadata
        errors = v.check_bundled_schema(
            schema, Path("/test/source/x.schema.json")
        )
        error_kinds = [e.kind for e in errors if e.severity == "error"]
        self.assertIn("missing_required_metadata", error_kinds)


class TestValidateBodyAgainstSchema(unittest.TestCase):
    def test_valid_body(self):
        body = {"purpose": "Test", "trigger_when": ["one"]}
        errors = v.validate_body_against_schema(
            body, valid_schema_json(),
            Path("/test/SKILL.md"), Path("/test/source/x.schema.json"),
        )
        self.assertEqual(errors, [])

    def test_missing_required_field(self):
        body = {"purpose": "Test"}  # missing trigger_when
        errors = v.validate_body_against_schema(
            body, valid_schema_json(),
            Path("/test/SKILL.md"), Path("/test/source/x.schema.json"),
        )
        self.assertTrue(any(e.kind == "schema_violation" for e in errors))

    def test_wrong_type(self):
        body = {"purpose": 42, "trigger_when": ["one"]}
        errors = v.validate_body_against_schema(
            body, valid_schema_json(),
            Path("/test/SKILL.md"), Path("/test/source/x.schema.json"),
        )
        self.assertTrue(any(e.kind == "schema_violation" for e in errors))

    def test_unknown_extra_field_rejected(self):
        body = {
            "purpose": "Test", "trigger_when": ["one"],
            "schemaId": "should-not-be-here",
        }
        errors = v.validate_body_against_schema(
            body, valid_schema_json(),
            Path("/test/SKILL.md"), Path("/test/source/x.schema.json"),
        )
        self.assertTrue(any(e.kind == "schema_violation" for e in errors))


class TestEndToEnd(unittest.TestCase):
    """End-to-end tests run validate_skill, which emits JSON Lines to stderr."""

    @staticmethod
    def _run_quietly(fn):
        with contextlib.redirect_stderr(io.StringIO()):
            return fn()

    def test_valid_skill_passes(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "test-skill"
            write_skill(skill)
            err, _warn, _fm = self._run_quietly(lambda: v.validate_skill(skill))
            self.assertEqual(err, 0)

    def test_missing_path_fails(self):
        err, _, _ = self._run_quietly(
            lambda: v.validate_skill(Path("/nonexistent-skill-path"))
        )
        self.assertGreater(err, 0)

    def test_not_a_directory_fails(self):
        with tempfile.NamedTemporaryFile(suffix="-skill") as tf:
            err, _, _ = self._run_quietly(
                lambda: v.validate_skill(Path(tf.name))
            )
            self.assertGreater(err, 0)

    def test_missing_skill_md_fails(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "test-skill"
            skill.mkdir()
            err, _, _ = self._run_quietly(lambda: v.validate_skill(skill))
            self.assertGreater(err, 0)

    def test_missing_source_dir_fails(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "test-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(valid_skill_md_content())
            err, _, _ = self._run_quietly(lambda: v.validate_skill(skill))
            self.assertGreater(err, 0)

    def test_missing_bundled_schema_fails(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "test-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(valid_skill_md_content())
            (skill / "source").mkdir()
            err, _, _ = self._run_quietly(lambda: v.validate_skill(skill))
            self.assertGreater(err, 0)

    def test_schema_id_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "test-skill"
            write_skill(skill)
            # Rewrite the bundled schema with a different $id.
            bad = valid_schema_json()
            bad["$id"] = "https://other.com/different.schema.json"
            (skill / "source" / "runbook.schema.json").write_text(json.dumps(bad))
            err, _, _ = self._run_quietly(lambda: v.validate_skill(skill))
            self.assertGreater(err, 0)

    def test_body_violates_schema_fails(self):
        with tempfile.TemporaryDirectory() as td:
            skill = Path(td) / "test-skill"
            write_skill(skill)
            content = valid_skill_md_content().replace(
                "purpose: Test skill purpose statement.\n",
                "",  # remove a required field
            )
            (skill / "SKILL.md").write_text(content)
            err, _, _ = self._run_quietly(lambda: v.validate_skill(skill))
            self.assertGreater(err, 0)

    def test_name_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            # Folder name doesn't match the `name` in frontmatter.
            skill = Path(td) / "different-folder"
            write_skill(skill)
            err, _, _ = self._run_quietly(lambda: v.validate_skill(skill))
            self.assertGreater(err, 0)


if __name__ == "__main__":
    unittest.main()
