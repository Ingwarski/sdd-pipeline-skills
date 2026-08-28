---
name: to-design-brief
description: Define design and experience rules, tokens, usability coverage, source inventory and the canonical approved visual baseline from structural wireframes.
---
# to-design-brief

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) and [H1-H10 contract](../to-sdd-pipeline/references/heuristic-usability-review.md) before work. Resolve links from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs

Required before starting: PRD, guardrails, journey, screen map and wireframes under `docs/`; in pipeline mode also the validated context/terms bundle.

Optional grounding: design-material source notes in `docs/product-idea.md` and their referenced locations, README, explicit audience/brand/content/platform constraints, existing tokens/components/design systems, screenshots/reference products and Phase 2 executor/handoff metadata.

QA check IDs and executed evidence are **later references**, not prerequisites for creating the brief. Until real IDs exist, leave bindings pending. Read the [verification contract](../to-sdd-pipeline/references/verification-contract.md) when planning reviews/user validation.

## Output and ownership

Write only `docs/design-brief.md`. Own design intent/direction, design decisions, semantic tokens, density/tone, typography/color/spacing/component appearance, shared interaction/state behavior, responsive/accessibility rules, handoff, source inventory, H1-H10 coverage, user-validation plan and canonical approved-baseline metadata.

The screen map owns which states exist; wireframes own their structure. PRD/journey own product behavior. Do not create features, screens/routes, duplicate layouts, concrete QA items or implementation tasks.

## Design process

1. Reuse intake materials/preferences without repeating the upload request. Find other grounding material before inventing. Catalog every named file, screenshot, asset, design-system reference and external link in the Design Source Material Inventory; retain confirmed constraints versus inspiration and observed access limits.
2. Trace intent through JOB → UC → journey → screen/state. Identify product type, audience, primary action, stakes, device/form factor and density.
3. Run a concern scan: accessibility, platform conventions, brand/regulated language, motion, localization, dark mode, offline, content, input modes, notifications and AI control/reversibility. Expand only relevant concerns.
4. Preserve existing UI systems and source vocabulary. Verify current named standards, platform guidance and external references when needed; do not invent a competing system.
5. Define two complementary sections:
   - **Design Spine:** brand/style, color, typography, spacing/layout, radius/shapes, elevation, component appearance, visual do/don't rules and semantic tokens.
   - **Experience Spine:** form factor, IA implications, voice/tone, component behavior, state patterns, interactions, accessibility and key flows.
6. Store token values once; other rules reference token names. Cover appearance and behavior for every named component and all applicable screen-map states.
7. Critique generic defaults. Name a domain-grounded signature element or deliberate restraint, and where the design uses or withholds boldness. Avoid decorative filler, meaningless gradients/blobs, hidden scrollbars, one-note palettes and nested-card defaults that weaken usability.
8. Missing aesthetic direction is not a blocker: propose up to three source-grounded directions with shared constraints/differences/rationale. Do not ask the user to choose before interactive candidate comparison.
9. Define explicit H1-H10 coverage for the primary journey and representative screens/states/routes/viewports, desktop/mobile when supported, recovery and accessible critical actions. `covered` means planned coverage, not passed testing.
10. Make H7 efficiency and H10 contextual/task-oriented help decisions explicit. Every applicable failure uses cause → what was preserved → next action → retry/undo → observable completion.
11. Plan representative-user tasks for critical/consequential flows: JOB/UC, user group, task, device/viewport, success criterion, timing and evidence status. For regulated, safety- or accessibility-critical/high-risk flows prefer pre-approval validation when feasible. A deferral needs assumption/risk, owner and timing; do not call it user-validated.
12. Define responsive and accessibility rules. Default to WCAG 2.2 AA design targets and 390/430/768/1280/1440px unless sources specify otherwise; screenshots do not prove conformance.
13. Preserve source-approved motion and communicate required state/information without animation alone. Do not invent motion removal, simplification or an unrequested reduced-motion variant. Verify font licensing/provenance when project policy requires it; prefer system stacks or verified independent foundries if uncertain.
14. Record selected/rejected directions, scope cuts, tool choices and user overrides in the Decision Log. Handoff guidance names frozen inputs, the complete inventory and equivalent scope; no permission to edit domain docs or production code.
15. Run both validation passes below, then write only the brief.

## Source inventory

Each material resolves: `material_id`, kind, repository-relative path/URL, required-for-generation flag, purpose, source basis, access status (`resolved | unavailable | not_required`), hash/capture ID where applicable, and authorized access mode for external material.

Every named material has one entry; every entry has a use. An unavailable **required** source blocks candidate generation and stays visible in Open Questions; do not silently substitute it. An optional aesthetic reference may use a disclosed fallback. Claude Design additionally requires its source-access/read receipts.

## Approval and reconciliation

Classify proposed changes by security impact before accepting them into the baseline. Changed roles, sharing, data visibility, inputs, integrations or sensitive actions require affected PRD obligations to be reassessed and upstream owners reconciled first. Styling-only changes preserve security requirements and need no full PRD rerun. A design approval cannot waive a security control; simulated authentication/authorization is never product-security evidence.

Before approval, the baseline section is `Status: proposed`. Only the engineer's whole-design approval in Codex makes one exact candidate/version authoritative. A Claude selection only chooses what to export.

On approval, atomically record: Baseline ID; selected candidate/version; origin and handoff ID; immutable target reference/hash; frozen normalized prototype source root/tree hash with `sdd-tree-sha256-v1`; durable prototype paths; visual-DoD scope; screen/state/viewport coverage; operator approval receipt/time; permitted variance; overrides and supersession.

Keep the prior approved baseline active and immutable while a revision is proposed. A new approved whole supersedes it; preserve the earlier ID/receipt/history. A source-backed accepted scoped correction is an operator override, not a redundant approval request.

The canonical section is the only baseline authority. Spines still govern reusable/unshown states and accessibility; reconcile them with the approved whole. No temporary URL/export/result ID may be its sole durable reference. Return invalidation intent: the orchestrator rechecks affected architecture → DoD → QA → development plan and invalidates prior implementation authorization. This owner cannot change runtime state.

## Validation passes

**Mechanical:** every key flow traces to journey/JOB/UC with success/failure coverage; every token resolves; every component has appearance and behavior; every required state has a pattern or explicit deferral; every source has a usable inventory entry or named blocker; every critical flow has a task-validation plan; H1–H10 each have applicability/status/rationale, coverage and planned evidence. QA references remain pending until created.

**Judgment:** no duplicated wireframes or token values, generic filler or unsupported scope; inheritance is faithful; direction is product-specific; spines remain contracts. Review H1 feedback, H2 user language/model, H3 exit/undo/cancel, H4 standards, H5 prevention, H6 recognition/context, H7 efficiency, H8 relevance/noise, H9 diagnosis/recovery and H10 help.

Record findings in Validation Report by downstream impact (Critical/High/Medium/Low), or `0 findings` per pass. This artifact-review ranking is not a competing P0–P3 release scale.

## Artifact coverage and return

Required semantic sections: Source References; Design Source Material Inventory; Design Brief; Decision Log; Product Experience Goal; Design Spine; Experience Spine; Heuristic Review; Usability Validation Plan; Approved Visual Baseline; Validation Report; Open Questions. Add other sections only for decisions.

Heuristic rows resolve ID, JOB/UC/journey, scope, expected behavior, applicability, planned evidence, `covered | deferred | not applicable`, rationale and later QA binding. Keep actual execution evidence/findings with QA; DoD defines gates.

Return file, changed decisions, coverage/open risks, validation and baseline/provenance fields. No section approval or automatic candidate selection.
