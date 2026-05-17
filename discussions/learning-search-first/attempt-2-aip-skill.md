---
name: search-first
description: Research-before-coding runbook. Before writing a utility or adding functionality, search npm/PyPI, MCP servers, and existing skills; score candidates and decide adopt / extend / compose / build. Use when starting a new feature, adding a dependency, or before creating a helper or wrapper. Default posture is read-only — install/config writes require explicit approval.
metadata:
  aip:
    spec: https://raw.githubusercontent.com/zach-blumenfeld/aip/main/spec.md
    schemaId: urn:uuid:11f269a1-5611-4e2c-abee-6c4f97d163cf
  origin: ECC
---

```yaml
schemaId: urn:uuid:11f269a1-5611-4e2c-abee-6c4f97d163cf
title: search-first
summary: >-
  Research-before-coding runbook. Before writing custom code, search the
  repo, package registries, MCP servers, installed skills, and GitHub for
  existing solutions; evaluate; then adopt, extend, compose, or build.

trigger:
  - Starting a new feature that likely has existing solutions.
  - Adding a dependency or integration.
  - The user asks "add X functionality" and the agent is about to write code.
  - Before creating a new utility, helper, or abstraction.

scope:
  default: >-
    Read-only research: inspect the repo, package metadata, docs, and public
    examples before recommending a dependency or integration.
  approvalRequired:
    - Installing packages.
    - Configuring MCP servers.
    - Publishing artifacts or opening PRs.
    - Any external write action.
    - Candidates that require credentials, paid services, network writes,
      or project-wide config changes — return a recommendation and
      approval checkpoint instead of applying directly.

phases:
  - name: need-analysis
    description: >-
      Define what functionality is needed; identify language, framework, and
      project constraints that narrow the candidate set.
  - name: parallel-search
    description: >-
      Search across registries, MCP / skills, and code hosting in parallel.
      For non-trivial scope, delegate this phase to a researcher subagent.
    substeps:
      - Search npm / PyPI for matching packages.
      - Check MCP server configuration and installed skills.
      - Run GitHub / web code search for maintained OSS implementations
        and templates.
  - name: evaluate
    description: >-
      Score candidates on functionality match, maintenance signal, community
      size, documentation quality, license compatibility, and dependency
      footprint.
  - name: decide
    description: >-
      Pick the disposition that fits the strongest candidate.
    substeps:
      - Adopt the package as-is.
      - Extend or wrap the package with a thin adapter.
      - Compose 2-3 small packages.
      - Build custom only when nothing fits.
  - name: approval-checkpoint-and-implement
    description: >-
      Recommend the package, MCP, or custom code with rationale. Apply only
      after the user explicitly approves the install, config, or write.

decisionMatrix:
  - signal: Exact match, well-maintained, MIT/Apache license.
    action: >-
      Adopt — recommend the package and request approval before install or
      config changes.
  - signal: Partial match, good foundation.
    action: >-
      Extend — recommend the package plus a thin wrapper, then wait for
      approval before applying.
  - signal: Multiple weak matches.
    action: >-
      Compose — propose 2-3 small packages and an integration plan before
      installing anything.
  - signal: Nothing suitable found.
    action: >-
      Build — explain why custom code is warranted, then implement only
      within the approved task scope.

modes:
  - name: quick
    whenToUse: >-
      Inline, before writing a utility or adding small functionality. A
      mental checklist; no subagent.
    steps:
      - Does this already exist in the repo? Search relevant modules and
        tests first.
      - Is this a common problem? Search npm / PyPI.
      - Is there an MCP server for this? Check MCP configuration and
        search.
      - Is there an installed skill for this? Check available skills.
      - Is there a GitHub implementation or template? Run GitHub code
        search for maintained OSS before writing net-new code.
  - name: full
    whenToUse: >-
      Non-trivial functionality where structured comparison is worth the
      round-trip cost. Delegate to a research-focused subagent.
    delegateTo: researcher subagent
    steps:
      - >-
        Invoke the researcher subagent with: description of the need,
        language / framework, and any constraints.
      - Ask the subagent to search npm / PyPI, MCP servers, installed
        skills, and GitHub.
      - Request a structured comparison with a recommendation.

shortcuts:
  - category: Development Tooling
    items:
      - need: Linting
        candidates: [eslint, ruff, textlint, markdownlint]
      - need: Formatting
        candidates: [prettier, black, gofmt]
      - need: Testing
        candidates: [jest, pytest, go test]
      - need: Pre-commit
        candidates: [husky, lint-staged, pre-commit]
  - category: AI / LLM Integration
    items:
      - need: Claude SDK
        candidates: [check for latest Anthropic SDK docs]
      - need: Prompt management
        candidates: [check MCP servers]
      - need: Document processing
        candidates: [unstructured, pdfplumber, mammoth]
  - category: Data & APIs
    items:
      - need: HTTP clients
        candidates: [httpx (Python), ky (Node), got (Node)]
      - need: Validation
        candidates: [zod (TypeScript), pydantic (Python)]
      - need: Database
        candidates: [check for MCP servers first]
  - category: Content & Publishing
    items:
      - need: Markdown processing
        candidates: [remark, unified, markdown-it]
      - need: Image optimization
        candidates: [sharp, imagemin]

integrations:
  - with: planner agent
    howToCombine: >-
      The planner should invoke the researcher before Phase 1
      (Architecture Review), so identified tools are incorporated into
      the implementation plan rather than reinvented in it.
  - with: architect agent
    howToCombine: >-
      Consult the researcher for technology-stack decisions, integration
      pattern discovery, and existing reference architectures.
  - with: iterative-retrieval skill
    howToCombine: >-
      Combine for progressive discovery: cycle 1 broad search across
      registries / MCP / skills, cycle 2 deep evaluation of top
      candidates, cycle 3 compatibility check against project
      constraints.

examples:
  - name: Add dead-link checking
    need: Check markdown files for broken links.
    search: npm search for "markdown dead link checker".
    found: textlint-rule-no-dead-link (score 9/10).
    action: >-
      Adopt — recommend textlint-rule-no-dead-link and ask before
      installing it.
    result: Zero custom code if approved; battle-tested solution.
  - name: Add HTTP client wrapper
    need: Resilient HTTP client with retries and timeout handling.
    search: npm "http client retry"; PyPI "httpx retry".
    found: got (Node) with retry plugin; httpx (Python) with built-in retry.
    action: >-
      Adopt — recommend got / httpx directly with retry config and ask
      before changing dependencies.
    result: Zero custom code if approved; production-proven libraries.
  - name: Add config-file linter
    need: Validate project config files against a schema.
    search: npm "config linter schema"; "json schema validator cli".
    found: ajv-cli (score 8/10).
    action: >-
      Adopt + Extend — recommend ajv-cli plus a project-specific schema,
      then wait for approval before install or write.
    result: One package plus one schema file if approved; no custom
      validation logic.

antiPatterns:
  - name: Jumping to code
    description: Writing a utility without checking whether one already exists.
  - name: Ignoring MCP
    description: >-
      Not checking whether an MCP server already provides the capability.
  - name: Over-customizing
    description: Wrapping a library so heavily it loses its benefits.
  - name: Dependency bloat
    description: Installing a massive package for one small feature.
```
