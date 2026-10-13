---
name: to-dod-evals
description: Define reusable completion gates, evidence requirements, eval result formats and release/rerun rules from validated SDD, before concrete QA and development planning.
---
# to-dod-evals

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) and [verification contract](../to-sdd-pipeline/references/verification-contract.md) before work. Resolve installed resources from this SKILL.md's real directory.

## Inputs by phase

Required: PRD, guardrails, journey and architecture under `docs/`; UI scope also needs screen map, wireframes and design brief. Pipeline mode adds validated context/terms.

Optional grounding: README, authoritative product idea when named by the PRD, explicit decisions and current engineering or deployment evidence.

Consulted **later at evaluation**, not required for authoring: concrete QA check IDs/evidence and, after implementation begins, development-plan destinations/promotion receipts. Never add QA or the plan as a DoD creation dependency.

For user-visible scope read the [H1-H10 contract](../to-sdd-pipeline/references/heuristic-usability-review.md). Shared references are installed resources, not product-source documents.

## Output and ownership

Write only `docs/dod-evals.md`. Own the standing Definition of Done, acceptance and completion distinction, verification profile, gates, eval format, failures, evidence, rerun rules and source-backed delivery conditions.

Guardrails owns evidence policy; QA owns checks/results; authorized executors run checks. This skill **defines gates; it does not run them**. Create no product scope, architecture, checks, units or external effects.

## Workflow

Read the [security traceability contract](../to-sdd-pipeline/references/security-contract.md). Define required `product_security_requirements` for every PRD security obligation, with implementation evidence and failure/rerun rules. Exceptions return to the PRD. Reassess affected controls; return `security_coverage` and the gate's `security_requirement_ids`.

1. Extract source acceptance outcomes and architectural risks; inspect verification surfaces without running gates.
2. Separate mechanism construction, bounded contributions, device qualification and full integration/release acceptance. Construction needs its own checks; later qualification cannot supply missing construction. Define fresh evidence and no-open-blocker completion conditions. Component or mocked evidence cannot pass required real-consumer obligations; deferred integration retains an accountable owner.
3. Define source-supported profiles, evidence limits and release conditions. Never invent commands, CI, thresholds or merge policies. Required uncertain capabilities need source-defined feasibility evidence before dependent construction, or an explicit blocker.
4. Define `approved_visual_baseline_fidelity` for UI scope. Define `heuristic_usability_review` and `representative_user_task_validation` where source-backed task scope requires them, including nonvisual tasks under the shared verification contract. Never substitute evidence classes.
5. Leave UI baseline parameters pending before approval and check bindings pending before QA exists. Prepared does not mean executed or passed.
6. After approval, consume reconciled architecture and current baseline; revalidate affected definitions. The orchestrator indexes available parameters/QA IDs without making QA an authoring dependency.
7. Define engineering lane/state promotion gates only when sources establish such a workflow. Ordinary UI states do not create delivery gates.
8. Define provenance, failure and rerun rules through the [unit contract](../to-sdd-pipeline/references/unit-execution-contract.md). Changed-source or changed-plan reuse needs explicit reviewed revalidation of unchanged claims, unit records, and necessary owner/prerequisite sources. Preserve original observations/times; unresolved impact or affected claims need new evidence. Revalidation never renews authority.
9. Map each FR/NFR clause to an active applicable gate or blocker; inactive/excluded checks and parent IDs cannot supply coverage. Use the [lifecycle checklist](../to-sdd-pipeline/references/lifecycle-contract.md) for supported environments, retention, recovery, migration and feasibility. Define actual platform-policy qualification separately from simulated deletion recovery; unreproduced required conditions remain pending. Each check must bind back to its applicable gate.
10. Validate sources, ownership and evidence limits. Keep definitions `prepared`, execution separate, and unexecuted release readiness `not_evaluated`.

Define evidence for consequential decisions, preserved data and recovery. Add control, focus and long-content observations for applicable interfaces; a final screenshot cannot establish these outcomes.

## Artifact coverage

Required semantic sections: Source References; Definition Of Done Model; Verification Profile; Gate Matrix; Eval Result Format; Evidence Requirements; Failure And Blocker Classification; Completion And Delivery Rules; Out Of Scope; Open Questions. Include PR merge rules only when the project uses them.

Add feature/unit levels, promotions and recovery sections only where useful. Each gate resolves the shared verification fields and parameters; do not duplicate full criteria.

## Return

Report the file, prepared/revalidated gates, pending bindings, evidence limits and open blockers. Explicitly say tests were not run. Follow shared provenance and return to the orchestrator.
