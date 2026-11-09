"""The graph (spec 3), the bundle id, the bundle file (compile, write, read with verification,
export) and the `compile` and `export` commands. The tests that open a Relate file skip when
Relate is not installed and say how to install it; the graph and the id need nothing."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from aip_spec import (
    LANGUAGE_VERSION, BundleError, FileEntry, bundle_id, compile_folder, compile_source, example_dir, example_names,
    export_bundle, read_bundle, write_bundle,
)
from aip_spec import relate
from aip_spec.cli import main
from aip_spec.graph import PROCEDURE_ID

needs_relate = unittest.skipUnless(relate.available(), relate.INSTALL_HINT)
PREFIX = 'Procedure p "x"\n'


def compiled(name: str):
    bundle, diagnostics = compile_folder(example_dir(name))
    assert bundle is not None, [str(d) for d in diagnostics]
    return bundle


def props(graph, id: str) -> dict:
    node = graph.node(id)
    assert node is not None, f"no node {id}; have {[n.id for n in graph.nodes]}"
    return node.properties


def one(graph, type: str, start: str | None = None, end: str | None = None) -> dict:
    found = graph.edges_of(type, start, end)
    assert len(found) == 1, (type, start, end, [e.to_dict() for e in found])
    return found[0].properties


def bare(properties: dict) -> dict:
    """The properties without the source span."""
    return {k: v for k, v in properties.items() if k not in ("line", "column", "end_line", "end_column")}


class TheGraph(unittest.TestCase):
    def test_every_node_is_addressable_and_every_edge_joins_two_nodes(self):
        for name in example_names():
            with self.subTest(name):
                bundle = compiled(name)
                ids = [n.id for n in bundle.graph.nodes]
                self.assertEqual(len(ids), len(set(ids)), "ids are unique")
                for n in bundle.graph.nodes:
                    self.assertEqual((n.properties["id"], n.properties["bundle_id"]), (n.id, bundle.id))
                    self.assertNotIn(None, n.properties.values(), "null properties are left out")
                for e in bundle.graph.edges:
                    self.assertIn(e.start, ids, e.to_dict())
                    self.assertIn(e.end, ids, e.to_dict())
                [procedure] = bundle.graph.with_label("Procedure")
                self.assertEqual((procedure.id, procedure.properties["name"], procedure.properties["bundle_id"]),
                                 (PROCEDURE_ID, bundle.name, bundle.id))
                self.assertEqual(procedure.properties["source"], bundle.source)
                self.assertEqual(procedure.properties["language_version"], LANGUAGE_VERSION)

    def test_billing_support(self):
        g = compiled("billing-support").graph
        self.assertEqual([n.id for n in g.with_label("Step")],
                         ["step:start", "step:triage", "step:by_tone", "step:escalate", "step:reply", "step:end"])
        self.assertEqual(g.node("step:reply").labels, ("Step", "Task_Agent"))
        one(g, "STARTS_AT", PROCEDURE_ID, "step:start")
        one(g, "ENDS_AT", PROCEDURE_ID, "step:end")
        self.assertEqual(props(g, "step:triage") | {"line": 0, "column": 0, "end_line": 0, "end_column": 0},
                         {"id": "step:triage", "bundle_id": props(g, PROCEDURE_ID)["bundle_id"], "name": "triage", "kind": "Decide",
                          "description": "Classify whether the message is about billing and how upset the customer is.",
                          "agent_fallback": True, "history": False, "produces": "triage_decision",
                          "line": 0, "column": 0, "end_line": 0, "end_column": 0})
        self.assertEqual(props(g, "step:triage")["line"], 33)
        q = props(g, "question:triage.tone")
        self.assertEqual((q["type"], q["labels"], q["order"], q["criteria_labels"]), ("choice", ["angry", "calm"], 1, ["angry", "calm"]))
        self.assertTrue(q["instruction"].startswith("How upset is the customer?"), "a named string is resolved")
        self.assertEqual(one(g, "ASKS", "step:triage", "question:triage.tone"), {"order": 1})
        self.assertEqual(props(g, "step:by_tone")["check_below"], 0.6)
        self.assertEqual(one(g, "BELOW", "step:by_tone", "step:escalate")["below"], 0.6)
        self.assertEqual(one(g, "BRANCH", "step:by_tone", "step:escalate")["value"], "angry")
        self.assertEqual(one(g, "BRANCH", "step:by_tone", "step:reply")["value"], "calm")
        self.assertEqual(one(g, "READS", "step:by_tone", "key:triage_decision")["field"], "tone")
        self.assertEqual({k.id: k.properties.get("type") for k in g.with_label("Key")},
                         {"key:message": "string", "key:triage_decision": "decision", "key:ticket_id": "integer",
                          "key:queue": "string", "key:reply": "string"})
        self.assertEqual(props(g, "key:ticket_id")["description"], "The tier-2 ticket opened for the message.")
        self.assertEqual([e.end for e in g.edges_of("PRODUCES", "step:escalate")], ["key:ticket_id", "key:queue"])
        self.assertEqual(props(g, "step:escalate")["script"], "scripts/escalate.py")
        one(g, "RUNS", "step:escalate", "file:scripts/escalate.py")
        self.assertEqual(bare(one(g, "USES", "step:escalate", "file:assets/config.json")), {}, "an asset has no description")
        self.assertTrue(one(g, "USES", "step:reply", "file:references/help.md")["description"].startswith("Escalation contacts"))
        one(g, "PROMPTED_BY", "step:reply", "file:assets/reply.md")
        self.assertEqual(props(g, "step:reply")["prompt"], "assets/reply.md")
        self.assertEqual(len(g.with_label("File")), 5)
        f = props(g, "file:assets/config.json")
        self.assertEqual((f["path"], f["size"], f["sha256"]), ("assets/config.json", len(f["text"].encode()),
                                                             hashlib.sha256(f["text"].encode()).hexdigest()))
        self.assertEqual(len(g.edges_of("HAS_FILE", PROCEDURE_ID)), 5)
        p = props(g, PROCEDURE_ID)
        self.assertEqual((p["requires_interpreter"], p["requires_version"], len(p["use_when"]), len(p["avoid"])), ("python", "3.10", 2, 2))
        self.assertEqual([e.end for e in g.edges_of("NEXT", "step:start")], ["step:triage"])
        self.assertEqual(one(g, "NEXT", "step:start", "step:triage")["line"], 30, "a flow edge carries the clause's span")

    def test_ticket_triage_loops(self):
        g = compiled("ticket-triage").graph
        loop = props(g, "loop:each_ticket")
        self.assertEqual(g.node("loop:each_ticket").labels, ("Loop", "For"))
        self.assertEqual((loop["kind"], loop["mode"], loop["item"], loop["at_most"], loop["collect_key"], loop["collect_into"]),
                         ("For", "Over", "ticket", 50, "reply", "replies"))
        one(g, "OVER", "loop:each_ticket", "key:tickets")
        one(g, "BINDS", "loop:each_ticket", "key:ticket")
        one(g, "COLLECTS", "loop:each_ticket", "key:reply")
        one(g, "PRODUCES", "loop:each_ticket", "key:replies")
        self.assertEqual(props(g, "key:replies")["type"], "list")
        self.assertEqual([(e.end, e.properties["order"]) for e in g.edges_of("CONTAINS", "loop:each_ticket")],
                         [("step:classify", 0), ("step:by_tone", 1), ("step:draft", 2), ("step:escalate", 3), ("step:check", 4),
                          ("loop:revise", 5)])
        one(g, "ENTERS", "loop:each_ticket", "step:classify")
        one(g, "CONTINUES", "step:escalate", "loop:each_ticket")
        one(g, "NEXT", "loop:each_ticket", "step:summarize")
        revise = props(g, "loop:revise")
        self.assertEqual((revise["kind"], revise["mode"], revise["at_most"], revise["at_cap"], revise["until_answer"]),
                         ("Loop", "Until", 3, "Else_Fail", "passed"))
        self.assertEqual(bare(one(g, "WATCHES", "loop:revise", "key:passed")), {}, "a bare true_or_false condition: no field, no comparison")
        one(g, "CONTINUES", "loop:revise", "loop:each_ticket")
        one(g, "AGAIN", "step:fix", "step:check")
        self.assertEqual(one(g, "BRANCH", "step:by_tone", "step:draft")["value"], "calm")
        self.assertEqual(props(g, "key:passed")["type"], "true_or_false")

    def test_dynamic_policy_interpolation_and_nesting(self):
        g = compiled("dynamic-policy").graph
        self.assertEqual(bare(one(g, "READS", "step:check", "key:policy")), {"interpolated": True})
        self.assertEqual(bare(one(g, "READS", "step:check", "key:work")), {})
        self.assertEqual([e.end for e in g.edges_of("CONTAINS", "loop:revise")], ["loop:review", "step:summarize_check", "step:fix"])
        one(g, "ENTERS", "loop:revise", "loop:review")
        one(g, "ENTERS", "loop:review", "step:check")
        one(g, "CONTINUES", "step:check", "loop:review")
        one(g, "NEXT", "loop:review", "step:summarize_check")
        self.assertIn("{policy}", props(g, "question:check.follows")["instruction"])
        watches = one(g, "WATCHES", "loop:revise", "key:check_summary")
        self.assertEqual(watches["field"], "all_hold")
        agg = props(g, "aggregation:summarize_check.all_hold")
        self.assertEqual((agg["mode"], agg["source"], agg["confidence_above"]), ("All", "verdicts.follows", 0.7))
        self.assertEqual(one(g, "OVER", "aggregation:summarize_check.all_hold", "key:verdicts")["field"], "follows")
        self.assertEqual(props(g, "key:verdicts")["type"], "list")
        self.assertEqual(props(g, "key:verdict")["type"], "decision")

    def test_fixed_policy_aggregation(self):
        g = compiled("fixed-policy").graph
        self.assertEqual(one(g, "AGGREGATES", "step:summarize_check", "aggregation:summarize_check.all_hold"), {"order": 0})
        self.assertEqual(one(g, "OVER", "aggregation:summarize_check.all_hold", "key:policy_check"), {})
        self.assertEqual(props(g, "key:check_summary")["type"], "aggregation")
        self.assertEqual(props(g, "key:policy_check")["type"], "decision")
        self.assertEqual(props(g, "step:summarize_check")["produces"], "check_summary")

    def test_runtime_keys(self):
        source = PREFIX + ('Start "s" { items: list  Next_Step f }\nFor f Over items As i, At_Most 3 {\n'
                           '  Task_Agent t "t" { Read i, index  Produce o: string  Continue }\n  Next_Step u\n}\n'
                           'Task_Agent u "u" { Read iterations  Produce z: string  Next_Step end }\nEnd "e" { Read z }\n')
        bundle, diagnostics = compile_source(source, [])
        self.assertEqual(diagnostics, [])
        g = bundle.graph
        self.assertEqual((props(g, "key:index")["runtime"], props(g, "key:index")["type"]), (True, "integer"))
        one(g, "PRODUCES", "loop:f", "key:index")
        one(g, "PRODUCES", "loop:f", "key:iterations")
        one(g, "READS", "step:u", "key:iterations")
        self.assertIsNone(props(g, "key:i").get("type"), "an item of a plain list has no known type")

    def test_json_form_leaves_the_contents_out(self):
        bundle = compiled("billing-support")
        full = bundle.graph.to_dict()
        lean = bundle.graph.to_dict(content=False)
        self.assertEqual(set(full), {"nodes", "edges"})
        by_id = {n["id"]: n["properties"] for n in lean["nodes"]}
        self.assertNotIn("source", by_id[PROCEDURE_ID])
        self.assertNotIn("text", by_id["file:assets/config.json"])
        self.assertEqual({n["id"]: n["properties"] for n in full["nodes"]}[PROCEDURE_ID]["source"], bundle.source)
        self.assertEqual({"line", "column", "end_line", "end_column"} & set(by_id["step:triage"]), {"line", "column", "end_line", "end_column"})
        json.dumps(full)  # serialisable

    def test_canonical_form_ignores_order(self):
        a = compiled("fixed-policy").graph
        b = compiled("fixed-policy").graph
        b.nodes.reverse()
        b.edges.reverse()
        self.assertEqual(a.canonical(), b.canonical())
        self.assertNotEqual(a.canonical(), compiled("dynamic-policy").graph.canonical())


class TheBundleId(unittest.TestCase):
    def test_the_recipe(self):
        files = [FileEntry("scripts/b.py", b"print(1)\n", 0o755), FileEntry("assets/a.md", b"# a\n")]
        manifest = ("aip bundle 1\nsource " + hashlib.sha256(b"Procedure p").hexdigest() + "\n"
                    + f"file assets/a.md {hashlib.sha256(b'# a\n').hexdigest()}\n"
                    + f"file scripts/b.py {hashlib.sha256(b'print(1)\n').hexdigest()}\n")
        self.assertEqual(bundle_id("Procedure p", files), hashlib.sha256(manifest.encode()).hexdigest())
        self.assertEqual(bundle_id("Procedure p", list(reversed(files))), bundle_id("Procedure p", files), "sorted by path")

    def test_the_same_folder_anywhere_gives_the_same_id(self):
        bundle = compiled("billing-support")
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "elsewhere"
            shutil.copytree(example_dir("billing-support"), copy)
            again, _ = compile_folder(copy)
            self.assertEqual(again.id, bundle.id)
            self.assertEqual(again.graph.canonical(), bundle.graph.canonical())
            (copy / "assets" / "config.json").write_bytes((copy / "assets" / "config.json").read_bytes() + b"\n")
            changed, _ = compile_folder(copy)
            self.assertNotEqual(changed.id, bundle.id, "a byte in a file changes the id")
            self.assertEqual(len(bundle.id), 64)

    def test_mode_and_the_compiler_do_not_enter_the_id(self):
        source = PREFIX + 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n'
        a, _ = compile_source(source, [FileEntry("assets/a", b"x", 0o644)], compiler="1")
        b, _ = compile_source(source, [FileEntry("assets/a", b"x", 0o755)], compiler="2")
        self.assertEqual(a.id, b.id)
        self.assertEqual(a.graph.canonical(ignore=("compiler_version", "mode")), b.graph.canonical(ignore=("compiler_version", "mode")))
        self.assertEqual((a.compiler_version, b.compiler_version), ("1", "2"))


@needs_relate
class TheBundleFile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_compile_write_read_export_compile_gives_the_same_id_for_every_example(self):
        for name in example_names():
            with self.subTest(name):
                folder = example_dir(name)
                bundle = compiled(name)
                out = write_bundle(bundle, self.tmp / f"{name}.rl")
                self.assertTrue(out.is_file(), "an .rl is one file")
                back = read_bundle(out)
                self.assertEqual((back.id, back.name, back.source, back.language_version), (bundle.id, bundle.name, bundle.source, LANGUAGE_VERSION))
                self.assertEqual(back.graph.canonical(), bundle.graph.canonical())
                exported = export_bundle(back, self.tmp / f"{name}-export")
                self.assertEqual((exported / "procedure.aip").read_bytes(), (folder / "procedure.aip").read_bytes())
                for f in bundle.files:
                    self.assertEqual((exported / f.path).read_bytes(), (folder / f.path).read_bytes(), f.path)
                    if os.name == "posix":
                        self.assertEqual(stat.S_IMODE((exported / f.path).stat().st_mode), f.mode, f.path)
                self.assertEqual(sorted(str(p.relative_to(exported)) for p in exported.rglob("*") if p.is_file()),
                                 sorted(["procedure.aip"] + [str(Path(*Path(f.path).parts)) for f in bundle.files]), "nothing extra")
                again, _ = compile_folder(exported)
                self.assertEqual(again.id, bundle.id)

    def test_the_bundle_answers_cypher(self):
        bundle = compiled("billing-support")
        out = write_bundle(bundle, self.tmp / "b.rl")
        with relate.open(out) as conn:
            self.assertEqual(conn.execute("MATCH (s:Step) RETURN count(s) AS n").fetchall()[0]["n"], 6)
            self.assertEqual(conn.execute("MATCH (p:Procedure) RETURN p.bundle_id AS id").fetchall()[0]["id"], bundle.id)
            rows = conn.execute("MATCH (r:Route)-[b:BRANCH]->(t:Step) RETURN b.value AS v, t.name AS t ORDER BY v").fetchall()
            self.assertEqual([(r["v"], r["t"]) for r in rows], [("angry", "escalate"), ("calm", "reply")])
            with self.assertRaises(Exception):
                conn.execute("CREATE (:X)")  # read-only

    def test_a_hand_edit_is_tampered(self):
        bundle = compiled("billing-support")
        edits = {
            "a step": "MATCH (s:Step {name: 'triage'}) SET s.agent_fallback = false",
            "the source": "MATCH (p:Procedure) SET p.source = replace(p.source, 'Confidence_Below 0.6', 'Confidence_Below 0.9')",
            "a file": "MATCH (f:File {path: 'assets/config.json'}) SET f.text = '{}'",
            "an edge": "MATCH (:Route)-[b:BRANCH {value: 'angry'}]->() SET b.value = 'furious'",
            "a new node": "CREATE (:Step:Decide {id: 'step:extra', bundle_id: $b, name: 'extra', kind: 'Decide'})",
        }
        for what, cypher in edits.items():
            with self.subTest(what):
                out = write_bundle(bundle, self.tmp / "t.rl")
                with relate.open(out, read_only=False) as conn:
                    conn.execute(cypher, {"b": bundle.id})
                with self.assertRaises(BundleError) as caught:
                    read_bundle(out)
                self.assertEqual(caught.exception.code, "bundle_tampered", str(caught.exception))

    def test_what_is_not_a_bundle(self):
        junk = self.tmp / "junk.rl"
        junk.write_bytes(b"not a bundle")
        with self.assertRaises(BundleError) as caught:
            read_bundle(junk)
        self.assertEqual(caught.exception.code, "not_a_bundle")
        with relate.create(self.tmp / "empty.rl") as conn:
            conn.execute("CREATE (:Nothing)")
        with self.assertRaises(BundleError) as caught:
            read_bundle(self.tmp / "empty.rl")
        self.assertEqual(caught.exception.code, "not_a_bundle")
        with self.assertRaises(BundleError) as caught:
            read_bundle(self.tmp / "missing.rl")
        self.assertEqual(caught.exception.code, "not_a_bundle")

    def test_another_language_version_is_refused_before_verification(self):
        out = write_bundle(compiled("fixed-policy"), self.tmp / "v.rl")
        with relate.open(out, read_only=False) as conn:
            conn.execute("MATCH (p:Procedure) SET p.language_version = '0.8'")
        with self.assertRaises(BundleError) as caught:
            read_bundle(out)
        self.assertEqual(caught.exception.code, "bundle_language_version")

    def test_export_refuses_a_directory_in_use_unless_forced(self):
        bundle = compiled("fixed-policy")
        target = self.tmp / "out"
        target.mkdir()
        (target / "keep.txt").write_text("x")
        with self.assertRaises(BundleError) as caught:
            export_bundle(bundle, target)
        self.assertEqual(caught.exception.code, "export_target")
        export_bundle(bundle, target, force=True)
        self.assertTrue((target / "procedure.aip").is_file() and (target / "keep.txt").is_file())
        empty = self.tmp / "empty"
        empty.mkdir()
        export_bundle(bundle, empty)
        self.assertTrue((empty / "assets" / "policy.md").is_file())

    def test_writing_replaces_an_existing_file(self):
        out = self.tmp / "same.rl"
        write_bundle(compiled("fixed-policy"), out)
        write_bundle(compiled("dynamic-policy"), out)
        self.assertEqual(read_bundle(out).name, "dynamic_policy")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["same.rl"], "no temporary file is left behind")


class CompileAndExportCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_check_writes_nothing(self):
        with contextlib.chdir(self.tmp):
            code, out, err = self.run_cli("compile", "--check", str(example_dir("billing-support")))
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("ok billing_support: 6 steps, 5 files, bundle "), out)
        self.assertNotIn("wrote", out)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_json_report(self):
        code, out, err = self.run_cli("compile", "--check", "--json", str(example_dir("dynamic-policy")))
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual(set(report), {"procedure", "file", "ok", "bundle_id", "language_version", "compiler_version", "output",
                                       "diagnostics", "graph"})
        self.assertEqual((report["procedure"], report["ok"], report["output"], report["diagnostics"]), ("dynamic_policy", True, None, []))
        self.assertEqual(report["bundle_id"], compiled("dynamic-policy").id)
        ids = {n["id"] for n in report["graph"]["nodes"]}
        self.assertIn("loop:review", ids)
        self.assertNotIn("source", {n["id"]: n for n in report["graph"]["nodes"]}[PROCEDURE_ID]["properties"])
        self.assertTrue(all(set(e) == {"type", "start", "end", "properties"} for e in report["graph"]["edges"]))
        bad = self.tmp / "bad"
        bad.mkdir()
        (bad / "procedure.aip").write_text(PREFIX + 'Start "s" { m: string  Next_Step nowhere }\nEnd "e" { Read m }\n', encoding="utf-8")
        code, out, _ = self.run_cli("compile", "--check", "--json", str(bad))
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual((report["ok"], report["graph"], report["bundle_id"]), (False, None, None))
        self.assertEqual([d["code"] for d in report["diagnostics"]], ["unknown_step", "unreachable_step"][:len(report["diagnostics"])])

    @needs_relate
    def test_compile_writes_and_export_restores(self):
        with contextlib.chdir(self.tmp):
            code, out, err = self.run_cli("compile", str(example_dir("fixed-policy")))
            self.assertEqual(code, 0, err)
            self.assertTrue((self.tmp / "fixed_policy.rl").is_file(), "the default output is <name>.rl here")
            self.assertIn("wrote", out)
        code, out, err = self.run_cli("compile", str(example_dir("fixed-policy")), "-o", str(self.tmp / "x.rl"), "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["output"], str(self.tmp / "x.rl"))
        code, out, err = self.run_cli("export", str(self.tmp / "x.rl"), "--out", str(self.tmp / "restored"))
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("exported fixed_policy (bundle "), out)
        self.assertEqual((self.tmp / "restored" / "procedure.aip").read_bytes(),
                         (example_dir("fixed-policy") / "procedure.aip").read_bytes())
        code, _, err = self.run_cli("export", str(self.tmp / "x.rl"), "--out", str(self.tmp / "restored"))
        self.assertEqual(code, 1)
        self.assertIn("export_target", err)
        code, _, err = self.run_cli("export", str(self.tmp / "nope.rl"), "--out", str(self.tmp / "r2"))
        self.assertEqual(code, 2)
        (self.tmp / "junk.rl").write_bytes(b"junk")
        code, _, err = self.run_cli("export", str(self.tmp / "junk.rl"), "--out", str(self.tmp / "r3"))
        self.assertEqual(code, 1)
        self.assertIn("not_a_bundle", err)

    def test_errors_fail_the_command_and_write_nothing(self):
        bad = self.tmp / "bad"
        bad.mkdir()
        (bad / "procedure.aip").write_text(PREFIX + 'Start "s" { m: string  Next_Step nowhere }\nEnd "e" { Read m }\n', encoding="utf-8")
        with contextlib.chdir(self.tmp):
            code, out, err = self.run_cli("compile", str(bad))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("error unknown_step", err)
        self.assertTrue(err.rstrip().endswith("2 errors"), err)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["bad"])

    def test_the_aip_command_has_export(self):
        from aip.client.cli import COMMANDS
        self.assertIn("export", COMMANDS)
        self.assertIn("compile", COMMANDS)


if __name__ == "__main__":
    unittest.main()
