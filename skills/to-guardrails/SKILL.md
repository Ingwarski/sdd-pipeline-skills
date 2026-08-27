---
name: to-guardrails
description: Define SDD source authority, autonomy, scope, conflict handling, stop conditions and evidence policy after the PRD.
---
# to-guardrails

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve the link from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs

Required before starting: `docs/prd.md`; in pipeline mode also the validated `docs/project-context.md` and `docs/canonical-terms.md` bundle.

Optional grounding: README, explicit user decisions, relevant confirmed context/terms, and `docs/product-idea.md` only when the PRD names it as authoritative or the user requests it.

Read [verification boundaries](../to-sdd-pipeline/references/verification-contract.md) and, for user-visible scope, the [heuristic contract](../to-sdd-pipeline/references/heuristic-usability-review.md). These are installed skill resources, not project prerequisites.

Never import downstream UX, architecture, DoD, QA or planning decisions into guardrails.

## Output and ownership

Write only `docs/guardrails.md`. Own source priority, AI autonomy, allowed/forbidden changes, scope, conflict resolution, questions/stops, artifact separation and behavioral evidence policy.

DoD owns reusable completion gates; QA owns concrete checks/results. Do not write journeys, screens, layouts, visual direction, gate definitions, QA items or implementation tasks.

## Workflow

1. Identify authoritative inputs and stakes: hobby/internal, consumer/paid, or regulated/accessibility-critical/sensitive-data.
2. Assign authority by concern: PRD/journey for behavior; the approved integrated baseline for presentation/interaction detail; architecture, guardrails and applicable standards for technical and risk boundaries.
3. Allow reversible, source-grounded work within intent. Keep one whole-design approval and just-in-time authorization for irreversible, destructive, financial, legal, public, privileged, security/privacy-sensitive or external effects.
4. Define conflict routing to the owner and when a material non-inferable answer is needed. Do not interview about discoverable facts or every user-facing edit.
5. Distinguish representative-user validation, H1-H10 review, visual/browser observations, accessibility checks and functional/runtime evidence. None substitutes for another; no fabricated sessions, findings, results or compliance claims.
6. Require fresh verification before completion claims: identify evidence, run the authorized check, read its output, then report the supported result. A mockup/static surface does not prove real data, actions, persistence or integrations.
7. Classify unavailable sources. Missing material scope/compliance/high-risk evidence blocks the affected claim. A merely aesthetic reference permits a disclosed source-grounded fallback; an executor's explicitly required source-access gate still applies.
8. Validate source coverage, ownership and open risks; write only the owned artifact.

Re-run only when a named upstream decision or consumed source fragment changes a rule or authority boundary. Later files appearing is not a rerun trigger.

## Artifact coverage

Required semantic sections: Source References; Source Of Truth Order; AI Autonomy Boundaries; Forbidden Changes; When To Ask; When To Stop; Artifact Separation Rules; Verification Rules; Open Questions.

Add Allowed Changes, Scope Boundaries, Design Authority, Conflict Resolution, Evidence Requirements or Source Access Failures only when they add decisions. Cite shared evidence definitions; do not copy them.

## Return

Report the file, changed rules, validation evidence, open risks and next owner. Follow the shared provenance contract; playback and document validation are not approvals.
