---
name: to-qa-checklist
description: Prepare or reconcile source-backed acceptance, usability, accessibility, responsive and visual checks; record actual evidence separately from unexecuted test plans.
---
# to-qa-checklist

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) and [verification contract](../to-sdd-pipeline/references/verification-contract.md) before work. Resolve installed resources from this SKILL.md's real directory.

## Inputs by phase

Required: PRD, guardrails, journey, architecture and DoD/evals under `docs/`; UI scope also needs screen map, wireframes and design brief. Pipeline mode adds validated context/terms.

Optional grounding: README, source-backed environments, roles, locales and risks, current code, tests or runtime configuration. Read the [H1-H10 and recovery contract](../to-sdd-pipeline/references/heuristic-usability-review.md) for applicable human-task checks.

Consulted **later**, only when it exists and implementation began: `docs/development-plan.md` to locate declared destinations, interface seams and promotion receipts. It is never a QA-authoring prerequisite or source of QA rules.

## Output and ownership

Write only `docs/qa-checklist.md`. Own concrete acceptance, journey, state, usability, accessibility, device, regression and release checks, with per-check findings and evidence.

Guardrails owns evidence policy, DoD gates/release rules, architecture technical choices, and screen map states. Reference them; add no product requirements, design, architecture or implementation tasks.

## Preparing versus running

Default to **authoring checks**, not executing tests. New items are `Definition Status: prepared` / `Execution Status: not_run`; no invented evidence, finding, participant, timestamp or pass.

Project execution instructions govern agent behaviour while running checks. This document defines check actions, expected results, findings and evidence. Do not copy the execution continuation or pause policy here. Project `AGENTS.md` is not a prerequisite for authoring QA definitions.

Keep definitions and compact current results canonical here by check ID. Preserve detailed observations and superseded run history through verified evidence references. Read the [storage contract](../to-sdd-pipeline/references/evidence-storage-contract.md) when recording/resolving evidence. Inspect original executor/time, revision, scope, action name, observed state, fixture and result. Metadata corrections retain original bytes/times and correction history; storage migration never executes a check.
Writing the checklist never means the product is verified.

Planning output uses `Release Readiness: not_evaluated`. An explicitly requested release evaluation uses `passed | blocked` under the DoD rules. A required unrun/deferred check cannot pass.

## Workflow

Read the [security traceability contract](../to-sdd-pipeline/references/security-contract.md). Define allowed and denied/adversarial checks for each PRD security obligation at its real enforcement seam. Bind `product_security_requirements`; return `security_coverage` and per-check `security_requirement_ids`. Simulation cannot verify production controls; authoring runs no tests or scanners.

1. Inspect current sources and recheck any repository observations; source truth defines behavior, not discovered implementation drift.
2. For UI scope, use proposed visual expectations with `Binding Status: pending_baseline` before approval. After architecture/DoD reconciliation, bind the active Baseline ID, immutable target hash and permitted variance.
3. Map each requirement clause, journey and state to stable checks or blockers. Use the [coverage review](../to-sdd-pipeline/references/acceptance-coverage-review.md) when preparing or reconciling checks. Separate scenarios when their claims, failure diagnosis or rerun conditions differ; parent IDs are insufficient.
4. Separate bounded mechanism construction checks from native/device qualification and full integration/release checks. Use architecture's mechanism duties, owned interfaces and declared success/failure outcomes; later qualification cannot hide missing construction checks.
5. Resolve H1-H10 and user-task scope/evidence through the shared verification contract for applicable UI or nonvisual tasks; include supported input modes, errors/recovery and accessible critical actions.
6. H7: source-backed novice flow and applicable shortcuts, bulk/repeated work and customization using supported input modes/platforms. H10: contextual help, searchable docs when needed, actionable empty states, inline instructions and recovery links.
7. Specify each applicable failure sequence: cause → preserved work → required action or recovery trigger → observable completion. Exercise specified recovery controls or observe the defined automatic/external transition and its result. Cover retained candidates, changed decisions, Cancel, pending recovery records and other live pages where the PRD requires them.
8. Give applicable critical/consequential flows separate representative-user checks with the shared task/group/success/timing fields. Expert or visual evidence cannot substitute for participants.
9. Cover applicable states, repeated actions and realistic maximum content. For supported focus-based navigation, observe focus and the next destination after navigation or control changes. Check recovery access in long or maximum-content views through each supported input mode; screenshots alone are insufficient.
10. Cite architecture/DoD gates and guardrail policy. Inventory necessary claim-relevant sources with honest owner/prerequisite closure when allocated, never to avoid reruns. Name actual consumers; retain full integration/release checks. Return acceptance through the [unit contract](../to-sdd-pipeline/references/unit-execution-contract.md); planning assigns units. For current unit records, read [completion preservation](../to-sdd-pipeline/references/completion-preservation.md): distinguish original execution from current applicability, preserve actual results, and return exact reviewed check inputs including shared definitions. Missing, failed, stale or deferred results never pass completion.
11. After implementation begins, inspect declared prototype-promotion receipts when applicable; absent/mismatched receipts block fidelity. Never fabricate a receipt or make the plan an upstream dependency.
12. Validate coverage and boundaries; write only the checklist and return its hash-bound check/gate index to the caller.

Changed baselines, targets, overrides or obligations invalidate affected results. Reuse unchanged check/unit claims only through explicit reviewed revalidation under the unit contract. Preserve original evidence/times, required source closure and blockers; never renew authority. Participant reruns depend on changed tasks, consequences, copy, presentation or population.

## Source-overridable UI defaults

Apply [platform-appropriate accessibility](../to-sdd-pipeline/references/accessibility-policy.md). Web UI uses 320 CSS px reflow and text/viewport zoom; compare 390/430/768/1280/1440px unless sources differ. Web house defaults: 44×44px targets, 8px separation, 16px mobile inputs, 14–16px body, no emoji-as-icons. These do not replace WCAG criteria/exceptions. Native UI uses platform guidance. Check supported input modes, focus, motion, contrast and assistive technology.

Use [lifecycle guidance](../to-sdd-pipeline/references/lifecycle-contract.md) for source-defined operations and early feasibility. Bind supported environments, versions and use modes. Where persistence/recovery applies, cover its platform limits and required outcomes. Actual platform qualification differs from simulated recovery; unreproduced required conditions stay pending.

## Artifact coverage

Required sections: Source References; Execution Status; Product Acceptance; Evidence Requirements; Evidence Limits; Release Readiness; Open Questions. For UI scope add Screen And State Checks, Heuristic Usability Checks and UX/UI Checks. Include Usability Validation Checks when applicable.

Resolve shared verification fields through scope IDs where useful. Keep findings, severity, release effect and recommendation unassessed until actual findings exist.

## Return

Report the file, checks prepared, actual execution status, supplied/observed evidence, pending bindings, limitations and open blockers. Follow shared provenance. State “checks prepared; tests not run” when only authoring occurred; no extra approval.
