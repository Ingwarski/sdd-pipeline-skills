---
name: to-wireframes
description: Use when docs/screen-map.md exists and the user wants wireframes, low-fidelity layouts, screen structure, content hierarchy, CTAs, forms, or state variants before visual design.
---
# to-wireframes

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit request, otherwise use the language of the latest substantive user message. Use it for all questions, playbacks, reports, and natural-language headings and prose in the owned artifact. English template headings are semantic labels, not literal output. For Ukrainian (`uk`), write idiomatic Ukrainian and keep English only in immutable filenames/paths, code/commands, machine values, API/identifier names, names/quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary English prose or calques. Keep explicit product content locales separate from the specification language.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/wireframes.md`, every load-bearing claim must be source-backed, user-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized decisions not fully determined by source files, play back the resolved decisions in a pithy summary and continue with the smallest reversible, source-grounded choice unless the missing answer materially changes product scope or a high-risk boundary. Playback is not an approval gate; intermediate wireframes and pre-approval design choices do not require approval.

## Input
Read:
- `README.md`, if present
- `docs/prd.md`
- `docs/project-context.md`, when present or supplied by `to-sdd-pipeline`
- `docs/canonical-terms.md`, when present or supplied by `to-sdd-pipeline`
- `docs/user-journey.md`
- `docs/screen-map.md`
- `docs/guardrails.md`
- `skills/to-sdd-pipeline/references/heuristic-usability-review.md`, for the shared error/recovery contract when error states are applicable

Use confirmed relevant platform, viewport, localization, content, and vocabulary constraints from the context bundle. Do not copy descriptive context, promote assumptions to facts, invent screen structure from context alone, or override the screen map. Record only the exact sections or terms consumed when pipeline provenance is requested.

## Output
Create or update exactly one artifact:
- `docs/wireframes.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/wireframes.md` owns:
- low-fidelity screen structure
- content hierarchy
- primary and secondary CTAs
- forms, fields, and inputs
- content zones and repeated blocks
- state variants per screen
- interaction notes needed to understand layout behavior
- structural error and recovery contract for applicable failure states

Wireframes may reference `JOB-*` and `UC-*` IDs from upstream artifacts, but they do not redefine the job, use-case paths, or product requirements.

For states: `docs/screen-map.md` owns which states exist per screen - reference its list; this file owns each state's structure only.

It must not define:
- final colors
- typography system
- visual mood
- brand style
- component visual polish
- design tokens
- QA checklist items
- implementation tasks

The final product goal is high-quality UX/UI design. This artifact supports that goal by making the product structure clear before visual decisions are made.

## Proven Mechanics To Use
- Run a wireframe-readiness preflight, not a design-brief gate and not a human approval: derive what each screen must help the user do, which structural or existing-system constraints apply, and how interactive the final experience must be from the PRD, journey, screen map, guardrails, and available product evidence. The dependency order is `screen-map -> wireframes -> design-brief -> interactive Prototype Mockup Candidates`; `docs/wireframes.md` must never depend on `docs/design-brief.md`. Defer typography, color, visual mood, tokens, and component styling to the later design brief. Missing non-material visual direction does not block structural wireframes. `Whole-product` candidate scope means complete design coverage, not implementation of the application.
- Use a concrete notation, not prose. For every screen: an ordered content-zone list with a hierarchy level and priority per zone; an ASCII layout sketch for any screen whose layout is not a single column; state variants expressed as deltas from the default blueprint (for example: "Error: zone 3 replaced by inline message; primary CTA disabled").
- Keep the primary user intent and primary CTA traceable to the applicable `JOB-*`, `UC-*`, journey stage, and screen-map state without copying the upstream definitions.
- Prefer source capture over guessing. If an existing product, design system, screenshot, Storybook, component library, or token file exists, use it as grounding material.
- Differentiate structure before style: vary hierarchy, grouping, interaction model, and CTA emphasis before discussing brand style.
- Use this separation priority inside wireframes: spacing, grouping, alignment, and hierarchy first; simple dividers second; subtle surface tint third; borders fourth; shadows last.
- Do not default to a whole-app card, nested cards, or card-heavy layouts unless sources require it.
- Include complete structural states: default, loading, empty, error, success, disabled, permission-denied, offline, and long-content where relevant.
- For every applicable error or recovery state, specify the canonical sequence `cause -> what was preserved -> next action -> retry/undo option -> condition for successful completion`. If one element is not applicable, record the source-backed reason.
- Keep realistic content slots. Avoid lorem ipsum as a decision substitute.

## Gap-Check
Before writing, verify that sources identify:
- the screen inventory
- the applicable `JOB-*`, `UC-*`, journey-stage, and screen-map references
- primary action per screen
- required content or data per screen
- required states per screen
- priority of blocks when space is constrained
- whether an existing design system or component set must be respected
- expected interactivity depth for the later implementation
- error cause, preserved user work, next action, retry/undo behavior, and observable success condition for each applicable failure state

If block priority, CTAs, forms, or state behavior are missing or contradictory, ask only when the unresolved answer materially changes product scope or a high-risk boundary. Otherwise choose the smallest reversible structure that satisfies the screen map and journey, record it, and continue.

## Workflow
1. Inspect the input files.
2. Use `docs/screen-map.md` as the source for screens and states.
3. Preserve the applicable `JOB-*`, `UC-*`, journey-stage, and screen-map references.
4. For each screen, define purpose, user intent, content hierarchy, CTAs, inputs, and state variants.
5. For each applicable error/recovery state, define `cause -> what was preserved -> next action -> retry/undo option -> condition for successful completion`.
6. Keep wireframes low-fidelity and structural.
7. Define responsive structural behavior only where it affects content priority or interaction.
8. Preserve traceability to PRD requirements, user journey stages, and screen-map entries.
9. Avoid adding features, screens, fields, or flows outside approved sources.
10. Before writing the artifact, verify the planned content:
   - Every load-bearing claim traces to a named source file or an explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
11. Create or update only `docs/wireframes.md`.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Wireframe Principles`, `Screen Blueprints`, `State Variants`, and `Open Questions`. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. List omitted optional sections in the Final Report.

```markdown
# Wireframes

## Source References

## Wireframe Principles

## Screen Blueprints

## Responsive Structure Notes

## Shared Patterns

## State Variants

## Content Priority Notes

## Cross-Screen Notes For Design Brief

Only notes that span multiple screens. Per-screen notes belong in each blueprint.

## Open Questions
```

For each screen blueprint include:
- `Source Screen`
- `Job And Use-Case References`: applicable `JOB-*`, `UC-*`, journey-stage, and screen-map state IDs
- `Purpose`
- `Primary User Intent`
- `Layout Structure`
- `Primary CTA`
- `Secondary Actions`
- `Inputs And Content`
- `States`
- `Error And Recovery Contract`, for applicable error/recovery states: `cause -> what was preserved -> next action -> retry/undo option -> condition for successful completion`
- `Notes For Design Brief`

## Final Report
Return:
- `Result`
- `Created/Updated File`
- `Confirmed Facts And Constraints`
- `Omitted Optional Sections`, if any
- `Open Questions`
- `Next Recommended Action`
- `Next Recommended Skill`
