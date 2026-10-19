---
name: to-development-plan
description: Create implementation units, dependencies and verification mapping from current SDD and the approved design, then stop for a separate implementation prompt.
---
# to-development-plan

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) and [verification contract](../to-sdd-pipeline/references/verification-contract.md) before work. Resolve installed resources from this SKILL.md's real directory.

## Inputs

Required: current validated PRD, guardrails, journey, architecture, DoD/evals and QA under `docs/`. UI scope also needs screen map, wireframes, design brief, the approved integrated baseline and durable referenced prototype.

Pipeline mode also requires the validated context/terms bundle. Standalone, missing context files need not block when required SDD already supplies every relevant fact/term. Inspect README and current codebase evidence where useful.

After approval, architecture, DoD and QA must have been reconciled in that order. Prepared checks are sufficient for planning; completed implementation tests are not a prerequisite.

Read the [H1-H10 contract](../to-sdd-pipeline/references/heuristic-usability-review.md) for user-visible units, and [prototype promotion](references/prototype-promotion.md) only when presentation code will be reused.

## Output and ownership

Write only `docs/development-plan.md`. Own implementation strategy/units, dependency/build order, unit references/work/acceptance/verification, risk sequencing, handoff, cross-layer interfaces and bounded prototype-reuse mappings.

Do not redefine product behavior, journeys/screens, layouts/style, architecture, DoD gates or concrete QA checks. **Requirements, approved design and architecture determine the plan; QA adds verification steps.** This is SDD, not mandatory TDD.

## Workflow

Read the [security traceability contract](../to-sdd-pipeline/references/security-contract.md). Include control implementation, negative tests and applicable dependency/operational maintenance work in existing units, tracing every PRD security obligation to real QA IDs and the required security gate. Return `security_coverage`; unresolved security design goes to its owner first. Never silently remove security work to fit a revised design or imply that planning ran a scan.

1. Read current sources; classify context/terms as applied, reference-only, irrelevant or conflicting. Cite only relevant fragments and local implementation consequences; no copied personas, summaries or glossaries.
2. For UI scope, verify approved Baseline ID, candidate/version, target hash, frozen source hash/algorithm, approval receipt, scope and permitted variance. Stop before production-unit planning if approval is missing. Do not reinterpret or re-approve the design.
3. Verify architecture/DoD/QA match current sources and the applicable baseline. Changed approval/target/override invalidates affected units and authorization; return to the appropriate owner.
4. Inspect existing modules/files/routes/components/services/tests and dated observations; follow established architecture.
5. Apply the [unit execution contract](../to-sdd-pipeline/references/unit-execution-contract.md): review full construction/acceptance with later units absent; resolve cycles through source-backed splits/merges, assign integration owners, then number dependency order. Preserve every clause/check and reconciliation/authorization rule. Each unit finishes using itself and completed lower-numbered units; partial work is not completion.
   Allocate [lifecycle mechanisms](../to-sdd-pipeline/references/lifecycle-contract.md) and early feasibility prerequisites before dependent construction. Every required mechanism needs authorized production paths, construction owner/checks, interfaces and prerequisites. A qualification-only unit cannot supply omitted production work. This handoff does not authorize deployment.
6. Preserve applicable JOB → UC → task traces and heuristic/user-task verification through the shared verification contract, including nonvisual tasks. UI units also bind journey/screen/state, baseline/target/scope/variance and visual fidelity.
7. Reference gate definitions and concrete QA checks; bind all consumed QA sections, including shared scope/evidence conventions and terms they rely on, not later execution results. Return their `source_usage` and hashes/fragments. Never invent participants, findings or research outcomes. Pending execution stays not-run, not passed.
8. For independently developed or cross-layer units define interfaces produced/consumed, API/data-contract references, owner, compatibility and integration verification.
9. If prototype code exists, declare no reuse or the bounded promotion contract. Keep component/integration responsibilities and missing production capabilities explicit.
10. If implementation already began, inspect declared destinations and required promotion receipts/strategies. Report absence/mismatch for QA/DoD; never synthesize historical receipts.
11. Reconcile mechanism duties and unit prose with production paths, contribution IDs, typed `implements` links, [construction allocations](../to-sdd-pipeline/references/traceability-contract.md), and QA owners. Full acceptance coverage cannot conceal construction omissions. Preserve clauses/states, gate coverage and canonical terms; unresolved upstream mismatches return to their owner.
12. Use current unit records and [completion preservation](../to-sdd-pipeline/references/completion-preservation.md); version 1 is import-only. Return reviewed unit inputs and obligation/check mappings for pending edits; preserve completed IDs and route changed meanings to their owners. Unusable prior acceptance becomes explicit revalidation work, not an automatic code rewrite. Write only the plan and return provenance. New plans stop at `awaiting-implementation-prompt`; existing authorized documentation-only corrections follow the [correction contract](../to-sdd-pipeline/references/authorization-corrections.md). Other revisions retain the fresh-prompt gate. Do not write production code, run promotion or dispatch implementation.

Unresolved upstream decisions return to their owner first. Ask only for material non-inferable scope/risk changes; otherwise record the smallest reversible source-compatible seam.

## Artifact coverage

Required semantic sections: Source References; Implementation Strategy; Implementation Units; Dependency Order; Verification Plan; Out Of Scope; Open Questions. State the unit completion condition once in Implementation Strategy: a unit remains incomplete until its scoped work, integration, required checks and acceptance evidence meet the referenced DoD and QA requirements. Reference project `AGENTS.md` for execution behaviour; do not copy its continuation or pause policy. Record missing project instruction setup as a prerequisite before implementation, not a blocker to plan authoring. The plan owner must not create project instruction files.

Add Codebase Map, Visual/UX Verification, Risks/Sequencing or Prototype Promotion Plan only when applicable. The latter is required for traced reuse.

Each unit resolves:

- ID/scope/owner; mechanism and clause contributions; construction dependencies/checks; acceptance prerequisites; authorized production paths; integration ownership; work and evidence. Return canonical `unit_plan`, its architecture `construction_ref` and complete `construction` allocation, with typed traceability.
- Component/layer: use architecture-defined names, not a fixed web-layer taxonomy.
- For UI units: JOB/UC/journey/state, Baseline ID/target hash, scope, permitted variance/overrides and `approved_visual_baseline_fidelity`.
- Applicable `heuristic_usability_review`/H1-H10/QA IDs and `representative_user_task_validation` references follow shared scope rules for visual or nonvisual tasks.
- For nonvisual components: source-defined tasks and whether they enable user-visible states/data/actions.
- For parallel tasks inside the active unit: interfaces, exclusive write ownership, shared evidence reservations and coordinator integration. Later units remain sequential.
- Record actual worker assignments and progress in execution records; generic coordination rules belong in project `AGENTS.md`.
- For traced prototype reuse: the fields in the promotion reference.

Shared records may carry repeated scope/contract data if each unit's references resolve. Do not add a context field to every unit; use its existing Source References only where relevant.

## Return

Report file, changed/revalidated units, coverage/evidence limits, open questions and authorization disposition. A plan or design approval never authorizes Phase 3 on its own.
