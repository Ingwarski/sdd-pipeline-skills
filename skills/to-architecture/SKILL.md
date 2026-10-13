---
name: to-architecture
description: Define or reconcile system architecture, module/data boundaries, integrations, runtime configuration and technical risks from the current SDD sources.
---
# to-architecture

Read [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve installed resources from this SKILL.md's real directory.

## Inputs

Required: PRD, guardrails and journey under `docs/`; UI scope also needs screen map, wireframes and design brief. Pipeline mode adds validated context/terms.

Optional grounding: README, explicit decisions, authoritative product idea when named by the PRD, and current code/routes/schemas/config/tests/build/deployment evidence. Inspect secret names, never expose secret values.

The design brief may be proposed during initial authoring. After whole-design approval or a baseline revision, recheck architecture against the exact approved baseline before DoD, QA and planning continue. This is technical reconciliation, not design approval.

Read the [security traceability contract](../to-sdd-pipeline/references/security-contract.md). Map every PRD security obligation to concrete enforcement, data/trust boundaries, configuration or operational ownership; frontend visibility alone is not enforcement. Name unresolved technical control decisions without claiming a scan or certification.

## Output and ownership

Write only `docs/architecture.md`. Own system context, module/service boundaries, data/state ownership, integrations, runtime/automation, source-backed stack constraints, configuration/bindings/build outputs, security/privacy/access, performance/reliability/observability, decisions and risks.

Map applicable `UC-*` behavior to technical boundaries without rewriting it. Do not add requirements, journeys, screens/states, layouts/style, DoD gates, QA items or implementation units.

## Workflow

1. Read source drivers and inspect the current codebase. Separate observed implementation facts from proposed decisions; return dated, path-scoped observations.
2. Map each applicable UC and each distinct FR/NFR obligation to a realizing module, interface, data or runtime element.
3. Define context, boundaries, state/data ownership, integrations and runtime. At consequential storage/session/file seams, specify inputs, outputs, result/error codes, resource owner and producer/consumer; include success, cancellation, stale-state, unavailable-capability and failure examples where applicable. Classify hidden recovery records and pending work in decision bindings, not only visible counts.
4. For each deployable unit, specify required environment variables, bindings, secret **names**, build outputs and hosting/runtime constraints supported by sources.
   Resolve applicable [lifecycle concerns](../to-sdd-pipeline/references/lifecycle-contract.md), including exact qualification profiles, platform retention and required early feasibility evidence. Record the bounded non-production experiment, owner and unmet condition before dependent construction; keep design prototypes within simulation scope.
5. Preserve established architecture; choose the simplest reversible PRD-compatible mechanism. Do not force a stack, service, cost model or feature.
6. Record important decisions, alternatives/rejection reasons, consequences and follow-up. Preserve decision history.
7. Add a readable Mermaid diagram only when it clarifies relationships.
8. On approved-baseline reconciliation, inspect changed interaction/state/data, integration and runtime consequences. Update only affected decisions, or return a fresh no-change validation with the new baseline/source hashes.
9. Validate clause/configuration coverage. Record mechanism duties, production paths and interface/verification seams through the [construction projection](../to-sdd-pipeline/references/traceability-contract.md), including lifecycle mechanisms tested later. Architecture names no future units/check IDs. Unmapped duties or unresolved qualification conditions remain open; a missing value blocks its dependent claim.
10. Write only architecture and return provenance.

PRD/journey own behavior; the approved baseline owns presentation/interaction detail; confirmed code owns existing facts. Static design never proves runtime completion. Browse only when a named current external dependency/standard needs verification, not for an unsolicited “latest stack”.

## Artifact coverage

Required semantic sections: Source References; Architecture Overview; Architecture Principles; Module And Boundary Map; Data And State Model; Integration Map; Configuration And Binding Contract; Architecture Decision Log; Risks And Mitigations; Out Of Scope; Open Questions.

Add runtime/automation, security/access, performance/observability, stack constraints and a diagram where relevant. Each important decision resolves source, alternatives, rationale, consequences and open follow-up.

## Return

Report file, changed or revalidated decisions, clause/configuration coverage, observations, baseline binding when applicable, unresolved risks and `security_coverage`. No commits, README edits or repository synchronization inside this owner.
