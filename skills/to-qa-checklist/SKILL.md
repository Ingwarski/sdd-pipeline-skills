---
name: to-qa-checklist
description: Prepare or reconcile source-backed acceptance, usability, accessibility, responsive and visual checks; record actual evidence separately from unexecuted test plans.
---
# to-qa-checklist

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) and [verification contract](../to-sdd-pipeline/references/verification-contract.md) before work. Resolve links from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs by phase

Required before authoring: PRD, guardrails, journey, screen map, wireframes, design brief, architecture and DoD/evals under `docs/`; in pipeline mode also the validated context/terms bundle.

Optional grounding: README, source-backed devices/locales/roles/risks and current code/test/build/CI/runtime configuration to identify executable checks. Read the [H1-H10 and recovery contract](../to-sdd-pipeline/references/heuristic-usability-review.md) for applicable UI checks.

Consulted **later**, only when it exists and implementation began: `docs/development-plan.md` to locate declared destinations, interface seams and promotion receipts. It is never a QA-authoring prerequisite or source of QA rules.

## Output and ownership

Write only `docs/qa-checklist.md`. Own concrete acceptance/journey/state, heuristic/user-validation, UX/UI, responsive/accessibility, browser/device, regression and release checks, with per-check findings/evidence.

Guardrails owns evidence policy; DoD owns reusable gate definitions, result formats and release rules; architecture owns technical choices; the screen map owns the state list. Reference them without redefining them. Do not add requirements, journeys, screens, layouts, visual direction, architecture or implementation tasks.

## Preparing versus running

Default to **authoring checks**, not executing tests. New items are `Definition Status: prepared` / `Execution Status: not_run`; no invented evidence, finding, participant, timestamp or pass.

Keep stable check definitions separate from execution results/run history within this same file, joined by check ID. Record executed results only from inspected supplied evidence or a separately authorized review, with actual executor/time, evaluated revision, scope and evidence. Keep previous runs; mark stale results superseded. Writing the checklist never means the product is verified.

Planning output uses `Release Readiness: not_evaluated`. An explicitly requested release evaluation uses `passed | blocked` under the DoD rules. A required unrun/deferred check cannot pass.

## Workflow

Read the [security traceability contract](../to-sdd-pipeline/references/security-contract.md). Define positive and denied/adversarial checks for every PRD security obligation at the real enforcement seam, using architecture decisions. Bind them to `product_security_requirements` and return `security_coverage` plus per-check `security_requirement_ids`. Simulation alone cannot verify production controls. Preserve unchanged definitions; changed obligations invalidate affected results. Authoring still does not run tests or scanners.

1. Inspect current sources and recheck any repository observations; source truth defines behavior, not discovered implementation drift.
2. Before approval, prepare visual expectations against the proposed design with `Binding Status: pending_baseline`. After approval, use the reconciled architecture/DoD and bind visual checks to the active Baseline ID, immutable target hash and permitted variance.
3. Create stable check IDs. Map each distinct requirement obligation, journey and screen-state to checks or explicit blockers; do not mistake a parent requirement ID for clause coverage.
4. Group only useful concerns: acceptance, journeys, screens/states, heuristic usability, representative-user validation, UX/UI, responsive, accessibility, browser/device, regression and release.
5. Cover all applicable H1-H10 with task/user group, JOB/UC, route/state/viewport, expected behavior, evidence needs, applicability and result. Include desktop/mobile when supported, errors/recovery and accessible critical actions.
6. Explicitly check H7: simple novice flow, source-justified shortcuts, bulk/repeated work, keyboard/touch alternatives and useful customization. Check H10: contextual/task-oriented help, searchable docs when needed, actionable empty states, inline instructions and recovery links.
7. Verify each applicable failure sequence: cause → what was preserved → next action → retry/undo → observable success.
8. Add separate representative-user checks for applicable critical/consequential flows: JOB/UC, representative group, observed task, success criterion, device/viewport and pre-approval/post-implementation/both timing. Heuristic or visual evidence cannot stand in for real users.
9. Include applicable hover/focus/active/disabled, loading/empty/error/success, permission/offline, long-content and repeat-click checks. Verify keyboard/focus, labels/errors, semantics, targets, timing/motion/state communication, reflow and zoom.
10. Cite architecture/DoD gate IDs and guardrail evidence policy. For each item distinguish required evidence from actual evidence, pass from not-run, and severity from release effect.
11. After implementation begins, inspect declared prototype-promotion receipts when applicable; absent/mismatched receipts block fidelity. Never fabricate a receipt or make the plan an upstream dependency.
12. Validate coverage and boundaries; write only the checklist and return its hash-bound check/gate index to the caller.

A changed baseline/target/override invalidates affected bindings and results. Reuse unchanged checks and IDs; reconcile before development planning or release.

## Source-overridable UI defaults

Use the [accessibility policy](../to-sdd-pipeline/references/accessibility-policy.md) for standards-based reflow at 320 CSS px, text/viewport zoom, input/focus, motion and assistive-technology checks. Cover 390/430/768/1280/1440px for additional design comparison unless sources specify otherwise. House defaults: 44×44px touch targets with 8px separation, mobile input text 16px, body text usually 14–16px, and no emoji-as-icons. These preferences are source-overridable; they do not redefine WCAG's 24px AA target criterion or its exceptions. Verify applicable contrast and state communication in supported themes.

Use the [lifecycle checklist](../to-sdd-pipeline/references/lifecycle-contract.md) to define applicable deployment, restore/rollback, migration, performance, maintenance and outcome checks from PRD/architecture—not invented operations or claims of execution.

## Artifact coverage

Required semantic sections: Source References; Execution Status; Product Acceptance; Screen And State Checks; Heuristic Usability Checks; UX/UI Checks; Evidence Requirements; Evidence Limits; Release Readiness; Open Questions. Include Usability Validation Checks when applicable.

Every item resolves the shared verification record fields. Shared scope tables may supply repeated task/user/route/state/viewport data through IDs. Keep finding/severity/release-effect/recommendation empty or explicitly unassessed until findings exist, not fabricated to fill columns.

## Return

Report the file, checks prepared, actual execution status, supplied/observed evidence, pending bindings, limitations and open blockers. Follow shared provenance. State “checks prepared; tests not run” when only authoring occurred; no extra approval.
