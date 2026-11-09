"""The checker: a case per diagnostic code on a small program, the rules of the state across loops
and routes, the examples compiling clean, and the `compile` command."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from aip_spec import CODES, Diagnostic, check, check_path, check_source, example_dir, example_names, format_program, parse
from aip_spec.cli import main

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "language"

PREFIX = 'Procedure p "x"\n'  # line 1 of every case
# A complete three-step program: Start on line 2, a task on line 3, End on line 4.
OK = 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n'
START = 'Start "s" { m: string  Next_Step d }\n'
DECIDE = 'Decide d "d" { Read m  Answer_Questions { q: choice [a, b] "?" }  Produce dec  Next_Step r }\n'
NOUL = 'Decide d "d" { Read m  Answer_Questions { q: noul "?" }  Produce dec  Next_Step r }\n'


def diagnostics(body: str, folder=None) -> list[Diagnostic]:
    return check(parse(PREFIX + body), folder)


def codes(body: str) -> list[str]:
    return [d.code for d in diagnostics(body)]


# (code, the source after the Procedure line, line, column, step) of the diagnostic that must be reported
CASES = [
    ("missing_start", 'End "e" { Read m }\n', 1, 1, None),
    ("missing_end", 'Start "s" { m: string  Next_Step end }\n', 1, 1, None),
    ("duplicate_step", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Next_Step u }\n'
                       'Task_Agent t "t" { Read o  Produce z: string  Next_Step end }\nEnd "e" { Read z }\n', 4, 1, "t"),
    ("duplicate_step", 'Start "s" { m: string  Next_Step t }\nStart "s" { n: string  Next_Step t }\n' + OK.split("\n", 1)[1], 3, 1, "start"),
    ("duplicate_name", 'a = "x"\na = "y"\n' + OK, 3, 1, None),
    ("unknown_name", 'Start "s" { m: string  Next_Step t }\nTask_Agent t nope { Read m  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n', 3, 14, "t"),
    ("unused_name", 'a = "x"\n' + OK, 2, 1, None),
    ("start_in_loop", 'Loop l 3 Times {\n  Start "s" { m: string  Next_Step end }\n  Next_Step end\n}\nEnd "e" { Read m }\n', 3, 3, "start"),
    ("end_in_loop", 'Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  End "e" { Read m }\n  Next_Step end\n}\n', 4, 3, "end"),
    ("reserved_key", 'Start "s" { index: integer  Next_Step t }\nTask_Agent t "t" { Read index  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n', 2, 13, "start"),
    ("missing_clause", START + 'Decide d "d" { Read m  Produce dec  Next_Step end }\nEnd "e" { Read dec }\n', 3, 1, "d"),
    ("missing_clause", START + 'Decide d "d" { Read m  Answer_Questions { q: noul "?" }  Next_Step end }\nEnd "e" { Read m }\n', 3, 1, "d"),
    ("missing_clause", START.replace("d }", "a }") + 'Aggregate a "a" { Read m  Produce agg  Next_Step end }\nEnd "e" { Read agg }\n', 3, 1, "a"),
    ("missing_clause", 'Requires python 3.10\n' + START.replace("d }", "e }") + 'Execute e "e" { Read m  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n', 4, 1, "e"),
    ("missing_type", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o  Next_Step end }\nEnd "e" { Read o }\n', 3, 36, "t"),
    ("missing_next_step", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string }\nEnd "e" { Read o }\n', 3, 1, "t"),
    ("question_labels", START + 'Decide d "d" { Read m  Answer_Questions { q: choice [a] "?" }  Produce dec  Next_Step end }\nEnd "e" { Read dec }\n', 3, 43, "d"),
    ("question_labels", START + 'Decide d "d" { Read m  Answer_Questions { q: noul [a, b] "?" }  Produce dec  Next_Step end }\nEnd "e" { Read dec }\n', 3, 43, "d"),
    ("question_labels", START + 'Decide d "d" { Read m  Answer_Questions { q: score [a, a] "?" }  Produce dec  Next_Step end }\nEnd "e" { Read dec }\n', 3, 43, "d"),
    ("duplicate_question", START + 'Decide d "d" { Read m  Answer_Questions { q: noul "?"  q: noul "?" }  Produce dec  Next_Step end }\nEnd "e" { Read dec }\n', 3, 56, "d"),
    ("duplicate_aggregation", START + NOUL.replace("Next_Step r", "Next_Step a")
     + 'Aggregate a "a" { Read dec  Aggregations { x: All dec  x: Any dec }  Produce agg  Next_Step end }\nEnd "e" { Read agg }\n', 4, 56, "a"),
    ("unknown_step", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Next_Step nowhere }\nEnd "e" { Read o }\n', 3, 47, "t"),
    ("unknown_step", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Next_Step start }\nEnd "e" { Read o }\n', 3, 47, "t"),
    ("unreachable_step", 'Start "s" { m: string  Next_Step end }\nTask_Agent t "t" { Read m  Produce o: string  Next_Step end }\nEnd "e" { Read m }\n', 3, 1, "t"),
    ("cycle_without_loop", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Next_Step u }\n'
                           'Task_Agent u "u" { Read o  Produce z: string  Next_Step t }\nEnd "e" { Read z }\n', 4, 47, "u"),
    ("jump_into_body", 'Start "s" { m: string  Next_Step inner }\nLoop l 3 Times {\n  Task_Agent inner "i" { Read m  Produce o: string  Continue }\n'
                       '  Next_Step end\n}\nEnd "e" { Read m }\n', 2, 24, "start"),
    ("flow_leaves_body", 'Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Task_Agent t "t" { Read m  Produce o: string  Next_Step end }\n'
                         '  Next_Step end\n}\nEnd "e" { Read m }\n', 4, 49, "t"),
    ("continue_outside_loop", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Continue }\nEnd "e" { Read o }\n', 3, 47, "t"),
    ("continue_outside_loop", 'Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Task_Agent t "t" { Read m  Produce o: string  Continue }\n'
                              '  Continue\n}\nEnd "e" { Read m }\n', 5, 3, "l"),
    ("again_outside_loop", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Again t }\nEnd "e" { Read o }\n', 3, 47, "t"),
    ("again_target", 'Start "s" { items: list  Next_Step f }\nFor f Over items As i, At_Most 3 {\n  Task_Agent t "t" { Read i  Produce o: string  Again f }\n'
                     '  Next_Step end\n}\nEnd "e" { Read items }\n', 4, 49, "t"),
    ("again_target", 'Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Task_Agent t "t" { Read m  Produce o: string  Again l }\n'
                     '  Next_Step end\n}\nEnd "e" { Read m }\n', 4, 49, "t"),
    ("again_target", 'Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Task_Agent t "t" { Read m  Produce o: string  Again after }\n'
                     '  Next_Step after\n}\nTask_Agent after "a" { Read m  Produce z: string  Next_Step end }\nEnd "e" { Read z }\n', 4, 49, "t"),
    ("missing_cap", 'Start "s" { items: list  Next_Step f }\nFor f Over items As i {\n  Task_Agent t "t" { Read i  Produce o: string  Continue }\n'
                    '  Next_Step end\n}\nEnd "e" { Read items }\n', 3, 1, "f"),
    ("missing_cap", 'Start "s" { m: string  Next_Step l }\nLoop l Until dec.q, Else_Exit {\n  Decide d "d" { Read m  Answer_Questions { q: noul "?" }  Produce dec  Continue }\n'
                    '  Next_Step end\n}\nEnd "e" { Read dec }\n', 3, 1, "l"),
    ("missing_cap", 'Start "s" { m: string  Next_Step l }\nLoop l 0 Times {\n  Task_Agent t "t" { Read m  Produce o: string  Continue }\n'
                    '  Next_Step end\n}\nEnd "e" { Read m }\n', 3, 1, "l"),
    ("empty_loop", 'Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Next_Step end\n}\nEnd "e" { Read m }\n', 3, 1, "l"),
    ("missing_loop_exit", 'Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Task_Agent t "t" { Read m  Produce o: string  Continue }\n}\nEnd "e" { Read m }\n', 3, 1, "l"),
    ("unknown_key", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read nothing  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n', 3, 25, "t"),
    ("unavailable_key", START + NOUL + 'Route r "r" { Read dec.q  true -> a  false -> b }\nTask_Agent a "a" { Read m  Produce x: string  Next_Step c }\n'
                        'Task_Agent b "b" { Read m  Produce y: string  Next_Step c }\nTask_Agent c "c" { Read x  Produce z: string  Next_Step end }\nEnd "e" { Read z }\n', 7, 25, "c"),
    ("unknown_field", START + NOUL + 'Route r "r" { Read dec.nope  true -> end  false -> end }\nEnd "e" { Read dec }\n', 4, 20, "r"),
    ("duplicate_producer", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m  Produce o: string  Next_Step u }\n'
                           'Task_Agent u "u" { Read o  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n', 4, 36, "u"),
    ("type_mismatch", 'Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read m: integer  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n', 3, 25, "t"),
    ("route_reads_one", START + NOUL + 'Route r "r" { Read dec.q, m  true -> end  false -> end }\nEnd "e" { Read dec }\n', 4, 1, "r"),
    ("condition_on_plain_value", START + NOUL + 'Route r "r" { Read m  true -> end  false -> end }\nEnd "e" { Read dec }\n', 4, 20, "r"),
    ("missing_branch", START + DECIDE + 'Route r "r" { Read dec.q  a -> end }\nEnd "e" { Read dec }\n', 4, 1, "r"),
    ("duplicate_branch", START + DECIDE + 'Route r "r" { Read dec.q  a -> end  a -> end  b -> end }\nEnd "e" { Read dec }\n', 4, 37, "r"),
    ("unknown_label", START + DECIDE + 'Route r "r" { Read dec.q  a -> end  b -> end  c -> end }\nEnd "e" { Read dec }\n', 4, 47, "r"),
    ("comparison_required", 'Start "s" { m: string  Next_Step l }\nLoop l Until dec.q, At_Most 3 {\n'
                            '  Decide d "d" { Read m  Answer_Questions { q: choice [a, b] "?" }  Produce dec  Continue }\n  Next_Step end\n}\nEnd "e" { Read dec }\n', 3, 14, "l"),
    ("confidence_on_aggregate", START + NOUL.replace("Next_Step r", "Next_Step a")
     + 'Aggregate a "a" { Read dec  Aggregations { all: All dec }  Produce agg  Next_Step r }\n'
     'Route r "r" { Read agg.all  Confidence_Below 0.5 -> end  true -> end  false -> end }\nEnd "e" { Read agg }\n', 5, 29, "r"),
    ("source_not_read", START + NOUL.replace("Next_Step r", "Next_Step a")
     + 'Aggregate a "a" { Read m  Aggregations { all: All dec }  Produce agg  Next_Step end }\nEnd "e" { Read agg }\n', 4, 51, "a"),
    ("confidence_on_unmeasured_source", START + NOUL.replace("Produce", "Agent_Fallback true  Produce")
     + 'Route r "r" { Read dec.q  Confidence_Below 0.5 -> end  true -> end  false -> end }\nEnd "e" { Read dec }\n', 4, 27, "r"),
    ("unmeasured_route", START + NOUL.replace("Produce", "Agent_Fallback true  Produce")
     + 'Route r "r" { Read dec.q  true -> end  false -> end }\nEnd "e" { Read dec }\n', 4, 1, "r"),
    ("missing_file", 'Requires python 3.10\n' + START.replace("d }", "e }")
     + 'Execute e "e" { Read m  Run_Script nope.py  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n', 4, 25, "e"),
    ("missing_requires", START.replace("d }", "e }") + 'Execute e "e" { Read m  Run_Script scripts/x.py  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n', 3, 1, "e"),
]


class EveryCode(unittest.TestCase):
    def test_each_code_is_reported_at_its_position(self):
        covered = set()
        for code, body, line, column, step in CASES:
            with self.subTest(code=code, line=line):
                found = [d for d in diagnostics(body) if d.code == code]
                self.assertTrue(found, f"{code} not reported; got {[str(d) for d in diagnostics(body)]}")
                self.assertIn((line, column, step), [(d.line, d.column, d.step) for d in found], [str(d) for d in found])
                self.assertTrue(all(d.severity == CODES[code] for d in found))
                self.assertTrue(all(d.end_line >= d.line and (d.end_line > d.line or d.end_column > d.column) for d in found), "a span, not a point")
                covered.add(code)
        self.assertEqual(covered, set(CODES) - {"missing_file"} | {"missing_file"}, "every code has a case")

    def test_syntax_error_is_a_diagnostic(self):
        program, found = check_source('Procedure p "x"\nDecide d {}\n', "p/procedure.aip")
        self.assertIsNone(program)
        [d] = found
        self.assertEqual((d.code, d.severity, d.line, d.column, d.file), ("syntax_error", "error", 2, 10, "p/procedure.aip"))

    def test_diagnostic_shape(self):
        [d] = [x for x in diagnostics(CASES[0][1]) if x.code == "missing_start"]
        self.assertEqual(set(d.to_dict()), {"code", "severity", "message", "file", "line", "column", "end_line", "end_column", "step"})
        self.assertEqual(str(d), "1:1: error missing_start: " + d.message)

    def test_a_correct_program_has_no_diagnostics(self):
        self.assertEqual(codes(OK), [])


class StateRules(unittest.TestCase):
    """Spec 2.3: one producer per path, rebinding inside a loop, what a loop leaves behind."""

    def test_route_arms_may_write_the_same_key(self):
        body = START + NOUL + ('Route r "r" { Read dec.q  true -> a  false -> b }\nTask_Agent a "a" { Read m  Produce x: string  Next_Step c }\n'
                               'Task_Agent b "b" { Read m  Produce x: string  Next_Step c }\nTask_Agent c "c" { Read x  Produce z: string  Next_Step end }\n'
                               'End "e" { Read z, x }\n')
        self.assertEqual(codes(body), [])

    def test_arms_disagreeing_on_a_type_is_a_mismatch_at_the_join(self):
        body = START + NOUL + ('Route r "r" { Read dec.q  true -> a  false -> b }\nTask_Agent a "a" { Read m  Produce x: string  Next_Step c }\n'
                               'Task_Agent b "b" { Read m  Produce x: integer  Next_Step c }\nTask_Agent c "c" { Read x  Produce z: string  Next_Step end }\n'
                               'End "e" { Read z }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.step), ("type_mismatch", "c"))
        self.assertIn("a string from a; an integer from b", d.message)

    def test_a_loop_body_may_rewrite_a_key_from_before_the_loop(self):
        body = ('Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Task_Agent t "t" { Read m  Produce m: string  Continue }\n'
                '  Next_Step end\n}\nEnd "e" { Read m, iterations }\n')
        self.assertEqual(codes(body), [])

    def test_two_steps_in_one_pass_may_not_write_the_same_key(self):
        body = ('Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Task_Agent t "t" { Read m  Produce o: string  Next_Step u }\n'
                '  Task_Agent u "u" { Read o  Produce o: string  Continue }\n  Next_Step end\n}\nEnd "e" { Read o }\n')
        self.assertEqual(codes(body), ["duplicate_producer"])

    def test_a_step_after_a_loop_may_not_rewrite_what_the_body_produced(self):
        body = ('Start "s" { m: string  Next_Step l }\nLoop l 3 Times {\n  Task_Agent t "t" { Read m  Produce o: string  Continue }\n'
                '  Next_Step u\n}\nTask_Agent u "u" { Read o  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.step), ("duplicate_producer", "u"))
        self.assertIn("already produced by t", d.message)

    def test_for_keys_are_per_pass_unless_collected(self):
        body = ('Start "s" { items: list  Next_Step f }\nFor f Over items As i, At_Most 3 {\n  Task_Agent t "t" { Read i, index  Produce o: string  Continue }\n'
                '  Next_Step end\n}\nEnd "e" { Read o, iterations }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.line), ("unavailable_key", 7))
        self.assertIn("per-pass", d.message)
        self.assertIn("Collect o Into", d.message)
        self.assertEqual(codes(body.replace("At_Most 3", "At_Most 3, Collect o Into os").replace("Read o,", "Read os,")), [])

    def test_collect_needs_the_key_on_every_pass(self):
        body = ('Start "s" { items: list  Next_Step f }\nFor f Over items As i, At_Most 3, Collect o Into os {\n'
                '  Decide d "d" { Read i  Answer_Questions { q: noul "?" }  Produce dec  Next_Step r }\n'
                '  Route r "r" { Read dec.q  true -> t  false -> Continue }\n'
                '  Task_Agent t "t" { Read i  Produce o: string  Continue }\n  Next_Step end\n}\nEnd "e" { Read os }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.line, d.column, d.step), ("unavailable_key", 3, 35, "f"))
        self.assertIn("may end without producing o", d.message)
        [d] = diagnostics(body.replace("Collect o Into", "Collect zz Into"))
        self.assertEqual(d.code, "unknown_key")

    def test_a_loop_leaves_only_what_every_exit_has_written(self):
        body = ('Start "s" { m: string  Next_Step l }\nLoop l Until dec.q, At_Most 3 {\n'
                '  Decide d "d" { Read m  Answer_Questions { q: noul "?" }  Produce dec  Next_Step r }\n'
                '  Route r "r" { Read dec.q  true -> Continue  false -> t }\n'
                '  Task_Agent t "t" { Read m  Produce extra: string  Continue }\n  Next_Step end\n}\nEnd "e" { Read dec, extra }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.step), ("unavailable_key", "end"))
        self.assertIn("extra", d.message)
        self.assertEqual(codes(body.replace("Read dec, extra", "Read dec")), [])

    def test_index_and_iterations(self):
        self.assertEqual(codes('Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read index  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n'),
                         ["unavailable_key"])
        self.assertEqual(codes('Start "s" { m: string  Next_Step t }\nTask_Agent t "t" { Read iterations  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n'),
                         ["unavailable_key"])
        self.assertEqual(codes('Start "s" { items: list  Next_Step f }\nFor f Over items As index, At_Most 3 {\n'
                               '  Task_Agent t "t" { Read index  Produce o: string  Continue }\n  Next_Step end\n}\nEnd "e" { Read items }\n'), ["reserved_key"])

    def test_item_and_collect_names_may_not_shadow_a_key(self):
        body = ('Start "s" { items: list  m: string  Next_Step f }\nFor f Over items As m, At_Most 3 {\n'
                '  Task_Agent t "t" { Read m  Produce o: string  Continue }\n  Next_Step end\n}\nEnd "e" { Read items }\n')
        self.assertEqual(codes(body), ["duplicate_producer"])
        self.assertEqual(codes(body.replace("As m", "As i").replace("At_Most 3", "At_Most 3, Collect o Into m")), ["duplicate_producer"])

    def test_over_needs_a_list(self):
        body = ('Start "s" { m: string  Next_Step f }\nFor f Over m As i, At_Most 3 {\n'
                '  Task_Agent t "t" { Read i  Produce o: string  Continue }\n  Next_Step end\n}\nEnd "e" { Read m }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.line, d.column), ("type_mismatch", 3, 12))

    def test_interpolations_count_as_reads(self):
        body = START + 'Decide d "d" { Read m  Answer_Questions { q: noul "Is {m} fine given {nope}?" }  Produce dec  Next_Step end }\nEnd "e" { Read dec }\n'
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.line, d.column, d.step), ("unknown_key", 3, 70, "d"))
        body = START + NOUL.replace("Next_Step r", "Next_Step t") + 'Task_Agent t "Judge {dec.nope} and {dec.q.value}." { Read dec  Produce o: string  Next_Step end }\nEnd "e" { Read o }\n'
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.step), ("unknown_field", "t"))
        self.assertEqual(codes(body.replace("{dec.nope}", "{dec.q.confidence}")), [])

    def test_a_named_string_is_checked_where_it_is_used(self):
        body = 'q = "About {policy}"\n' + START + 'Decide d "d" { Read m  Answer_Questions { q: noul q }  Produce dec  Next_Step end }\nEnd "e" { Read dec }\n'
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.line, d.column, d.step), ("unknown_key", 2, 12, "d"))


class Conditions(unittest.TestCase):
    """Spec 2.4 and 2.5: what a route, an Until and an aggregation may be on."""

    def test_until_on_a_plain_boolean_from_a_script(self):
        body = ('Requires python 3.10\nStart "s" { m: string  Next_Step l }\nLoop l Until passed, At_Most 3 {\n'
                '  Execute e "e" { Read m  Run_Script scripts/x.py  Produce passed: boolean  Continue }\n  Next_Step end\n}\nEnd "e" { Read passed }\n')
        found = [d for d in diagnostics(body) if d.code == "condition_on_plain_value"]
        self.assertEqual([(d.line, d.column, d.step) for d in found], [(4, 14, "l")])
        self.assertIn("never a plain value", found[0].message)
        self.assertEqual(codes(body.replace("passed: boolean", "passed: true_or_false")), [])

    def test_until_needs_its_answer_produced_before_or_inside(self):
        body = ('Start "s" { m: string  Next_Step l }\nLoop l Until dec.q, At_Most 3 {\n  Task_Agent t "t" { Read m  Produce o: string  Continue }\n'
                '  Next_Step d\n}\nDecide d "d" { Read o  Answer_Questions { q: noul "?" }  Produce dec  Next_Step end }\nEnd "e" { Read dec }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.line, d.column), ("unavailable_key", 3, 14))
        self.assertIn("neither before Loop l nor by a step in its body", d.message)
        self.assertEqual(codes(body.replace("Until dec.q", "Until nothing.q")), ["unknown_key"])

    def test_until_answer_produced_before_the_loop_and_renewed_by_again(self):
        self.assertEqual([d.code for d in check_path(EXAMPLES / "ticket-triage")[1]], [])

    def test_confidence_bar_on_a_script_answer_warns_and_on_an_aggregation_fails(self):
        body = ('Requires python 3.10\nStart "s" { m: string  Next_Step l }\nLoop l Until passed With Confidence_Above 0.8, At_Most 3 {\n'
                '  Execute e "e" { Read m  Run_Script scripts/x.py  Produce passed: true_or_false  Continue }\n  Next_Step end\n}\nEnd "e" { Read passed }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.severity, d.step), ("confidence_on_unmeasured_source", "warning", "l"))
        self.assertIn("comes from e, not a decision model", d.message)
        body = (START + NOUL.replace("Next_Step r", "Next_Step a")
                + 'Aggregate a "a" { Read dec  Aggregations { all: All dec }  Produce agg  Next_Step b }\n'
                'Aggregate b "b" { Read agg  Aggregations { again: All agg.all With Confidence_Above 0.5 }  Produce agg2  Next_Step end }\nEnd "e" { Read agg2 }\n')
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.step), ("confidence_on_aggregate", "b"))

    def test_aggregation_sources(self):
        loop = ('Start "s" { items: list  Next_Step f }\nFor f Over items As i, At_Most 5, Collect verdict Into verdicts {\n'
                '  Decide d "d" { Read i  Answer_Questions { q: noul "?"  c: choice [a, b] "?" }  Produce verdict  Continue }\n  Next_Step agg\n}\n')
        ok = loop + 'Aggregate agg "a" { Read verdicts  Aggregations { all: All verdicts.q  none: None verdicts.c == a With Confidence_Above 0.7 }  Produce s  Next_Step end }\nEnd "e" { Read s }\n'
        self.assertEqual(codes(ok), [])
        whole = loop + 'Aggregate agg "a" { Read verdicts  Aggregations { all: All verdicts }  Produce s  Next_Step end }\nEnd "e" { Read s }\n'
        [d] = diagnostics(whole)
        self.assertEqual(d.code, "comparison_required", "the decision's choice question needs a comparison")
        self.assertIn("verdicts[].c", d.message)
        plain = loop + 'Aggregate agg "a" { Read items  Aggregations { all: All items }  Produce s  Next_Step end }\nEnd "e" { Read s }\n'
        [d] = diagnostics(plain)
        self.assertEqual(d.code, "condition_on_plain_value")
        self.assertIn("not known to be answers", d.message)
        wrong_label = loop + 'Aggregate agg "a" { Read verdicts  Aggregations { all: All verdicts.c == z }  Produce s  Next_Step end }\nEnd "e" { Read s }\n'
        self.assertEqual(codes(wrong_label), ["unknown_label"])
        wrong_bool = loop + 'Aggregate agg "a" { Read verdicts  Aggregations { all: All verdicts.q == yes }  Produce s  Next_Step end }\nEnd "e" { Read s }\n'
        self.assertEqual(codes(wrong_bool), ["unknown_label"])

    def test_a_collected_answer_key_is_a_source(self):
        body = ('Requires python 3.10\nStart "s" { items: list  Next_Step f }\nFor f Over items As i, At_Most 5, Collect passed Into results {\n'
                '  Execute e "e" { Read i  Run_Script scripts/x.py  Produce passed: true_or_false  Continue }\n  Next_Step agg\n}\n'
                'Aggregate agg "a" { Read results  Aggregations { all: All results }  Produce s  Next_Step r }\n'
                'Route r "r" { Read s.all  true -> end  false -> end }\nEnd "e" { Read s }\n')
        self.assertEqual(codes(body), [])

    def test_route_on_a_score_and_its_criteria(self):
        decide = 'Decide d "d" { Read m  Answer_Questions { u: score [low, high] "?"\n    low: "l"\n    mid: "m" }  Produce dec  Next_Step r }\n'
        body = START + decide + 'Route r "r" { Read dec.u  low -> end  high -> end }\nEnd "e" { Read dec }\n'
        [d] = diagnostics(body)
        self.assertEqual((d.code, d.line, d.column), ("unknown_label", 5, 5))
        self.assertIn("criterion mid", d.message)

    def test_a_route_may_read_the_whole_decision_only_by_naming_an_answer(self):
        body = START + NOUL + 'Route r "r" { Read dec  true -> end  false -> end }\nEnd "e" { Read dec }\n'
        [d] = diagnostics(body)
        self.assertEqual(d.code, "condition_on_plain_value")
        self.assertIn("such as dec.q", d.message)

    def test_a_route_with_only_a_check_is_measured_on_a_model_answer(self):
        body = START + DECIDE + 'Route r "r" { Read dec.q  Confidence_Below 0.7 -> end  a -> end  b -> end }\nEnd "e" { Read dec }\n'
        self.assertEqual(codes(body), [])
        self.assertEqual(codes(body.replace("Confidence_Below 0.7 -> end  ", "")), [], "a measured route needs no check")


class Resources(unittest.TestCase):
    def test_files_are_checked_against_the_folder(self):
        body = ('Requires python 3.10\nStart "s" { m: string  Next_Step e }\n'
                'Execute e "e" { Read m  Run_Script scripts/run.py  Use assets/cfg.json  Produce o: string  Next_Step t }\n'
                'Task_Agent t "t" { Read o  Prompt assets/p.md  Use references/r.md "when"  Produce z: string  Next_Step end }\nEnd "e" { Read z }\n')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            found = diagnostics(body, folder)
            self.assertEqual([(d.code, d.line, d.column) for d in found],
                             [("missing_file", 4, 25), ("missing_file", 4, 56), ("missing_file", 5, 28), ("missing_file", 5, 52)],
                             "Run_Script and Prompt are reported at the clause, each Use at its path")
            self.assertIn("does not exist", found[0].message)
            for rel in ("scripts/run.py", "assets/cfg.json", "assets/p.md", "references/r.md"):
                (folder / rel).parent.mkdir(exist_ok=True)
                (folder / rel).write_text("x")
            self.assertEqual(diagnostics(body, folder), [])
            self.assertEqual(diagnostics(body), [], "without a folder, existence is not checked")
        self.assertEqual(codes(body.replace("scripts/run.py", "../run.py")), ["missing_file"])
        self.assertEqual(codes(body.replace("assets/p.md", "p.md")), ["missing_file"])


class Examples(unittest.TestCase):
    def test_the_examples_compile_clean(self):
        for name in example_names():
            with self.subTest(name):
                program, found = check_path(example_dir(name))
                self.assertIsNotNone(program)
                self.assertEqual([d for d in found if d.severity == "error"], [], [str(d) for d in found])
                if name == "billing-support":
                    [d] = found
                    self.assertEqual((d.code, d.line, d.step), ("confidence_on_unmeasured_source", 50, "by_tone"))
                else:
                    self.assertEqual(found, [], name)

    def test_the_spec_summary_example_is_the_ticket_triage_example(self):
        spec = (Path(__file__).resolve().parents[3] / "docs" / "language" / "spec.md").read_text(encoding="utf-8")
        block = spec.split("```aip\n", 1)[1].split("```", 1)[0]
        code_lines = lambda text: [line for line in format_program(parse(text)).splitlines() if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(code_lines(block), code_lines((EXAMPLES / "ticket-triage" / "procedure.aip").read_text(encoding="utf-8")),
                         "the two differ only in comments")
        self.assertEqual(check(parse(block)), [])

    def test_every_code_is_in_the_spec(self):
        spec = (Path(__file__).resolve().parents[3] / "docs" / "language" / "spec.md").read_text(encoding="utf-8")
        for code in CODES:
            self.assertIn(f"`{code}`", spec, code)


class CompileCommand(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_check_the_examples(self):
        for name in example_names():
            with self.subTest(name):
                code, out, err = self.run_cli("compile", "--check", str(example_dir(name)))
                self.assertEqual(code, 0, err)
                self.assertTrue(out.startswith(f"ok {name.replace('-', '_')}: "), out)
                self.assertEqual("warning" in err, name == "billing-support")

    def test_json_output(self):
        code, out, err = self.run_cli("compile", "--check", "--json", str(example_dir("billing-support")))
        self.assertEqual((code, err), (0, ""))
        report = json.loads(out)
        self.assertEqual((report["procedure"], report["ok"], len(report["diagnostics"])), ("billing_support", True, 1))
        self.assertEqual(set(report["diagnostics"][0]), {"code", "severity", "message", "file", "line", "column", "end_line", "end_column", "step"})
        self.assertTrue(report["file"].endswith("procedure.aip"))

    def test_errors_fail_the_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "bad"
            folder.mkdir()
            (folder / "procedure.aip").write_text(PREFIX + 'Start "s" { m: string  Next_Step nowhere }\nEnd "e" { Read m }\n', encoding="utf-8")
            code, out, err = self.run_cli("compile", str(folder))
            self.assertEqual((code, out), (1, ""))
            self.assertIn("error unknown_step", err)
            self.assertIn("error unreachable_step", err)
            self.assertTrue(err.rstrip().endswith("2 errors"), err)
            code, out, err = self.run_cli("compile", "--json", str(folder / "procedure.aip"))
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(out)["ok"])
            (folder / "procedure.aip").write_text("Procedure", encoding="utf-8")
            code, out, err = self.run_cli("compile", "--check", "--json", str(folder))
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(out)["diagnostics"][0]["code"], "syntax_error")

    def test_missing_path(self):
        code, _, err = self.run_cli("compile", "/nonexistent/folder")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)


if __name__ == "__main__":
    unittest.main()
