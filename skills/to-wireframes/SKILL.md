---
name: to-wireframes
description: Turn a screen map into low-fidelity layouts, content hierarchy, actions, forms and structural state/recovery variants before visual design.
---
# to-wireframes

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve the link from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs

Required before starting: `docs/prd.md`, `docs/user-journey.md`, `docs/screen-map.md`, `docs/guardrails.md`; in pipeline mode also the validated `docs/project-context.md` and `docs/canonical-terms.md` bundle.

Optional grounding: README, existing design-system/component evidence, screenshots, confirmed content/localization/device constraints.

For error/recovery states, read the [shared recovery contract](../to-sdd-pipeline/references/heuristic-usability-review.md). Resolve it from the installed skill, never as a project-local `skills/` path.

The later `docs/design-brief.md` is **not** an input. The order is screen map → wireframes → design brief → interactive mockups.

## Output and ownership

Write only `docs/wireframes.md`. Own low-fidelity layout, hierarchy, content zones, primary/secondary actions, forms/inputs, structural states, responsive priorities and error/recovery structure.

Reference the screen map's state inventory and upstream JOB/UC behavior. Do not define final color, typography, mood, brand styling, polished components, tokens, QA items or implementation tasks.

## Workflow

1. Confirm each screen's user goal, content, primary action, structural constraints and required interaction depth from upstream sources.
2. Ground structure in available product/design-system evidence. Missing non-material aesthetic direction does not block wireframes.
3. For each screen, write an ordered zone list with hierarchy/priority. Add an ASCII sketch for non-single-column layouts.
4. Express state variants as deltas from the default blueprint; cover applicable default, loading, empty, error, success, disabled, permission, offline and long-content states.
5. For every applicable failure, specify: **cause → what was preserved → next action → retry/undo option → condition for successful completion**. Give a source-backed reason for any inapplicable element.
6. Prioritize spacing, grouping, alignment and hierarchy; then dividers, subtle tint, borders and finally shadows. Do not default to whole-app cards, nested cards or card-heavy layouts without a source-backed need.
7. Use realistic content slots. Preserve CTA/intent traceability to JOB/UC, journey stage and screen-state IDs. Define responsive structure only where content priority or interaction changes.
8. Check scope, structural coverage and recoverability; write only the wireframes.

Preserve PRD security obligations in sensitive forms, confirmations, disclosure and denied/recovery states. A disabled or hidden control is presentation, not authorization. Route any structural change that alters permissions, exposed data or consequential actions upstream before synchronizing it.

Prototype scope means whole-product **design coverage**, not production implementation. Typography, visual mood, tokens and final styling remain downstream.

## Artifact coverage

Required semantic sections: Source References; Wireframe Principles; Screen Blueprints; State Variants; Open Questions.

For each blueprint resolve: Source Screen; JOB/UC and journey/state references; Purpose; Primary User Intent; ordered Layout Structure; Primary CTA; Secondary Actions; Inputs/Content; States; applicable Error And Recovery Contract; Notes For Design Brief.

Shared patterns, responsive priorities and cross-screen handoff notes are optional. Keep per-screen notes in the blueprint; do not repeat them in a global section.

## Return

Report the file, structural decisions and coverage, open questions and next owner. Follow the shared provenance contract; no intermediate design approval.
