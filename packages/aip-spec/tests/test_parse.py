"""The parser: the example programs, the shape of the tree, every alias and header form, comments."""

import unittest
from pathlib import Path

from aip_spec import LANGUAGE_VERSION, example_dir, example_names, format_program, parse
from aip_spec import syntax as s
from aip_spec.keywords import ALIASES, keyword

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "language"


def source(name: str) -> str:
    return (EXAMPLES / name / "procedure.aip").read_text(encoding="utf-8")


class Examples(unittest.TestCase):
    def test_every_example_parses_and_round_trips(self):
        files = sorted(EXAMPLES.glob("*/procedure.aip"))
        self.assertEqual(len(files), 5, files)
        for file in files:
            with self.subTest(file=file.parent.name):
                text = file.read_text(encoding="utf-8")
                program = parse(text, str(file))
                formatted = format_program(program)
                self.assertEqual(parse(formatted, str(file)), program, "parse(format(parse(x))) == parse(x)")
                self.assertEqual(format_program(parse(formatted)), formatted, "the formatter is idempotent")

    def test_bundled_examples_are_the_language_examples(self):
        self.assertEqual(example_names(), ["billing-support", "billing-support-agent", "dynamic-policy", "fixed-policy", "ticket-triage"])
        self.assertTrue((example_dir("billing-support") / "procedure.aip").is_file())
        with self.assertRaises(FileNotFoundError):
            example_dir("nope")

    def test_language_version(self):
        self.assertEqual(LANGUAGE_VERSION, "0.9")


class BillingSupport(unittest.TestCase):
    """The tree of `examples/language/billing-support`, clause by clause."""

    @classmethod
    def setUpClass(cls):
        cls.p = parse(source("billing-support"))

    def test_header(self):
        p = self.p
        self.assertEqual(p.name, "billing_support")
        self.assertTrue(p.description.value.startswith("Turn an inbound billing message"))
        self.assertEqual(p.leading[0], "# billing-support/procedure.aip")
        self.assertEqual(p.leading[-1], "", "a blank line separates the file comment from Procedure")
        kinds = [(h.keyword, len(h.strings)) if isinstance(h, s.HeaderClause) else ("Requires", h.interpreter, h.version) for h in p.header]
        self.assertEqual(kinds, [("Use_When", 2), ("Do_Not_Use_When", 1), ("Requires", "python", "3.10"), ("Avoid", 2)])

    def test_named_strings_and_items(self):
        names = self.p.named_strings
        self.assertEqual(set(names), {"tone_question", "help_reference"})
        self.assertTrue(names["tone_question"].text.value.startswith("How upset"))
        self.assertEqual([st.kind for st in self.p.steps()], ["Start", "Decide", "Route", "Execute", "Task_Agent", "End"])
        self.assertEqual([st.name for st in self.p.steps()], [None, "triage", "by_tone", "escalate", "reply", None])

    def test_start(self):
        start = self.p.step("start")
        [inp] = start.inputs
        self.assertEqual((inp.key.dotted, inp.type, inp.description.value), ("message", "string", "The customer's message, verbatim."))
        self.assertEqual(start.flow, s.Flow("Next_Step", "triage"))

    def test_decide(self):
        d = self.p.step("triage")
        self.assertEqual([r.key.dotted for r in d.reads], ["message"])
        billing, tone = d.questions
        self.assertEqual((billing.name, billing.type, billing.labels), ("billing", "true_or_false", []))
        self.assertIsInstance(billing.instruction, s.Text)
        self.assertEqual((tone.name, tone.type, tone.labels), ("tone", "choice", ["angry", "calm"]))
        self.assertEqual(tone.instruction, s.NameRef("tone_question"))
        self.assertEqual([(c.label, c.text.value) for c in tone.criteria],
                         [("angry", "Frustrated, demanding, or threatening to leave."), ("calm", "Neutral or polite, asking a question.")])
        self.assertFalse(d.flag("History"))
        self.assertEqual([k.key.dotted for k in d.produces], ["triage_decision"])
        self.assertEqual([type(c).__name__ for c in d.clauses], ["ReadClause", "QuestionsClause", "ProduceClause", "FlowClause"],
                         "a Decide is its questions and its key; there is no Agent_Fallback")

    def test_labelled_produce(self):
        """`billing-support-agent`: the agent's answers are produced under declared labels."""
        agent = parse((EXAMPLES / "billing-support-agent" / "procedure.aip").read_text(encoding="utf-8"))
        t = agent.step("triage")
        self.assertEqual(t.kind, "Task_Agent")
        billing, tone = t.produces
        self.assertEqual((billing.key.name, billing.type, billing.labels), ("billing", "true_or_false", []))
        self.assertEqual((tone.key.name, tone.type, tone.labels, tone.description.value), ("tone", "choice", ["angry", "calm"], "How upset the customer is."))
        self.assertEqual(agent.step("by_tone").check, None, "no confidence check on an agent's answer")
        inline = parse('Procedure p "x"\nStart "s" {\n  level: score [low, mid, high] "The level."\n  Next_Step end\n}\n')
        [inp] = inline.step("start").inputs
        self.assertEqual((inp.type, inp.labels), ("score", ["low", "mid", "high"]))

    def test_route(self):
        r = self.p.step("by_tone")
        self.assertEqual(r.particle, "On")
        self.assertEqual([x.key.dotted for x in r.reads], ["triage_decision.tone"])
        self.assertEqual(r.reads[0].key.path, ["triage_decision", "tone"])
        self.assertEqual((r.check.below, r.check.target), (0.6, s.Flow("Next_Step", "escalate")))
        self.assertEqual([(b.value, b.target.step) for b in r.branches], [("angry", "escalate"), ("calm", "reply")])
        self.assertIsNone(r.flow)

    def test_execute(self):
        e = self.p.step("escalate")
        self.assertEqual(e.script, "scripts/escalate.py")
        self.assertEqual([(u.path, u.description) for u in e.uses], [("assets/config.json", None)])
        self.assertEqual([(k.key.dotted, k.type, k.description.value) for k in e.produces],
                         [("ticket_id", "integer", "The tier-2 ticket opened for the message."),
                          ("queue", "string", "The queue the ticket was routed to.")],
                         "Produce continues on the indented line")
        self.assertEqual(e.flow, s.Flow("Next_Step", "end"))

    def test_task_agent(self):
        t = self.p.step("reply")
        self.assertEqual(t.particle, "With")
        self.assertEqual(t.prompt, "assets/reply.md")
        self.assertEqual([(u.path, u.description) for u in t.uses],
                         [("assets/policy.md", None), ("references/help.md", s.NameRef("help_reference"))])

    def test_end(self):
        end = self.p.step("end")
        self.assertEqual([r.key.dotted for r in end.reads], ["message"])
        self.assertIsNone(end.flow)

    def test_positions(self):
        """Every node knows its line and column, 1-based."""
        lines = source("billing-support").splitlines()
        for st in self.p.steps():
            with self.subTest(step=st.kind):
                self.assertTrue(lines[st.line - 1][st.column - 1:].startswith(st.kind) or st.kind == "Task_Agent"
                                and lines[st.line - 1][st.column - 1:].startswith("Task"), (st.line, st.column))
                self.assertEqual(lines[st.end_line - 1][st.end_column - 2], "}", "a step ends at its closing brace")
        route = self.p.step("by_tone")
        self.assertEqual(lines[route.check.line - 1][route.check.column - 1:].split()[0], "Confidence_Below")
        self.assertEqual(lines[route.check.target.line - 1][route.check.target.column - 1:], "escalate")


class Loops(unittest.TestCase):
    def test_for_with_collect_and_nested_loop(self):
        p = parse(source("ticket-triage"))
        [each] = [i for i in p.items if isinstance(i, s.ForLoop)]
        self.assertEqual((each.name, each.over.dotted, each.item, each.at_most), ("each_ticket", "tickets", "ticket", 50))
        self.assertEqual(each.collect, s.Collect("reply", "replies"))
        self.assertEqual([b.name for b in each.body], ["classify", "by_tone", "draft", "escalate", "check", "revise"])
        self.assertEqual(each.exit, s.Flow("Next_Step", "summarize"))
        revise = each.body[-1]
        self.assertIsInstance(revise, s.Loop)
        self.assertEqual((revise.mode, revise.at_most, revise.at_cap), ("Until", 3, "Else_Fail"))
        self.assertEqual(revise.until, s.Condition(s.KeyRef(["passed"])))
        self.assertEqual(revise.exit, s.Flow("Continue"), "a nested loop may end the outer pass when it exits")
        self.assertEqual((revise.line, revise.column), (59, 3))
        self.assertEqual(revise.body[0].flow, s.Flow("Again", "check"))
        self.assertEqual([st.name for st in p.steps()][-2:], ["summarize", None])
        self.assertEqual([lp.name for lp in p.loops()], ["each_ticket", "revise"])

    def test_until_loop_with_for_inside(self):
        p = parse(source("dynamic-policy"))
        [revise] = [i for i in p.items if isinstance(i, s.Loop)]
        self.assertEqual(revise.until, s.Condition(s.KeyRef(["check_summary", "all_hold"])))
        review = revise.body[0]
        self.assertIsInstance(review, s.ForLoop)
        self.assertEqual(review.exit, s.Flow("Next_Step", "summarize_check"))
        self.assertEqual(review.body[0].flow, s.Flow("Continue"))
        self.assertEqual(revise.exit, s.Flow("Next_Step", "end"))
        agg = p.step("summarize_check").aggregations[0]
        self.assertEqual((agg.name, agg.mode), ("all_hold", "All"))
        self.assertEqual(agg.condition, s.Condition(s.KeyRef(["verdicts", "follows"]), None, None, 0.7))

    def test_every_header_form(self):
        p = parse("""
            Procedure loops "Every loop header."
            Start "x" { items: list  Next_Step a }
            Loop a 3 Times { Task_Agent t "x" { Read items  Produce out: string  Continue }  Next_Step b }
            Loop b Over items As item, At_Most 5 { Task_Agent u "x" { Read item  Produce out: string  Continue }  Next_Step c }
            Loop c Until verdict.ok == true With Confidence_Above 0.8, Max 2, Else_Exit {
              Decide d "x" { Read out  Questions { ok: noul "Fine?" }  Produce verdict  Continue }
              Next_Step e
            }
            For_Each e Over items As item At_Most 4 Collect out Into outs {
              Task f "x" { Read item  Produce out: string  Continue }
              Next_Step end
            }
            End "x" { Read outs }
        """)
        a, b, c, e = [i for i in p.items if isinstance(i, (s.Loop, s.ForLoop))]
        self.assertEqual((a.mode, a.times, a.at_most), ("Times", 3, None))
        self.assertEqual((b.mode, b.over.dotted, b.item, b.at_most), ("Over", "items", "item", 5))
        self.assertEqual((c.mode, c.at_most, c.at_cap), ("Until", 2, "Else_Exit"))
        self.assertEqual(c.until, s.Condition(s.KeyRef(["verdict", "ok"]), "==", "true", 0.8))
        self.assertEqual(c.body[0].questions[0].type, "true_or_false", "noul is an alias")
        self.assertEqual((e.at_most, e.collect), (4, s.Collect("out", "outs")), "commas between header clauses are optional")
        self.assertEqual(e.body[0].kind, "Task_Agent")


class Aliases(unittest.TestCase):
    def test_every_keyword_matches_in_any_case_and_alias(self):
        for canonical, aliases in ALIASES.items():
            for spelling in (canonical, canonical.lower(), canonical.upper(), *aliases):
                with self.subTest(spelling=spelling):
                    self.assertEqual(keyword(spelling), canonical)
        self.assertIsNone(keyword("message"))

    def test_aliases_in_a_program(self):
        p = parse("""
            PROCEDURE p "x"
            trigger_when "a"
            anti_pattern "b"
            start "s" { Input m: array "the list"  next a }
            decide a "d" {
              reads m
              questions { q: noul "Yes?"  c: choice [x, y] "Which?" }
              history true
              return dec
              go_to r
            }
            route on r "r" { input dec.c  when x -> e  y -> agg }
            aggregate agg "g" { read dec  aggregations { all: all dec.q w/ conf 0.5  none: none dec.c != x }  produces summary  next e }
            execute e "e" { read m  run scripts/x.py  command "python3 x.py"  asset assets/a.json "cfg"  output o: number  next t }
            agent_task t "t" { read o  template assets/p.md  reference references/r.md "when"  produce z: string  next end }
            end "e" { read z }
        """)
        self.assertEqual([h.keyword for h in p.header], ["Use_When", "Avoid"])
        start, a, r, agg, e, t, end = p.steps()
        self.assertEqual((start.inputs[0].type, start.flow.kind), ("list", "Next_Step"))
        self.assertEqual([q.type for q in a.questions], ["true_or_false", "choice"])
        self.assertTrue(a.flag("History"))
        self.assertEqual((a.produces[0].key.dotted, a.flow), ("dec", s.Flow("Next_Step", "r")))
        self.assertEqual((r.particle, [b.value for b in r.branches]), ("On", ["x", "y"]))
        self.assertEqual([(g.mode, g.condition.operator, g.condition.value, g.condition.confidence_above) for g in agg.aggregations],
                         [("All", None, None, 0.5), ("None", "!=", "x", None)])
        self.assertEqual((e.script, e.command.value, e.uses[0].description.value, e.produces[0].type),
                         ("scripts/x.py", "python3 x.py", "cfg", "float"))
        self.assertEqual((t.kind, t.prompt, t.uses[0].path), ("Task_Agent", "assets/p.md", "references/r.md"))
        self.assertEqual(end.reads[0].key.dotted, "z")

    def test_keywords_are_contextual(self):
        """A key may be called like a keyword (`task`, `history`): position decides."""
        p = parse("""
            Procedure p "x"
            Start "s" { task: string "t"  history: list "h"  Next_Step a }
            Task_Agent a "a" { Read task, history  Produce out: string
                                                           history: list "again"
                               Next_Step end }
            End "e" { Read out }
        """)
        start, a, _ = p.steps()
        self.assertEqual([i.key.dotted for i in start.inputs], ["task", "history"])
        self.assertEqual([r.key.dotted for r in a.reads], ["task", "history"])
        self.assertEqual([k.key.dotted for k in a.produces], ["out", "history"])


class Strings(unittest.TestCase):
    def test_interpolation_fields_with_positions(self):
        text = 'Procedure p "x"\nq = """\nDoes {work} follow {policy.text}?\n"""\n'
        p = parse(text)
        [ns] = p.items
        self.assertEqual([f.path for f in ns.text.fields], [["work"], ["policy", "text"]])
        self.assertEqual([(f.line, f.column) for f in ns.text.fields], [(3, 6), (3, 20)])
        self.assertEqual(ns.text.value, "\nDoes {work} follow {policy.text}?\n")
        one_line = parse('Procedure p "x"\nq = "a {b} c"\n').items[0]
        self.assertEqual((one_line.text.fields[0].line, one_line.text.fields[0].column), (2, 8))

    def test_escapes_and_multiline(self):
        p = parse('Procedure p "x"\na = "say \\"hi\\"\\nnow"\nb = """raw \\n "quoted" """\nc = "spans\n  lines"\n')
        a, b, c = p.items
        self.assertEqual(a.text.value, 'say "hi"\nnow')
        self.assertEqual(b.text.value, 'raw \\n "quoted" ')
        self.assertEqual(c.text.value, "spans\n  lines")
        self.assertEqual(a.text.raw, '"say \\"hi\\"\\nnow"', "the literal is kept as written")

    def test_description_may_be_a_name(self):
        p = parse('Procedure p "x"\nd = "the step"\nTask_Agent t d { Read x  Produce y: string  Next_Step end }\n')
        self.assertEqual(p.step("t").description, s.NameRef("d"))


class Comments(unittest.TestCase):
    def test_leading_trailing_and_end_comments(self):
        p = parse("""# file
# header

Procedure p "x"  # on the procedure line
  # above a header clause
  Use_When "a"  # after the string

# above the step
Start "s" {  # after the brace
  # above the input
  m: string "m"  # after the input

  Next_Step a  # after the flow
  # before the brace
}
Decide a "d" {
  Read m
  Answer_Questions {  # after questions
    # above q
    q: true_or_false "?"  # after q
      # above the criterion
      true: "yes"  # after the criterion
    # end of questions
  }
  Produce dec
  Next_Step end
}
End "e" { Read dec }
# the end
""")
        self.assertEqual(p.leading, ["# file", "# header", ""])
        self.assertEqual(p.description.trailing, "# on the procedure line", "the description shares the line, so the comment is its")
        [use_when] = p.header
        self.assertEqual((use_when.leading, use_when.strings[0].trailing), (["# above a header clause"], "# after the string"))
        start = p.items[0]
        self.assertEqual((start.leading, start.trailing), (["# above the step"], "# after the brace"))
        inp, flow = start.clauses
        self.assertEqual((inp.leading, inp.trailing), (["# above the input"], "# after the input"))
        self.assertEqual((flow.leading, flow.trailing), ([], "# after the flow"))
        self.assertEqual(start.end_comments, ["# before the brace"])
        questions = p.step("a").clauses[1]
        self.assertEqual(questions.trailing, "# after questions")
        [q] = questions.questions
        self.assertEqual((q.leading, q.trailing), (["# above q"], "# after q"))
        self.assertEqual((q.criteria[0].leading, q.criteria[0].trailing), (["# above the criterion"], "# after the criterion"))
        self.assertEqual(questions.end_comments, ["# end of questions"])
        self.assertEqual(p.end_comments, ["# the end"])
        self.assertEqual(parse(format_program(p)), p)

    def test_a_comment_in_an_odd_place_is_kept(self):
        p = parse('Procedure p "x"\nEnd "e" {\n  Read m\n  # odd\n  , n  # after n\n}\n')
        formatted = format_program(p)
        self.assertIn("End \"e\" {\n  Read m,\n       # odd\n       n  # after n\n}\n", formatted)
        self.assertEqual(parse(formatted), p)

    def test_procedure_line_comment(self):
        p = parse('Procedure p  # here\n  "x"\n')
        self.assertEqual(p.trailing, "# here")
        self.assertEqual(format_program(p), 'Procedure p  # here\n  "x"\n')


if __name__ == "__main__":
    unittest.main()
