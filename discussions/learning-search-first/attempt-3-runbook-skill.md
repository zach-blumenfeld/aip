---
name: search-first
description: Search for existing tools, libraries, MCPs, and skills before writing custom code. Trigger when starting a new feature, adding a dependency, or before creating a utility. Score candidates and decide adopt / extend / compose / build. Default read-only — install / config / external-write needs explicit approval.
---

```yaml
trigger:
  - Starting a new feature that likely has existing solutions
  - Adding a dependency or integration
  - User asks "add X functionality" and you're about to write code
  - Before creating a new utility, helper, or abstraction

scope: >-
  Default to read-only research: inspect the repo, package metadata, docs,
  and public examples before recommending. Do not install packages,
  configure MCP servers, publish artifacts, open PRs, or make external
  write actions unless explicitly approved. Candidates requiring
  credentials, paid services, network writes, or project-wide config
  changes get a recommendation + approval checkpoint, not direct action.

steps:
  - id: need-analysis
    do: Define what functionality is needed; identify language/framework constraints.
  - id: parallel-search
    do: Search in parallel across registries, MCP/skills, and code hosting.
    parallel:
      - npm / PyPI
      - MCP servers / installed skills
      - GitHub / web code search
  - id: evaluate
    do: Score candidates on functionality, maintenance, community, docs, license, deps.
  - id: decide
    do: Pick a disposition based on the decisions table.
    one_of: [adopt-as-is, extend-or-wrap, compose, build-custom]
  - id: approval-checkpoint
    do: Recommend package / MCP / custom code; apply only after explicit approval.

decisions:
  - when: Exact match, well-maintained, MIT/Apache
    then: Adopt — recommend the package; request approval before install or config.
  - when: Partial match, good foundation
    then: Extend — recommend the package + a thin wrapper; wait for approval.
  - when: Multiple weak matches
    then: Compose — propose 2–3 small packages and an integration plan.
  - when: Nothing suitable found
    then: Build — explain why custom code is warranted; implement within approved scope.

modes:
  quick: |
    Inline mental checklist before writing a utility:
    0. Does this already exist in the repo? Search relevant modules/tests.
    1. Is this a common problem? Search npm/PyPI.
    2. Is there an MCP for this? Check MCP config.
    3. Is there a skill for this? Check available skills.
    4. Is there a GitHub implementation/template? Run code search.
  full: |
    Delegate to a research-focused subagent:
      "Research existing tools for: [DESCRIPTION]
       Language/framework: [LANG]
       Constraints: [ANY]
       Search: npm/PyPI, MCP, skills, GitHub
       Return: structured comparison with recommendation"

shortcuts: |
  Development Tooling
    Linting     → eslint, ruff, textlint, markdownlint
    Formatting  → prettier, black, gofmt
    Testing     → jest, pytest, go test
    Pre-commit  → husky, lint-staged, pre-commit
  AI / LLM
    Claude SDK          → check latest Anthropic SDK docs
    Prompt management   → check MCP servers
    Document processing → unstructured, pdfplumber, mammoth
  Data & APIs
    HTTP clients → httpx (Python), ky / got (Node)
    Validation   → zod (TS), pydantic (Python)
    Database     → check MCP servers first
  Content & Publishing
    Markdown processing → remark, unified, markdown-it
    Image optimization  → sharp, imagemin

integrations:
  planner: >-
    Invoke researcher before Phase 1 (Architecture Review) so identified
    tools land in the plan instead of being reinvented.
  architect: >-
    Consult researcher for technology stack decisions, integration patterns,
    and reference architectures.
  iterative-retrieval: >-
    Cycle 1 broad search → cycle 2 evaluate top candidates →
    cycle 3 compatibility check with project constraints.

examples:
  - need: Check markdown files for broken links
    found: textlint-rule-no-dead-link (9/10)
    action: Adopt; ask before installing.
  - need: Resilient HTTP client with retries and timeout handling
    found: got (Node) with retry plugin; httpx (Python) built-in retry
    action: Adopt directly with retry config; ask before changing deps.
  - need: Validate project config files against a schema
    found: ajv-cli (8/10)
    action: Adopt + extend with project-specific schema; ask before install/write.

anti_patterns:
  - Jumping to code — writing a utility without checking if one exists
  - Ignoring MCP — not checking if an MCP server already provides the capability
  - Over-customizing — wrapping a library so heavily it loses its benefits
  - Dependency bloat — installing a massive package for one small feature
```
