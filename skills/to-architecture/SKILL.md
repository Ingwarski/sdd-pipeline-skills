---
name: to-architecture
description: Define or reconcile system architecture, module/data boundaries, integrations, runtime configuration and technical risks from the current SDD sources.
---
# to-architecture

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve the link from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs

Required before starting: `docs/prd.md`, `docs/guardrails.md`, `docs/user-journey.md`, `docs/screen-map.md`, `docs/wireframes.md`, `docs/design-brief.md`; in pipeline mode also the validated context/terms bundle.

Optional grounding: README, explicit decisions, authoritative product idea when named by the PRD, and current code/routes/schemas/config/tests/build/deployment evidence. Inspect secret names, never expose secret values.

The design brief may be proposed during initial authoring. After whole-design approval or a baseline revision, recheck architecture against the exact approved baseline before DoD, QA and planning continue. This is technical reconciliation, not design approval.

## Output and ownership

Write only `docs/architecture.md`. Own system context, module/service boundaries, data/state ownership, integrations, runtime/automation, source-backed stack constraints, configuration/bindings/build outputs, security/privacy/access, performance/reliability/observability, decisions and risks.

Map applicable `UC-*` behavior to technical boundaries without rewriting it. Do not add requirements, journeys, screens/states, layouts/style, DoD gates, QA items or implementation units.

## Workflow

1. Read source drivers and inspect the current codebase. Separate observed implementation facts from proposed decisions; return dated, path-scoped observations.
2. Map each applicable UC and each distinct FR/NFR obligation to a realizing module, interface, data or runtime element.
3. Define system context, module boundaries, data/state flow and ownership, integrations and runtime/automation.
4. For each deployable unit, specify required environment variables, bindings, secret **names**, build outputs and hosting/runtime constraints supported by sources.
5. Preserve established architecture; choose the simplest reversible design that satisfies the PRD. Name interfaces before inventing services. Do not force a stack, infrastructure, startup cost model or new feature.
6. Record important decisions, alternatives/rejection reasons, consequences and follow-up. Preserve decision history.
7. Add a readable Mermaid diagram only when it clarifies relationships.
8. On approved-baseline reconciliation, inspect changed interaction/state/data, integration and runtime consequences. Update only affected decisions, or return a fresh no-change validation with the new baseline/source hashes.
9. Validate obligation coverage and configuration completeness. Unmapped obligations remain open; a deferred threshold/catalog value needed by a future gate is a named blocker for that gate.
10. Write only architecture and return provenance.

PRD/journey own behavior; the approved baseline owns presentation/interaction detail; confirmed code owns existing facts. Static design never proves runtime completion. Browse only when a named current external dependency/standard needs verification, not for an unsolicited “latest stack”.

## Artifact coverage

Required semantic sections: Source References; Architecture Overview; Architecture Principles; Module And Boundary Map; Data And State Model; Integration Map; Configuration And Binding Contract; Architecture Decision Log; Risks And Mitigations; Out Of Scope; Open Questions.

Add runtime/automation, security/access, performance/observability, stack constraints and a diagram where relevant. Each important decision resolves source, alternatives, rationale, consequences and open follow-up.

## Return

Report file, changed or revalidated decisions, clause/configuration coverage, observations, baseline binding when applicable, and unresolved risks. No commits, README edits or repository synchronization inside this owner. [Authoring provenance](../to-sdd-pipeline/references/authoring-sources.md) is optional historical background, not a runtime input.
