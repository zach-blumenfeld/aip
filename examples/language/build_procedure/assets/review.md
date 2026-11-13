# Review the procedure

The procedure at `{path}` (relative to the working directory) compiles. Its files, by their path
in the folder:

{contents}

Read its `procedure.aip` and every one of its scripts once more against the rules it was built
from:

{rules}

It was tried once on example inputs, answering nothing and running none of its scripts (they
were written by a model and nobody has read them yet):

{test_report}

Say, in a few short lines: which rules it covers and where; which it does not, or covers only
partly; and anything a person should check before it is published. If it has a `Decide`,
say that it runs only where a decision model is configured (`aip config` shows whether one is). Then, under a line
`Scripts:`, one line per script: what it does, and what it touches outside the working directory
(services and URLs it calls, files it reads or writes elsewhere, commands it runs) and which
credentials it uses (tokens, logins, keys, environment variables), or that it touches nothing
outside; say which scripts are stubs that must be connected to a real system. Change nothing.

Answer with `review`: those lines as one string.
