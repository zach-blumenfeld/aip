# Why the language has no logical expressions

Decided 2026-11-06, after designing them in some detail. This page exists so that when the
topic comes back, and it will, the reasoning is here and not re-derived.

## What was proposed

A small expression grammar inside routes and gates: `==`, `!=`, `&&`, `||`, `any()`,
`all()`, `none()` over answers, with a confidence qualifier per atom (`x.tone == angry With
Confidence 0.8`). The confidence of an atom would come from the answer's probabilities, so
`tone != angry` would be `1 − P(angry)`, and compounds would use three-valued logic so that no
joint confidence was ever computed: an atom below its bar is unknown, and unknown propagates
like SQL null.

It is a tidy design. Every piece of it is computable from what the decision model already
returns. That is not the problem.

## Why not

The problem is what a reader believes when they see it.

`all(policy_check) With Confidence 0.8` reads as "the work passed every policy, with 80%
confidence". It is not that. It is "each answer, taken alone, had at least 80% on it". The
confidence of the conjunction is somewhere between 0.8 (if the answers are perfectly
correlated) and 0.8 to the power of the number of answers (if independent), and it is lower
still if the answers are correlated the wrong way. The language would be putting a number
next to a compound while the number belongs to the parts, and a reader in a governance
setting will take the number at face value.

The 2016 United States election forecasts are the standard example. State polls were modelled
as independent; they were not, because the polling error was shared across states. The
aggregate confidence was far higher than the evidence supported, and the people reading it had
no way to see that from the number. Answers from one model about one piece of work are the
same shape: one model, one input, one systematic error, and the errors on "no personal data"
and "plain tone" are not independent draws.

Three-valued logic does not fix this. It avoids computing a joint number, but the expression
still presents a compound verdict next to a threshold, and the implied joint confidence is
still read off it. The trap is in the syntax, not in the arithmetic.

There is also the ordinary reason: once there are expressions, `>=` on scores, arithmetic and
functions follow, and the language stops being a thing a compiler can check completely and a
governance reader can read in full.

## What the language does instead

- A `Route` branches on **one** value and checks **one** confidence. A procedure that needs
  two conditions writes two routes, and a reader sees two decisions with two confidences.
- Anything that combines answers is an `Execute` step with a script. The script's output is a
  plain `boolean` with **no confidence**, and the language cannot attach one to it. The
  combination is visible in the source, it is attributed to a script in the record, and it never
  claims a certainty it does not have.
- The record keeps every answer's confidence and probabilities, so governance can ask the
  question per answer, which is the only level at which the number means something.

## The line

The rule to apply when this comes back: **the language never produces a confidence from more
than one answer.** A confidence belongs to one answer from one model. Anything derived from
several answers is a boolean, and the derivation is a script.

An `Aggregate` step that resolves each `true_or_false` answer against its own bar and then
combines the resulting booleans with `All`, `Any` or `None` into an answer that carries **no
confidence** stays on the right side of this line, and is what replaced the AND script in the
policy examples. An expression language does not stay on the right side, and that is the whole
reason.
