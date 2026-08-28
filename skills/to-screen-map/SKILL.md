---
name: to-screen-map
description: Define screens, surfaces, routes, navigation, transitions and the canonical screen-state inventory from the PRD and user journey.
---
# to-screen-map

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve the link from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs

Required before starting: `docs/prd.md`, `docs/user-journey.md`, `docs/guardrails.md`; in pipeline mode also the validated `docs/project-context.md` and `docs/canonical-terms.md` bundle.

Optional grounding: README and confirmed platform, localization, boundary and vocabulary facts. Context alone cannot introduce a screen or feature.

## Output and ownership

Write only `docs/screen-map.md`. Own screens/surfaces, routes or navigation locations, entries/exits, transitions and which states exist per screen.

Wireframes own each state's structure; the design brief owns shared appearance/behavior; QA verifies this inventory. Do not define internal layouts, component hierarchy, final copy/style/tokens, QA items or implementation tasks.

## Workflow

1. Extract the PRD/journey workflow and its JOB/UC references.
2. Identify every surface needed for completion: screens and, where required, modals, drawers, notifications, emails or non-screen system responses.
3. Map routes/navigation, entry, return, cancellation, completion and failure paths.
4. Define applicable states, including empty, loading, error, success, permission-denied, offline and long-content.
5. Check **surface closure**: every journey stage has a supporting surface or an explicit non-screen explanation.
6. Check **scope closure**: every surface/state traces to a PRD requirement or journey stage and applicable UC. Flag new scope; do not invent it.
   Trace security-sensitive surfaces and denied/expired/recovery states to PRD obligations. New sharing, export, upload or privileged surfaces require upstream security reassessment, not a screen-only scope addition.
7. Write a journey-to-screen trace; use a matrix for more than three screens and Mermaid `flowchart LR` only when useful.
8. Validate coverage and write only the screen map.

Resolve non-material navigation ambiguity with a documented reversible model. Ask one material question only when sources cannot settle scope or a high-risk boundary.

## Artifact coverage

Required semantic sections: Source References; Screen Inventory; Journey-To-Screen Trace; Screen States; Open Questions.

Use Route Map, Navigation Model, Surface Closure Matrix, Transition Notes, Entry/Exit Points, Edge Paths and Out Of Scope only when useful. Each inventory/trace row resolves screen/surface ID, applicable JOB/UC, journey stage and requirement. Reference use-case steps rather than repeating them.

## Return

Report the file, coverage and state changes, open questions and next owner. Follow the shared provenance contract; no screen-by-screen approval.
