#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "jsonschema>=4.21",
#     "pyyaml>=6.0",
# ]
# ///
"""Unit tests for scripts/validate_schema.py.

Run with: uv run tests/test_validate_schema.py
"""

import sys
import unittest
from pathlib import Path

# Make scripts/ importable without packaging the project.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import validate_schema as vs


def valid_schema() -> dict:
    """Fresh, minimal valid AIP schema matching the base.schema.json floor.

    `aip.spec` is read from the validator's expected URL helper so the
    fixture stays in sync with the consuming aip skill's version. If
    the helper returns None (running outside the aip skill folder),
    fall back to a literal placeholder.
    """
    spec_url = vs.expected_aip_spec_url() or "https://example.com/spec"
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.com/test.schema.json",
        "title": "Test schema",
        "description": "Schema for unit tests.",
        "aip": {
            "spec": spec_url,
            "version": "0.1",
            "tag": "test",
        },
        "type": "object",
        "additionalProperties": False,
        "required": ["purpose", "trigger_when"],
        "properties": {
            "purpose": {
                "type": "string",
                "description": "What the skill covers.",
            },
            "trigger_when": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "When to use.",
            },
        },
    }


def errors_of(check_fn, schema):
    return list(check_fn(schema, "test"))


class TestRequiredMetadata(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(errors_of(vs.check_required_metadata, valid_schema()), [])

    def test_missing_schema(self):
        schema = valid_schema()
        del schema["$schema"]
        errors = errors_of(vs.check_required_metadata, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "missing_required_metadata")

    def test_missing_id(self):
        schema = valid_schema()
        del schema["$id"]
        errors = errors_of(vs.check_required_metadata, schema)
        self.assertEqual(len(errors), 1)

    def test_missing_title(self):
        schema = valid_schema()
        del schema["title"]
        errors = errors_of(vs.check_required_metadata, schema)
        self.assertEqual(len(errors), 1)

    def test_missing_description(self):
        schema = valid_schema()
        del schema["description"]
        errors = errors_of(vs.check_required_metadata, schema)
        self.assertEqual(len(errors), 1)

    def test_empty_string(self):
        schema = valid_schema()
        schema["title"] = ""
        errors = errors_of(vs.check_required_metadata, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_required_metadata")

    def test_whitespace_string(self):
        schema = valid_schema()
        schema["title"] = "   "
        errors = errors_of(vs.check_required_metadata, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_required_metadata")


class TestIdForm(unittest.TestCase):
    def test_https_uri(self):
        self.assertEqual(errors_of(vs.check_id_form, valid_schema()), [])

    def test_urn(self):
        schema = valid_schema()
        schema["$id"] = "urn:uuid:550e8400-e29b-41d4-a716-446655440000"
        self.assertEqual(errors_of(vs.check_id_form, schema), [])

    def test_no_colon(self):
        schema = valid_schema()
        schema["$id"] = "just-a-name"
        errors = errors_of(vs.check_id_form, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_id_form")


class TestAipNamespace(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(errors_of(vs.check_aip_namespace, valid_schema()), [])

    def test_missing_aip(self):
        schema = valid_schema()
        del schema["aip"]
        errors = errors_of(vs.check_aip_namespace, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "missing_aip_namespace")

    def test_aip_not_object(self):
        schema = valid_schema()
        schema["aip"] = "not an object"
        errors = errors_of(vs.check_aip_namespace, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_aip_namespace")

    def test_missing_version(self):
        schema = valid_schema()
        del schema["aip"]["version"]
        errors = errors_of(vs.check_aip_namespace, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "missing_aip_field")

    def test_version_empty(self):
        schema = valid_schema()
        schema["aip"]["version"] = ""
        errors = errors_of(vs.check_aip_namespace, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_aip_field")

    def test_version_not_string(self):
        schema = valid_schema()
        schema["aip"]["version"] = 0.1
        errors = errors_of(vs.check_aip_namespace, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_aip_field")

    def test_tag_optional(self):
        schema = valid_schema()
        del schema["aip"]["tag"]
        self.assertEqual(errors_of(vs.check_aip_namespace, schema), [])

    def test_tag_not_string(self):
        schema = valid_schema()
        schema["aip"]["tag"] = 123
        errors = errors_of(vs.check_aip_namespace, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_aip_field")


class TestAipSpec(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(errors_of(vs.check_aip_spec, valid_schema()), [])

    def test_missing_spec(self):
        schema = valid_schema()
        del schema["aip"]["spec"]
        errors = errors_of(vs.check_aip_spec, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "missing_aip_field")

    def test_spec_not_string(self):
        schema = valid_schema()
        schema["aip"]["spec"] = 123
        errors = errors_of(vs.check_aip_spec, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_aip_field")

    def test_spec_not_uri(self):
        schema = valid_schema()
        schema["aip"]["spec"] = "no-colon-here"
        errors = errors_of(vs.check_aip_spec, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_aip_field")

    def test_spec_mismatch(self):
        """A different-version URL must trigger aip_spec_mismatch."""
        # Only runs if the helper can find SKILL.md; otherwise the
        # URL-match check is skipped and this assertion would not hold.
        if vs.expected_aip_spec_url() is None:
            self.skipTest("SKILL.md not discoverable from validator")
        schema = valid_schema()
        schema["aip"]["spec"] = "https://github.com/zach-blumenfeld/aip/tree/v999.0"
        errors = errors_of(vs.check_aip_spec, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "aip_spec_mismatch")


class TestExpectedAipSpecUrl(unittest.TestCase):
    def test_reads_skill_md_version(self):
        url = vs.expected_aip_spec_url()
        # The aip skill's SKILL.md declares metadata.aip.version: "0.3a0"
        # at the time these tests were written. The assertion focuses on
        # the URL shape rather than the literal version to avoid coupling
        # the test to a moving version.
        self.assertIsNotNone(url)
        self.assertTrue(url.startswith(vs.AIP_SPEC_URL_PREFIX))


class TestBaseFloor(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(errors_of(vs.check_base_floor, valid_schema()), [])

    def test_missing_purpose_property(self):
        schema = valid_schema()
        del schema["properties"]["purpose"]
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("missing_base_property", kinds)

    def test_purpose_wrong_type(self):
        schema = valid_schema()
        schema["properties"]["purpose"]["type"] = "array"
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("invalid_base_property", kinds)

    def test_purpose_not_in_required(self):
        schema = valid_schema()
        schema["required"] = ["trigger_when"]
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("missing_base_required", kinds)

    def test_missing_trigger_when_property(self):
        schema = valid_schema()
        del schema["properties"]["trigger_when"]
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("missing_base_property", kinds)

    def test_trigger_when_wrong_type(self):
        schema = valid_schema()
        schema["properties"]["trigger_when"]["type"] = "string"
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("invalid_base_property", kinds)

    def test_trigger_when_items_wrong(self):
        schema = valid_schema()
        schema["properties"]["trigger_when"]["items"] = {"type": "number"}
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("invalid_base_property", kinds)

    def test_trigger_when_min_items_zero(self):
        schema = valid_schema()
        schema["properties"]["trigger_when"]["minItems"] = 0
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("invalid_base_property", kinds)

    def test_trigger_when_min_items_missing(self):
        schema = valid_schema()
        del schema["properties"]["trigger_when"]["minItems"]
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("invalid_base_property", kinds)

    def test_trigger_when_not_in_required(self):
        schema = valid_schema()
        schema["required"] = ["purpose"]
        kinds = [e.kind for e in errors_of(vs.check_base_floor, schema)]
        self.assertIn("missing_base_required", kinds)


class TestStrictCore(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(errors_of(vs.check_strict_core, valid_schema()), [])

    def test_missing_additional_properties(self):
        schema = valid_schema()
        del schema["additionalProperties"]
        errors = errors_of(vs.check_strict_core, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "missing_additional_properties")

    def test_additional_properties_true(self):
        schema = valid_schema()
        schema["additionalProperties"] = True
        errors = errors_of(vs.check_strict_core, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_additional_properties")

    def test_additional_properties_schema(self):
        schema = valid_schema()
        schema["additionalProperties"] = {"type": "string"}
        errors = errors_of(vs.check_strict_core, schema)
        # Root has additionalProperties as a dict — invalid.
        kinds = [e.kind for e in errors]
        self.assertIn("invalid_additional_properties", kinds)

    def test_nested_object_missing_additional_properties(self):
        schema = valid_schema()
        schema["$defs"] = {
            "Sub": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
            }
        }
        errors = errors_of(vs.check_strict_core, schema)
        self.assertTrue(any("Sub" in (e.location or "") for e in errors))


class TestDefsNaming(unittest.TestCase):
    def test_valid(self):
        schema = valid_schema()
        schema["$defs"] = {"GoodName": {"type": "object", "additionalProperties": False}}
        self.assertEqual(errors_of(vs.check_defs_naming, schema), [])

    def test_starts_with_digit(self):
        schema = valid_schema()
        schema["$defs"] = {"123bad": {"type": "object", "additionalProperties": False}}
        errors = errors_of(vs.check_defs_naming, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_def_name")

    def test_special_chars(self):
        schema = valid_schema()
        schema["$defs"] = {"bad-name": {"type": "object", "additionalProperties": False}}
        errors = errors_of(vs.check_defs_naming, schema)
        self.assertEqual(len(errors), 1)


class TestKeywordCollisions(unittest.TestCase):
    def test_no_collision(self):
        self.assertEqual(errors_of(vs.check_json_schema_keyword_collisions, valid_schema()), [])

    def test_collision_in_properties(self):
        schema = valid_schema()
        schema["properties"]["enum"] = {"type": "string"}
        warnings = errors_of(vs.check_json_schema_keyword_collisions, schema)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].severity, "warning")
        self.assertEqual(warnings[0].kind, "json_schema_keyword_collision")

    def test_collision_in_defs(self):
        schema = valid_schema()
        schema["$defs"] = {
            "Sub": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"format": {"type": "string"}},
            }
        }
        warnings = errors_of(vs.check_json_schema_keyword_collisions, schema)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].severity, "warning")


class TestSchemaValidity(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(errors_of(vs.check_schema_validity, valid_schema()), [])

    def test_broken_schema(self):
        schema = valid_schema()
        schema["properties"]["purpose"]["type"] = 12345  # must be string or array
        errors = errors_of(vs.check_schema_validity, schema)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].kind, "invalid_schema")


class TestEndToEnd(unittest.TestCase):
    """End-to-end tests invoke validate_schema_file, which emits JSON Lines
    to stderr. Suppress that during each test so unittest's own output
    (also stderr) stays readable."""

    def _run_quietly(self, fn):
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            return fn()

    def test_base_schema_passes(self):
        """The actual assets/base.schema.json must validate clean."""
        base_path = Path(__file__).parent.parent / "assets" / "base.schema.json"
        err_count, _warn_count, _title = self._run_quietly(
            lambda: vs.validate_schema_file(base_path)
        )
        self.assertEqual(err_count, 0, f"base.schema.json failed validation with {err_count} errors")

    def test_completely_broken_schema_fails(self):
        """A schema missing everything should fail multiple checks."""
        import json
        import tempfile
        broken = {"type": "object"}  # missing $schema, $id, title, description, aip, etc.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".schema.json", delete=False) as f:
            json.dump(broken, f)
            path = Path(f.name)
        try:
            err_count, _, _ = self._run_quietly(
                lambda: vs.validate_schema_file(path)
            )
            self.assertGreater(err_count, 0)
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
