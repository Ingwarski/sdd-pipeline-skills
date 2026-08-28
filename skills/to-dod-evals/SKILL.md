---
name: to-dod-evals
description: Define reusable completion gates, evidence requirements, eval result formats and release/rerun rules from validated SDD, before concrete QA and development planning.
---
# to-dod-evals

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) and [verification contract](../to-sdd-pipeline/references/verification-contract.md) before work. Resolve links from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs by phase

Required before authoring: PRD, guardrails, user journey, screen map, wireframes, design brief and architecture under `docs/`; in pipeline mode also the validated context/terms bundle.

Optional grounding: README, authoritative product idea when named by the PRD, explicit decisions and current package/test/CI/build/lint/typecheck/deployment evidence.

Consulted **later at evaluation**, not required for authoring: concrete QA check IDs/evidence and, after implementation begins, development-plan destinations/promotion receipts. Never add QA or the plan as a DoD creation dependency.

For user-visible scope read the [H1-H10 contract](../to-sdd-pipeline/references/heuristic-usability-review.md). Shared references are installed resources, not product-source documents.

## Output and ownership

Write only `docs/dod-evals.md`. Own the standing Definition of Done, acceptance-vs-completion distinction, verification profile, reusable gates/eval format, failure classification, evidence needed for completion, rerun/recovery and source-backed PR/merge/release rules.

Guardrails owns evidence policy; QA owns concrete checks and per-check results; authorized reviewers/runners execute checks. This skill **defines gates; it does not run them**. Do not create scope, architecture, UX decisions, checklist details, implementation units, issues or automation.

## Workflow

Read the [security traceability contract](../to-sdd-pipeline/references/security-contract.md). Define the required `product_security_requirements` gate for all PRD security obligations, with implementation evidence, failure and rerun rules. Source-confirmed exceptions must be resolved in the PRD, not silently downgraded by a gate. Reassess affected controls after security-relevant changes; return `security_coverage` and the gate's `security_requirement_ids`.

1. Extract source acceptance outcomes and architecture-driven verification concerns; inspect existing executable verification surfaces without running gates.
2. Separate acceptance criteria (specific expected behavior), standing DoD (finished-quality bar), concrete QA checks and implementation tasks.
3. Define only source-supported profile tiers: hard gates, unit/system checks, UX/UI, evidence limits and release checks. Do not invent CI, tests, commands, comparison thresholds or merge policies.
4. For UI scope define separate parameterized gates: `approved_visual_baseline_fidelity`, `heuristic_usability_review`, and applicable `representative_user_task_validation`. Use the shared verification contract; never substitute one evidence class for another.
5. Before approval, leave baseline parameters pending. Before QA exists, leave concrete check bindings pending. A prepared gate is not executed or passed.
6. After approval, consume the reconciled architecture and current baseline, revalidate affected gate definitions and bind available baseline parameters. The orchestrator later indexes real QA IDs; this does not require reading QA back into the definition.
7. Define engineering lane/state promotion gates only when sources establish such a workflow. Ordinary UI states do not create delivery gates.
8. Specify result/evidence/executor/timestamp/revision, failure classification and rerun rules. An inactive gate cannot remain load-bearing in requirement mappings.
9. Map every distinct FR/NFR obligation to an active gate or explicit blocker. Parent-ID coverage is insufficient; unavailable comparison values remain named blockers.
10. Validate source grounding, ownership and evidence limits; write only the DoD artifact. Keep `Definition Status: prepared` separate from any execution result.

Completion claims require fresh executed evidence. A mockup, static surface, plan or screenshot is not proof of real functionality, WCAG/security/compliance, heuristic coverage or user validation.

## Artifact coverage

Required semantic sections: Source References; Definition Of Done Model; Verification Profile; Gate Matrix; Eval Result Format; Evidence Requirements; Failure And Blocker Classification; PR Merge And Completion Rules; Out Of Scope; Open Questions.

Add feature/unit levels, lane promotions, evidence limits and rerun/recovery sections only where useful. Every gate includes ID/purpose/source/applicability, evidence, pass/block condition, rerun rule and automation status. Shared gate-specific parameter fields are defined once in the verification reference; resolve them without duplicating full criteria.

## Return

Report the file, prepared/revalidated gates, pending bindings, evidence limits and open blockers. Explicitly say tests were not run. Follow shared provenance and return to the orchestrator. [Authoring provenance](../to-sdd-pipeline/references/authoring-sources.md) is historical, not a mandatory input.
