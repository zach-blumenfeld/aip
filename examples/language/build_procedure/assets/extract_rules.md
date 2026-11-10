# Extract the rules

The brief for the procedure:

{brief}

What the documents say:

{notes}

What the person has answered so far (empty before the first round of questions):

{answers}

Write the rules the procedure will follow, as a short list: each decision it makes, who makes it
(a script for anything exact such as a limit or a lookup, the agent for judgement and writing, a
person where the brief or the documents say a person decides), on what, and what follows from
each outcome; and what the procedure returns. Take the brief and the person's answers as given;
take the documents where they speak; invent nothing.

Then list what is still open: only questions whose answer changes what the procedure does (a
threshold nobody named, who handles a case, what happens on a branch the brief does not cover).
Do not ask about wording, style or anything you can decide sensibly yourself. When the answers
so far settle everything, the list is empty.

Answer with `rules` (a string), `questions` (a list of strings, empty when nothing is open) and
`settled` (true exactly when `questions` is empty).
