# AIP runtime — format 0.4a0

You are executing an (Agent Instruction Protocol) AIP procedure: the fenced YAML block in this skill's `SKILL.md`. AIP is a protocol for cheaply, quickly, and accurately executing multi-step tasks using a graph-based workflow. AIP is portable, so while designed for execution with an AIP client and server, you, the agent can play both roles instead. 

## Running

If the `aip` command is available (`aip --help` succeeds), use it: run `aip run <this skill's folder> --input <start.json>` with the start step's inputs as JSON. When the run needs you it prints a JSON pause and exits with code 3. `paused` says why: `decision` — answer the listed questions; `review` — confirm or override the flagged answers; `client_task` — do the task and produce the keys in `expects`. Put your answer in a JSON file and run the `resume` command the pause printed. Repeat until the output has `"done": true`; `state` is the result. If `aip` is not available, execute the procedure yourself, following the semantics below.

Critical terminology:

- **Client**: whoever drives the run: posts each step's input, reviews uncertain decisions, performs client tasks, and makes the final call at every step. As a plain Agent Skill, it is the agent that activated the skill.
- **Server**: runs each step and validates its input against the step's `inputs`. Without one, the activating agent does this itself: runs scripts, answers decision questions by its own judgment, and follows routers.
- **State**: the JSON object a step receives. Each step declares its required keys as `inputs`; extra keys pass through.
- **Step kinds**: `execution` runs a script, `decision` asks typed questions about the state, `client_task` hands work to the client, `router` branches on a value in the state, `end` declares the final state's shape.

## Execution

The state is one JSON object. It starts as the start step's `inputs` and flows along `inputs_to`; each step's output is merged over it, so keys accumulate and extra keys pass through untouched. A step runs only if the state holds every key it declares in `inputs`, with the declared types. The client may change the state before any step runs; it has the final say at every step.

- **`execution`**: run `script` with one JSON object on stdin, `{"currentState": <state>, "assets": {<file stem>: <content>}, "expects": <the next step's inputs>}`. The script writes one JSON object to stdout; it is merged over the state.
- **`decision`**: answer each question against the state. Each answer collapses to one value under its question name and is merged over the state: a noul to `true`/`false`, a choice to its label, a score to its level number. With a decision model, an answer under its threshold is sent to the client to confirm or override before continuing; without one, the client answers the questions.
- **`client_task`**: render `template` with `{key}` from the state, `{assets[stem]}` for its assets, and `{meta.name}` for the skill name. The client performs the task, loading `references` if their descriptions apply, and returns the next step's `inputs`; they are merged over the state.
- **`router`**: read the state's `branch_on` key and continue at `branches[value]`. A value with no branch is an error.
- **`end`**: the state must hold `end`'s `inputs`. That state is the procedure's result.
