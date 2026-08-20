---
name: to-user-journey
description: Use when docs/prd.md exists and the user wants to map the user journey, user flow, personas, or journey stages before screens, wireframes, visual design, QA, or implementation planning.
---
# to-user-journey

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit request, otherwise use the language of the latest substantive user message. Use it for all questions, playbacks, reports, and natural-language headings and prose in the owned artifact. English template headings are semantic labels, not literal output. For Ukrainian (`uk`), write idiomatic Ukrainian and keep English only in immutable filenames/paths, code/commands, machine values, API/identifier names, names/quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary English prose or calques. Keep explicit product content locales separate from the specification language.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/user-journey.md`, every load-bearing claim must be source-backed, user-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized decisions not fully determined by source files, play back the resolved decisions in a pithy summary and continue with the smallest reversible, source-grounded choice unless the missing answer materially changes product scope or a high-risk boundary. Playback is not an approval gate; intermediate journey artifacts and pre-approval design choices do not require approval.

## Input
Read:
- `README.md`, if present
- `docs/prd.md`
- `docs/project-context.md`, when present or supplied by `to-sdd-pipeline`
- `docs/canonical-terms.md`, when present or supplied by `to-sdd-pipeline`
- `docs/guardrails.md`

Use confirmed relevant users, platforms, scenarios, constraints, and canonical vocabulary from the context bundle. Do not copy descriptive context, promote assumptions to facts, add product scope, or let either file override PRD behavior. Record only the exact sections or terms consumed when pipeline provenance is requested.

## Output
Create or update exactly one artifact:
- `docs/user-journey.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/user-journey.md` owns:
- primary user and context
- user goal and motivation
- named protagonist for the main journey, only when source-backed or user-confirmed
- real-session framing
- journey stages
- user actions
- decision points
- friction, fears, and blockers
- exit points
- success and failure states
- climax beat: the moment the user gets value or hits the central friction
- MVP journey risks

It must not define:
- screen inventory or routes
- wireframe layouts
- visual style, colors, typography, or design tokens
- QA checklist items
- implementation tasks

Later artifacts may reference this file, but they must not duplicate its content.

## Proven Mechanics To Use
- Start from a real person doing a real thing, not from a feature list.
- Use a named protagonist only when sources support it or the user confirms one. Never invent a persona name. If unnamed, use the role label and log the gap in Open Questions.
- Capture the journey as numbered steps with a climax beat and, where relevant, a failure path.
- Probe for stakes early: hobby, internal tool, consumer product, regulated product, paid workflow, sensitive data, or accessibility-critical usage.
- Prefer a Mermaid `journey` diagram when it clarifies the flow, but keep the markdown artifact readable without the diagram.

## Gap-Check
Before writing, verify that sources identify:
- the primary user
- the user's main goal
- the starting context
- the expected end state
- important constraints or risks
- the form factor or usage context, if it affects the journey
- the user's main fear, friction, or trust concern, if the PRD depends on behavior change

If any of these are missing or contradictory, ask only when the unresolved answer materially changes product scope or a high-risk boundary. Otherwise derive the smallest reversible journey interpretation from the PRD and guardrails, record the gap, and continue.

## Workflow
1. Inspect the input files.
2. Identify the primary user from sources.
3. Identify the real session: where the user is, what triggers the session, what device or context matters, and what pressure exists.
4. Extract the main user goal, success state, and failure path.
5. Map the journey stages from entry to completion as numbered steps.
6. Name the climax beat.
7. Capture actions, decisions, friction, trust concerns, exit points, and risks.
8. Trace every claim to source files or explicit user answers.
9. Avoid adding features, personas, flows, or goals outside the PRD.
10. Before writing the artifact, verify the planned content:
   - Every load-bearing claim traces to a named source file or an explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
11. Create or update only `docs/user-journey.md`.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Primary User`, `User Goal`, `Starting Context`, `Journey Stages`, `Success State`, and `Open Questions`. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. List omitted optional sections in the Final Report.

```markdown
# User Journey

## Source References

## Primary User

## Named Protagonist (only if source-backed or user-confirmed; otherwise use the role label)

## User Goal

## Starting Context

## Stakes And Constraints

## Journey Overview

## Journey Stages

## Climax Beat

## Decision Points

## Friction And Risks

## Failure Path

## Exit Points

## Success State

## Confirmed Facts And Constraints

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
