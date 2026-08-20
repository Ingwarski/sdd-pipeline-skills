---
name: to-architecture
description: Use when the current PRD, guardrails, and UX/design SDD chain exists and the user wants architecture.md, technical architecture, system architecture, module map, integration map, data/state model, runtime model, architectural decisions, risks, or architecture source-of-truth before DoD/evals, QA, or implementation planning.
---
# to-architecture

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit request, otherwise use the language of the latest substantive user message. Use it for all questions, playbacks, reports, and natural-language headings and prose in the owned artifact. English template headings are semantic labels, not literal output. For Ukrainian (`uk`), write idiomatic Ukrainian and keep English only in immutable filenames/paths, code/commands, machine values, API/identifier names, names/quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary English prose or calques. Keep explicit product content locales separate from the specification language.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/architecture.md`, every load-bearing architecture decision must be source-backed, user-confirmed, codebase-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized architecture decisions not fully determined by source files or existing code, play back the resolved decisions in a pithy summary and continue with the simplest reversible architecture that satisfies the sources unless the missing answer materially changes product scope or a high-risk boundary. Playback is not an approval gate; architecture does not create a pre-prototype design gate.

Never write a repository-state observation as a bare fact. Record `<claim> — observed <ISO date> via <command>` plus the exact observed paths and content hashes in the orchestrator's scoped repository observation. Never assert that something does not exist without naming the command that would prove it still does not.

## Input
Read:
- `README.md`, if present
- `docs/prd.md`
- `docs/project-context.md`, when present or supplied by `to-sdd-pipeline`
- `docs/canonical-terms.md`, when present or supplied by `to-sdd-pipeline`
- `docs/guardrails.md`
- `docs/user-journey.md`
- `docs/screen-map.md`
- `docs/wireframes.md`
- `docs/design-brief.md`
- `docs/product-idea.md`, only if `docs/prd.md` explicitly names it as an authoritative source or the user asks to use it

Use confirmed relevant platform/runtime/deployment constraints, roles, external dependencies, operational risks, and canonical vocabulary from the context bundle. Do not copy descriptive context, promote assumptions to architecture facts, add product scope, or let either file override PRD behavior. Record only the exact sections or terms consumed when pipeline provenance is requested.

Inspect the codebase structure when implementation will happen in an existing project. Existing code, package manifests, routes, schemas, environment files, and config files can confirm architecture facts; they do not authorize new product scope.

## Output
Create or update exactly one artifact:
- `docs/architecture.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/architecture.md` owns:
- system architecture overview
- architecture principles and constraints
- module, service, route, and boundary map
- data and state model
- integration map
- runtime and automation model
- technology stack constraints when source-backed or codebase-confirmed
- required runtime configuration: environment variables, platform bindings, secrets by name, and required build outputs
- security, privacy, reliability, performance, and observability architecture concerns
- architecture decision log with alternatives and consequences
- architecture risks and mitigations

It must not define:
- new product requirements
- user journey content
- screen inventory or state list
- wireframe layouts
- visual design direction
- Definition of Done, eval gates, or QA checklist items
- implementation units or task breakdown

Later artifacts may reference this file, but they must not duplicate its content.

## Proven Mechanics To Use
Adapt the useful parts of proven architecture/documentation skills without importing their bad fit:
- From `tad-generator`: extract PRD context first; clarify architecture only when source data is insufficient; cover system overview, architecture diagram, technology stack, system components, data architecture, infrastructure/runtime, security, performance/reliability, development constraints, and risks; validate that the diagram and sections are complete before reporting success.
- From `documentation-and-adrs`: document why, not only what; capture significant decisions, alternatives considered, rejection reasons, and consequences; preserve decision history instead of silently rewriting it.
- From `breakdown-epic-arch`: use a high-level architecture diagram and identify technical enablers, but do not hard-code any stack or epic path.
- From durable architecture-doc patterns: make the document useful for future agents so they do not re-derive architecture every session.
- From SDD guardrails: PRD and journey artifacts own product behavior; the engineer-approved integrated prototype owns visual composition, interaction detail, and frontend presentation; confirmed code owns existing implementation facts; architecture owns technical boundaries. Unapproved mockups, assistant preference, and generic stack defaults override none of them.
- Static design artifacts can inform UI architecture boundaries, but they cannot prove runtime behavior, real state/data/actions, or completed functionality.

Do not copy these source skills wholesale:
- Do not write `tad.md`; write `docs/architecture.md`.
- Do not commit, push, update README indexes, or perform repo sync from inside the skill.
- Do not force startup cost estimates, specific hosted infrastructure, React/Next/tRPC, Docker, PostgreSQL, Redis, or any stack choice unless sources or code confirm them.
- Do not browse for "latest best stack" unless a named external platform, standard, or package version is required and likely current.

## Authoring References Used
These references were used to design this skill. They are not product source files for a project run; product truth still comes only from the Input files and explicit user answers.

- `tad-generator`: `https://github.com/luongnv89/skills/blob/main/skills/tad-generator/SKILL.md`
  - Used: PRD extraction, architecture clarification, system overview, Mermaid diagram, stack/components/data/infrastructure/security/performance/risk coverage, artifact acceptance checks.
  - Not used: `tad.md` output path, automatic git sync/commit/push, README index updates, startup cost defaults, and forced stack assumptions.
- `documentation-and-adrs`: `https://github.com/addyosmani/agent-skills/blob/main/skills/documentation-and-adrs/SKILL.md`
  - Used: document why, alternatives considered, decision consequences, ADR-style decision log.
  - Not used: separate ADR file workflow under `docs/decisions/`, because this skill creates one artifact only.
- `breakdown-epic-arch`: `https://github.com/github/awesome-copilot/blob/main/skills/breakdown-epic-arch/SKILL.md`
  - Used: high-level architecture specification shape, Mermaid architecture diagram, technical enabler thinking.
  - Not used: hard-coded TypeScript/Next.js/tRPC/Turborepo/Docker/Stack Auth assumptions and epic-specific output path.
- `eatmycode`: `https://github.com/xwings/eatmycode`
  - Used: durable architecture documentation as a future-agent alignment surface.
  - Not used: multi-file `ARCHITECTURE.md` plus `ARCHITECTURE/<module>.md` structure, because this pipeline uses one output artifact per skill.
- Existing local SDD skills in this repository:
  - `skills/to-guardrails/SKILL.md`
  - `skills/to-development-plan/SKILL.md`
  - Used: Universal SDD Rule, one-artifact output contract, artifact boundary format, source-backed/open-question behavior, and Final Report shape.

## Gap-Check
Before writing, verify that sources or code identify:
- product scope and architectural drivers
- target platform and runtime environment
- major modules, surfaces, services, or subsystems
- data/state objects and ownership
- external integrations and boundaries
- authentication, authorization, privacy, and security needs, if relevant
- performance, reliability, offline, observability, or scalability needs, if relevant
- deployment, hosting, repository, or automation constraints, if relevant
- architecture decisions that are already settled versus open
- required environment variables, platform bindings, secrets by name, and build outputs for each deployable unit

If stack, runtime, data ownership, integrations, security boundaries, or deployment constraints are missing, ask only when the unresolved answer materially changes product scope or a high-risk boundary. Otherwise choose or defer the simplest reversible source-compatible architecture, record the open decision and migration seam, and continue.

Ask architecture questions with recommended answers based on sources. Prefer:
- preserving existing codebase architecture
- using the simplest architecture that satisfies the PRD
- deferring unconfirmed infrastructure decisions to `Open Questions`
- using explicit interface boundaries before inventing services

## Workflow
1. Inspect the input files.
2. Inspect codebase structure when a codebase exists: package manifests, app routes, source directories, schemas, configs, tests, build scripts, and environment examples.
3. Extract architecture drivers from source artifacts: scope, users, screens, states, integrations, data, automation, constraints, and non-goals.
4. Identify existing architecture facts separately from proposed architecture decisions.
5. Define system context and module boundaries without adding product scope.
6. Define data/state ownership and flow.
7. Define integration and runtime/automation boundaries.
8. Define technology constraints only where source-backed or codebase-confirmed.
9. Capture important decisions with alternatives and consequences.
10. Include an architecture diagram when it clarifies the system. Use Mermaid and keep it readable.
11. Before writing the artifact, verify the planned content:
   - Every load-bearing architecture decision traces to a named source file, codebase evidence, or an explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
   - The architecture does not invent product scope, screens, features, or implementation tasks.
   - Clause-level coverage: for every FR and NFR, enumerate its distinct obligations and name the architecture element that realizes each one. An obligation with no named element goes to `Open Questions`; an ID appearing in a traceability table is not coverage of that ID's clauses.
   - A deferred numeric, catalog value, or threshold that a DoD gate must compare against is recorded as a named blocker for that gate, not only as an open question. Deferral is legitimate; an unmeasurable gate is not.
12. Create or update only `docs/architecture.md`.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Architecture Overview`, `Architecture Principles`, `Module And Boundary Map`, `Data And State Model`, `Integration Map`, `Configuration And Binding Contract`, `Architecture Decision Log`, `Risks And Mitigations`, `Out Of Scope`, and `Open Questions`. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. List omitted optional sections in the Final Report.

```markdown
# Architecture

## Source References

## Architecture Overview

## Architecture Principles

## System Context

## Module And Boundary Map

## Runtime And Automation Model

## Data And State Model

## Integration Map

## Technology Stack And Constraints

## Configuration And Binding Contract

## Security Privacy And Access Model

## Performance Reliability And Observability

## Architecture Diagram

## Architecture Decision Log

## Risks And Mitigations

## Out Of Scope

## Open Questions
```

For each important architecture decision include:
- `Decision`
- `Source References`
- `Alternatives Considered`
- `Why This Direction`
- `Consequences`
- `Open Follow-Up`, if any

## Final Report
Return:
- `Result`
- `Created/Updated File`
- `Confirmed Architecture Facts And Constraints`
- `Omitted Optional Sections`, if any
- `Open Questions`
- `Next Recommended Action`
- `Next Recommended Skill`
