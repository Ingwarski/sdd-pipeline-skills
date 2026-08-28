---
name: to-development-plan
description: Create implementation units, dependencies and verification mapping from current SDD and the approved design, then stop for a separate implementation prompt.
---
# to-development-plan

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) and [verification contract](../to-sdd-pipeline/references/verification-contract.md) before work. Resolve links from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs

Required before starting: current validated PRD, guardrails, journey, screen map, wireframes, design brief, architecture, DoD/evals and QA checklist under `docs/`. For a UI product, require the engineer-approved integrated baseline and durable referenced prototype.

Pipeline mode also requires the validated context/terms bundle. Standalone, missing context files need not block when required SDD already supplies every relevant fact/term. Inspect README and current codebase evidence where useful.

After approval, architecture, DoD and QA must have been reconciled in that order. Prepared checks are sufficient for planning; completed implementation tests are not a prerequisite.

Read the [H1-H10 contract](../to-sdd-pipeline/references/heuristic-usability-review.md) for user-visible units, and [prototype promotion](references/prototype-promotion.md) only when presentation code will be reused.

## Output and ownership

Write only `docs/development-plan.md`. Own implementation strategy/units, dependency/build order, unit references/work/acceptance/verification, risk sequencing, handoff, cross-layer interfaces and bounded prototype-reuse mappings.

Do not redefine product behavior, journeys/screens, layouts/style, architecture, DoD gates or concrete QA checks. **Requirements, approved design and architecture determine the plan; QA adds verification steps.** This is SDD, not mandatory TDD.

## Workflow

Read the [security traceability contract](../to-sdd-pipeline/references/security-contract.md). Include control implementation, negative tests and applicable dependency/operational maintenance work in existing units, tracing every PRD security obligation to real QA IDs and the required security gate. Return `security_coverage`; unresolved security design goes to its owner first. Never silently remove security work to fit a revised design or imply that planning ran a scan.

1. Read current sources; classify context/terms as applied, reference-only, irrelevant or conflicting. Cite only relevant fragments and local implementation consequences; no copied personas, summaries or glossaries.
2. Verify the approved Baseline ID, candidate/version, target hash, frozen source hash/algorithm, approval receipt, scope and permitted variance. For UI scope, stop before production-unit planning if approval is missing. Do not reinterpret or re-approve the design.
3. Verify architecture/DoD/QA are current for that baseline. Changed approval/target/override invalidates affected units and authorization; return to the appropriate owner.
4. Inspect existing modules/files/routes/components/services/tests and dated observations; follow established architecture.
5. Split source-backed scope into useful units with clear ownership, dependencies, acceptance checks and evidence. Sequence by dependencies, risk and user value, not tiny commit choreography.
6. For each user-visible unit preserve JOB → UC → journey → screen/state trace and bind baseline/target/scope/variance, visual fidelity, applicable H1-H10/QA IDs and representative-user task validation.
7. Reference gate definitions and concrete QA checks; snapshot the consumed QA definition sections, not later execution results. Never invent participants, findings or research outcomes. Pending execution stays not-run, not passed.
8. For independently developed or cross-layer units define interfaces produced/consumed, API/data-contract references, owner, compatibility and integration verification.
9. If prototype code exists, declare no reuse or the bounded promotion contract. Keep frontend/backend/integration responsibilities and missing production capabilities explicit.
10. If implementation already began, inspect declared destinations and required promotion receipts/strategies. Report absence/mismatch for QA/DoD; never synthesize historical receipts.
11. Map every distinct PRD obligation and screen/state to a unit or explicit exclusion/open question. Verify architecture constraints, gate coverage, interface producer/consumer pairs and canonical terms.
12. Write only the plan, return provenance and stop at `awaiting-implementation-prompt`. Do not write production code, run promotion or dispatch implementation.

Unresolved upstream decisions return to their owner first. Ask only for material non-inferable scope/risk changes; otherwise record the smallest reversible source-compatible seam.

## Artifact coverage

Required semantic sections: Source References; Implementation Strategy; Implementation Units; Dependency Order; Verification Plan; Out Of Scope; Open Questions.

Add Codebase Map, Visual/UX Verification, Risks/Sequencing or Prototype Promotion Plan only when applicable. The latter is required for traced reuse.

Each unit resolves:

- ID/purpose; source obligations; dependencies; work items; acceptance and verification.
- Delivery layer: frontend, backend, full-stack, integration or infrastructure.
- For user-visible units: JOB/UC/journey/state, Baseline ID/target hash, scope, permitted variance/overrides, `approved_visual_baseline_fidelity`, applicable `heuristic_usability_review`/H1-H10/QA IDs and `representative_user_task_validation` task/success/evidence references.
- For backend-only units: whether it enables user-visible states/data/actions.
- For cross-layer/parallel units: interface producer/consumer, contract, owner, compatibility and integration checks.
- For traced prototype reuse: the fields in the promotion reference.

Shared records may carry repeated scope/contract data if each unit's references resolve. Do not add a context field to every unit; use its existing Source References only where relevant.

## Return

Report file, changed/revalidated units, coverage/evidence limits, open questions and the separate implementation prompt as next action. A plan or design approval never authorizes Phase 3 on its own.
