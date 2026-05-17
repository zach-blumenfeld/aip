---
name: search-first
description: >
  Runbook for the search-first workflow — research existing npm/PyPI packages,
  MCP servers, available skills, and GitHub repos before writing custom code.
  Use when starting a new feature, adding a dependency or integration, creating
  a new utility or helper, or whenever the user asks "add X functionality" and
  you're about to write code. Catches reinvented-wheel work before it lands.
metadata:
  aip:
    spec: https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md
    schemaId: urn:uuid:8c4f7e3a-1b5d-4f8e-9a2c-6b3e5f7d8c9a
  origin: ECC
---

```yaml
purpose: >
  Research existing tools, libraries, MCP servers, and skills before writing
  custom code. Recommend reuse or extension wherever an existing solution
  fits; build only when nothing suitable exists.

trigger_when:
  - Starting a new feature that likely has existing solutions.
  - Adding a dependency or integration.
  - The user asks "add X functionality" and you're about to write code.
  - Before creating a new utility, helper, or abstraction.
  - When evaluating technology choices.
  - Planning architecture decisions.

scope_and_approval: |
  Default to read-only research: inspect the repo, package metadata, docs,
  and public examples before recommending a dependency or integration. Do
  not install packages, configure MCP servers, publish artifacts, open PRs,
  or make external write actions from this skill unless the user has
  explicitly approved that action in the current task.

  When a candidate requires credentials, paid services, network writes, or
  project-wide config changes, return a recommendation and approval
  checkpoint instead of applying it directly.

steps:
  - name: need-analysis
    description: Define what functionality is needed; identify language and framework constraints.
  - name: parallel-search
    description: Search npm/PyPI, MCP servers, available skills, and GitHub/web in parallel via a researcher subagent for non-trivial work.
    parallel: true
  - name: evaluate
    description: Score candidates on functionality, maintenance, community, docs, license, and transitive dependencies.
  - name: decide
    description: Choose Adopt as-is, Extend/Wrap, Compose, or Build Custom.
    one_of:
      - Adopt as-is
      - Extend / Wrap
      - Compose
      - Build Custom
  - name: approval-and-implement
    description: Present the recommendation (package/MCP/custom code) and apply only after explicit user approval.

decisions:
  - signal: Exact match, well-maintained, MIT/Apache license.
    action: Adopt — recommend the package and request approval before install or config changes.
  - signal: Partial match, good foundation.
    action: Extend — recommend the package plus a thin wrapper, then wait for approval before applying.
  - signal: Multiple weak matches.
    action: Compose — propose 2–3 small packages and the integration plan before installing anything.
  - signal: Nothing suitable found.
    action: Build — explain why custom code is warranted, then implement only within the approved task scope.

modes:
  - name: quick
    body: |
      Before writing a utility or adding functionality, mentally run through:

      0. Does this already exist in the repo? Search relevant modules/tests first.
      1. Is this a common problem? Search npm / PyPI.
      2. Is there an MCP for this? Check MCP configuration and search.
      3. Is there a skill for this? Check available skills.
      4. Is there a GitHub implementation/template? Run GitHub code search for
         maintained OSS before writing net-new code.
  - name: full
    body: |
      For non-trivial functionality, delegate to a research-focused subagent:

          Research existing tools for: [DESCRIPTION]
          Language/framework: [LANG]
          Constraints: [ANY]
          Search: npm/PyPI, MCP servers, skills, GitHub
          Return: structured comparison with recommendation.

search_shortcuts:
  - category: Development Tooling
    body: |
      - Linting → eslint, ruff, textlint, markdownlint
      - Formatting → prettier, black, gofmt
      - Testing → jest, pytest, go test
      - Pre-commit → husky, lint-staged, pre-commit
  - category: AI / LLM Integration
    body: |
      - Claude SDK → check for latest docs
      - Prompt management → check MCP servers
      - Document processing → unstructured, pdfplumber, mammoth
  - category: Data & APIs
    body: |
      - HTTP clients → httpx (Python), ky / got (Node)
      - Validation → zod (TS), pydantic (Python)
      - Database → check for MCP servers first
  - category: Content & Publishing
    body: |
      - Markdown processing → remark, unified, markdown-it
      - Image optimization → sharp, imagemin

integrations:
  - partner: planner agent
    body: |
      The planner should invoke researcher before Phase 1 (Architecture Review):
      - Researcher identifies available tools.
      - Planner incorporates them into the implementation plan.
      - Avoids "reinventing the wheel" in the plan.
  - partner: architect agent
    body: |
      The architect should consult researcher for:
      - Technology stack decisions.
      - Integration pattern discovery.
      - Existing reference architectures.
  - partner: iterative-retrieval skill
    body: |
      Combine for progressive discovery:
      - Cycle 1: Broad search (npm, PyPI, MCP).
      - Cycle 2: Evaluate top candidates in detail.
      - Cycle 3: Test compatibility with project constraints.

examples:
  - need: Check markdown files for broken links.
    search: npm "markdown dead link checker".
    found: textlint-rule-no-dead-link (score 9/10).
    action: Adopt — recommend `textlint-rule-no-dead-link` and ask before installing it.
    result: Zero custom code if approved, battle-tested solution.
  - need: Resilient HTTP client with retries and timeout handling.
    search: npm "http client retry", PyPI "httpx retry".
    found: got (Node) with retry plugin; httpx (Python) with built-in retry.
    action: Adopt — recommend `got` or `httpx` directly with retry config and ask before changing dependencies.
    result: Zero custom code if approved, production-proven libraries.
  - need: Validate project config files against a schema.
    search: npm "config linter schema", "json schema validator cli".
    found: ajv-cli (score 8/10).
    action: Adopt + Extend — recommend `ajv-cli` plus a project-specific schema, then wait for approval before install or write.
    result: 1 package + 1 schema file if approved, no custom validation logic.

anti_patterns:
  - Jumping to code — writing a utility without checking if one exists.
  - Ignoring MCP — not checking if an MCP server already provides the capability.
  - Over-customizing — wrapping a library so heavily it loses its benefits.
  - Dependency bloat — installing a massive package for one small feature.
```
