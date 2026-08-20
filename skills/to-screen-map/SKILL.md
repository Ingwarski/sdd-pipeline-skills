---
name: to-screen-map
description: Use when docs/prd.md and docs/user-journey.md exist and the user wants to define the screen map, screen inventory, sitemap, routes, navigation, screen states, or transitions.
---
# to-screen-map

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit request, otherwise use the language of the latest substantive user message. Use it for all questions, playbacks, reports, and natural-language headings and prose in the owned artifact. English template headings are semantic labels, not literal output. For Ukrainian (`uk`), write idiomatic Ukrainian and keep English only in immutable filenames/paths, code/commands, machine values, API/identifier names, names/quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary English prose or calques. Keep explicit product content locales separate from the specification language.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/screen-map.md`, every load-bearing claim must be source-backed, user-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized decisions not fully determined by source files, play back the resolved decisions in a pithy summary and continue with the smallest reversible, source-grounded choice unless the missing answer materially changes product scope or a high-risk boundary. Playback is not an approval gate; intermediate screen-map artifacts and pre-approval design choices do not require approval.

## Input
Read:
- `README.md`, if present
- `docs/prd.md`
- `docs/project-context.md`, when present or supplied by `to-sdd-pipeline`
- `docs/canonical-terms.md`, when present or supplied by `to-sdd-pipeline`
- `docs/user-journey.md`
- `docs/guardrails.md`

Use confirmed relevant platforms, boundaries, localization constraints, flow names, and canonical vocabulary from the context bundle. Do not copy descriptive context, promote assumptions to facts, add screens or scope from context alone, or let either file override PRD/journey behavior. Record only the exact sections or terms consumed when pipeline provenance is requested.

## Output
Create or update exactly one artifact:
- `docs/screen-map.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/screen-map.md` owns:
- product screens and surfaces
- routes or navigation locations
- entry points and exit points
- transitions between screens
- required screen states
- empty, loading, error, success, and permission states
- links from screens to PRD requirements and journey stages

This file is the canonical owner of which states exist per screen. Wireframes own each state's structure; the design brief owns system-wide state appearance and behavior; the QA checklist verifies this list. Later artifacts reference this list instead of re-deriving it.

It must not define:
- detailed screen layouts
- component hierarchy inside a screen
- final copy
- visual style, colors, typography, or design tokens
- QA checklist items
- implementation tasks

Later artifacts may reference this file, but they must not duplicate its content.

## Proven Mechanics To Use
- Apply surface closure: every stated journey need must have a screen, surface, system response, or explicit non-screen explanation.
- Apply scope closure: every screen must trace back to `docs/prd.md` or `docs/user-journey.md`.
- Treat screens as contracts, not layouts. A screen map says what exists and how it connects; wireframes decide the internal structure.
- Model states explicitly. At minimum consider empty, loading, error, success, permission-denied, offline, and long-content states when relevant.
- Use Mermaid `flowchart LR` for transitions when it clarifies the route graph.
- Use a matrix for journey stage to screen coverage when the workflow has more than three screens.

## Gap-Check
Before writing, verify that sources identify:
- core screens needed to complete the main journey
- required navigation or route model
- completion, cancellation, error, and return paths
- important state transitions
- any modal, drawer, notification, email, or system surface that is required to complete the journey
- whether the product is single-surface, multi-surface, mobile, web, desktop, or cross-device

If routes, completion paths, or state logic are missing or contradictory, ask only when the unresolved answer materially changes product scope or a high-risk boundary. Otherwise derive the smallest reversible navigation/state model from the validated journey, record it, and continue.

## Workflow
1. Inspect the input files.
2. Extract the product's main workflow from `docs/prd.md` and `docs/user-journey.md`.
3. Identify all screens and surfaces required for the MVP journey.
4. Map entry points, exits, transitions, and return paths.
5. Identify required screen states.
6. Build a journey-to-screen coverage matrix.
7. Check surface closure: every journey stage must have a supporting screen or explicit non-screen explanation.
8. Check scope closure: every screen must trace to the PRD or user journey.
9. Flag screens or states that would require new product scope.
10. Before writing the artifact, verify the planned content:
   - Every load-bearing claim traces to a named source file or an explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
11. Create or update only `docs/screen-map.md`.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Screen Inventory`, `Journey-To-Screen Trace`, `Screen States`, and `Open Questions`. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. List omitted optional sections in the Final Report.

```markdown
# Screen Map

## Source References

## Screen Inventory

## Surface Closure Matrix

## Route Map

## Navigation Model

## Journey-To-Screen Trace

## Screen States

## Transition Notes

## Entry And Exit Points

## Edge Paths

## Out Of Scope Screens

## Open Questions
```

## Final Report
Return:
- `Result`
- `Created/Updated File`
- `Confirmed Facts And Constraints`
- `Omitted Optional Sections`, if any
- `Open Questions`
- `Next Recommended Action`
- `Next Recommended Skill`
