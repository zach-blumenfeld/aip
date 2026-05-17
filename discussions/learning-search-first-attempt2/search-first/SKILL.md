---
name: search-first
description: >
  Research-before-coding workflow. Search for existing tools, libraries,
  MCPs, and patterns before writing custom code. Use at the start of a
  new feature, before adding a dependency, or before creating a utility.
metadata:
  origin: ECC
  aip:
    spec: https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md
    schemaId: urn:uuid:94bc0f33-c889-4364-b986-7d31763e56cc
---

```yaml
schemaId: urn:uuid:94bc0f33-c889-4364-b986-7d31763e56cc
title: Research Before You Code

triggers:
  - Starting a new feature that likely has existing solutions.
  - Adding a dependency or integration.
  - User asks "add X functionality" and an agent is about to write code.
  - Before creating a new utility, helper, or abstraction.
  - Evaluating technology stack or architecture decisions.

scope_and_approval: |
  Default to read-only research: inspect the repo, package metadata, docs,
  and public examples before recommending a dependency or integration. Do
  not install packages, configure MCP servers, publish artifacts, open
  PRs, or make external write actions from this workflow unless the user
  has explicitly approved that action in the current task.

  When a candidate requires credentials, paid services, network writes, or
  project-wide config changes, return a recommendation and approval
  checkpoint instead of applying it directly.

workflow:
  phases:
    - phase_id: need_analysis
      name: Need analysis
      activity: >
        Define what functionality is needed; identify language and
        framework constraints.
    - phase_id: parallel_search
      name: Parallel search
      activity: >
        Search npm / PyPI, available MCP servers and skills, and GitHub /
        web in parallel (delegate to a researcher subagent for non-trivial
        scope).
    - phase_id: evaluate
      name: Evaluate
      activity: >
        Score candidates on functionality fit, maintenance health,
        community signals, docs quality, license, and dependency weight.
    - phase_id: decide
      name: Decide
      activity: >
        Pick an action class from the decision matrix: adopt as-is, extend
        / wrap, compose multiple, or build custom.
    - phase_id: approval_and_implement
      name: Approval checkpoint and implement
      activity: >
        Recommend the package / MCP / custom code path. Apply only after
        explicit user approval; otherwise return the recommendation and
        wait.

decisions:
  - signal: Exact match, well-maintained, MIT/Apache license.
    action: adopt
    guidance: >
      Recommend the package and request approval before install or any
      config changes.
  - signal: Partial match with a good foundation.
    action: extend
    guidance: >
      Recommend the package plus a thin wrapper; wait for approval before
      applying the wrapper or installing.
  - signal: Multiple weak matches, none ideal alone.
    action: compose
    guidance: >
      Propose two or three small packages and the integration plan; wait
      for approval before installing anything.
  - signal: Nothing suitable found after a thorough search.
    action: build
    guidance: >
      Explain why custom code is warranted; implement only within the
      approved task scope.

modes:
  quick:
    description: >
      Inline mental checklist to run through before writing a utility or
      adding functionality.
    checks:
      - Does this already exist in the repo? Search relevant modules and tests first.
      - Is this a common problem? Search npm / PyPI.
      - Is there an MCP for this? Check MCP configuration and search.
      - Is there a skill for this? Check available skills.
      - Is there a maintained GitHub implementation or template? Run a code search before writing net-new code.
  full:
    description: >
      For non-trivial functionality, delegate to a research-focused
      subagent using the template below.
    subagent_prompt_template: |
      Research existing tools for: [DESCRIPTION]
      Language/framework: [LANG]
      Constraints: [ANY]

      Search: npm/PyPI, MCP servers, skills, GitHub
      Return: Structured comparison with recommendation

shortcuts: |
  Development tooling
    - Linting        → eslint, ruff, textlint, markdownlint
    - Formatting     → prettier, black, gofmt
    - Testing        → jest, pytest, go test
    - Pre-commit     → husky, lint-staged, pre-commit

  AI / LLM integration
    - Claude SDK         → check for latest docs
    - Prompt management  → check MCP servers
    - Document processing → unstructured, pdfplumber, mammoth

  Data and APIs
    - HTTP clients → httpx (Python), ky / got (Node)
    - Validation   → zod (TS), pydantic (Python)
    - Database     → check for MCP servers first

  Content and publishing
    - Markdown processing → remark, unified, markdown-it
    - Image optimization  → sharp, imagemin

integration_points: |
  With the planner agent
    Invoke researcher before Phase 1 (Architecture Review). The
    researcher identifies available tools; the planner incorporates them
    into the implementation plan. Avoids "reinventing the wheel" in the
    plan itself.

  With the architect agent
    Consult researcher for technology stack decisions, integration
    pattern discovery, and existing reference architectures.

  With the iterative-retrieval skill
    Combine for progressive discovery —
      Cycle 1: broad search (npm, PyPI, MCP)
      Cycle 2: evaluate top candidates in detail
      Cycle 3: test compatibility with project constraints

examples:
  - need: Check markdown files for broken links.
    search: npm "markdown dead link checker"
    found: "textlint-rule-no-dead-link (score 9/10)"
    action: >
      ADOPT — recommend textlint-rule-no-dead-link and ask before
      installing it.
    result: Zero custom code if approved; battle-tested solution.
  - need: Resilient HTTP client with retries and timeout handling.
    search: npm "http client retry"; PyPI "httpx retry"
    found: "got (Node) with retry plugin; httpx (Python) with built-in retry."
    action: >
      ADOPT — recommend got / httpx directly with retry config and ask
      before changing dependencies.
    result: Zero custom code if approved; production-proven libraries.
  - need: Validate project config files against a schema.
    search: npm "config linter schema"; "json schema validator cli"
    found: "ajv-cli (score 8/10)"
    action: >
      ADOPT + EXTEND — recommend ajv-cli plus a project-specific schema,
      then wait for approval before install / write.
    result: One package plus one schema file if approved; no custom validation logic.

anti_patterns:
  - Jumping to code — writing a utility without checking whether one exists.
  - Ignoring MCP — not checking whether an MCP server already provides the capability.
  - Over-customizing — wrapping a library so heavily it loses its benefits.
  - Dependency bloat — installing a massive package for one small feature.
```
