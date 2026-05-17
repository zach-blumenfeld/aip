2. chose a very specific custom schema: search-first.schema.json.  Would have been better to generalize a bit more to something like runbook. 
2. asking user to validate proposed schema structure can be tough.  They aren't experts.  Ask if they would like to see schema or iuf you should just go forward before presenting
3. dont start by creating diectly in the .claude/skills folcder.  draft in some other temp location and get permission from user in install step to move over or put in a root directory first. 
4. schemaId in both frontmatter and yaml is redundent.  Remove from yaml
5. make sure to remove any vendor specific references in aip SKILL.md - this could be used by codex, cursor, etc. 
6. \#2 under friction and gaps from agent feedbsck below - we haven't considered usage of ./references, /.assets, ./scripts directories yet, may complicate things a bit. 


Feedback from Claude-code:
❯ any feedback to provide to the AIP dev?  He is actiuvily soliciting feedback on your usage experience and wants       
  candid feedback                                                                                                       
  
⏺ Candid feedback from this compile. Anchored to what I actually hit, ranked by what I'd act on first.

  What worked well

  - uv run scripts — zero install friction, first-time-correct. Don't change this.
  - Selective-typing heuristic ("would the agent for over this?") plus the worked example with attempt-3 numbers — this
  was the single most useful piece of guidance in the skill. It gave me a defensible answer for every section.
  - Honest compression caveat. The skill warns "tight source can compile larger than its source"; I got −10.8% bytes /
  −6.4% tokens — modest, exactly as predicted. The warning prevented me from over-promising the user. Most spec docs
  would have led with the 40–60% number and let me look bad.
  - The 4 always-confirm checkpoints felt right — not too many, and description deserves its own gate.

  Friction & gaps

  1. Schema discovery is mostly aspirational in v0.1. The skill walks the user through a 3-source discovery flow, then
  notes parenthetically that references/examples/ "may be empty." With no bundled examples and (for a fresh user) no
  installed Instructions, every Scenario-1 user is silently Scenario 3. The flow should either ship a starter set
  (workflow, runbook, deliberation) or be honest up-front: "you'll almost certainly draft a custom schema; here's the
  template."
  2. The skill's own SKILL.md is huge. It dumped what I'd estimate as ~3-4k tokens into context just to start. For a
  skill whose whole point is compression, that's an awkward look. A lot of it is conditional guidance (Scenario 3
  details, anti-patterns, source/README content rules) that could live in references/ and load on demand.
  3. metadata.aip.spec points at main with no version pin. Every Instruction in the wild now references a moving target.
   The spec acknowledges this; it's still a problem the day after a breaking spec change.
  4. Reserved property names ambush. I almost used id as a phase identifier. The validator would have caught it, but I'd
   already drafted the schema. Worth surfacing more loudly in the schema-authoring guidance — maybe a "common gotchas"
  callout: id reserved → use <domain>_id.
  5. Double schemaId declaration (frontmatter + body top-level, both required to match) is genuinely confusing. The spec
   justifies it (self-description after extraction), but it's the most likely place a human-edited Instruction breaks.
  Could the validator at least auto-inject the body one from the frontmatter on validate.py --fix?
  6. Strict-core enforced at root only. validate_schema.py enforces additionalProperties: false on the root schema, but
  not on $defs entries or nested objects. I set it on my nested objects defensively; an author who didn't would still
  pass validation, then get surprised by silent drift later. Either enforce everywhere or document the asymmetry.
  7. No aip.tag vocabulary guidance. I picked "workflow". Could have picked "research", "workflow-discipline", anything.
   With no controlled vocabulary (even a soft one), aip.tag is useless for cross-corpus discovery — which the spec lists
   as a per-corpus benefit.

  Things I'd flag for the spec itself

  - Selective-typing principle is the load-bearing idea in the whole protocol. Right now it's documented in the skill's
  SKILL.md, not the spec. If a different team writes an AIP skill, they may miss this entirely and ship Instructions
  that compile larger than source. Promote it into spec.md as a first-class authoring principle, not just a
  reference-skill UX note.
  - Self-description URL points at 1265 lines of markdown. If an AIP-unaware agent actually fetched metadata.aip.spec,
  parsing the spec to understand the protocol is non-trivial. A machine-readable companion (JSON Schema for the protocol
   itself, or a short "minimum agent contract" doc) would make self-description meaningfully actionable rather than
  aspirational.
  - The body's ASCII workflow diagram (one of the most information-dense parts of the source) was unrecoverable in
  compilation. It became a typed phases[] array — agent-queryable, but a human reading the body has to mentally
  reconstruct the visual flow. The "freeform |-block for tight structure" guidance is correct, but |-blocks don't render
   diagrams readably either. There's no great answer for visual structure today.
  
  One thing I'd change about the walkthrough

  When the user picked Balanced mode, the spec told me to "ask 3–5 structural choices." I collapsed them into one
  combined question (selective-typing table + naming + redundancy merge). That worked, but the skill didn't tell me it
  was OK to combine — strict reading says I should fire 3-5 separate questions. Worth adding: "combine into one
  preview-style question if the choices are interdependent."

