---
name: to-guardrails
description: Use when an SDD workflow needs AI guardrails, source-of-truth order, autonomy limits, scope boundaries, conflict resolution, stop conditions, or verification rules. Can run any time after docs/prd.md exists; running it before the design artifacts is recommended.
---
# to-guardrails

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit request, otherwise use the language of the latest substantive user message. Use it for all questions, playbacks, reports, and natural-language headings and prose in the owned artifact. English template headings are semantic labels, not literal output. For Ukrainian (`uk`), write idiomatic Ukrainian and keep English only in immutable filenames/paths, code/commands, machine values, API/identifier names, names/quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary English prose or calques. Keep explicit product content locales separate from the specification language.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/guardrails.md`, every load-bearing rule must be source-backed, user-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized decisions not fully determined by source files, play back the resolved decisions in a pithy summary and continue with the smallest reversible, source-grounded rule unless the missing answer would materially change product scope or a high-risk action. Playback is not an approval gate; guardrails do not select or approve a design direction.

## Input
Read:
- `README.md`, if present
- `docs/prd.md`
- `docs/project-context.md`, when present or supplied by `to-sdd-pipeline`
- `docs/canonical-terms.md`, when present or supplied by `to-sdd-pipeline`
- `docs/product-idea.md`, only when `docs/prd.md` names it as authoritative or the user asks to use it

This skill runs after `docs/prd.md` and the validated context bundle in pipeline mode, and before downstream UX, architecture, DoD/eval, and QA artifacts. Use only confirmed relevant context constraints and canonical vocabulary; do not turn assumptions into guardrails or let either context file override PRD behavior. Record exact consumed sections or terms when the orchestrator requests provenance. Re-run only when the PRD, an explicitly authoritative product-idea source, a consumed context/term fragment, or a user decision invalidates a named rule or introduces a new authority/risk boundary. Never read downstream artifacts back into guardrails; this keeps the dependency graph acyclic.

## Output
Create or update exactly one artifact:
- `docs/guardrails.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/guardrails.md` owns:
- source-of-truth hierarchy
- AI autonomy boundaries
- allowed and forbidden changes
- scope boundaries
- conflict resolution rules
- when to ask before acting
- when to stop
- verification expectations
- document separation rules
- mockup, prototype, screenshot, and static-surface limits for completion claims

This file owns the behavioral evidence policy: when the AI must verify, what counts as evidence, and when missing evidence must stop work. `docs/dod-evals.md` owns the reusable completion/eval contract: which gates and evidence make work Done. `docs/qa-checklist.md` owns concrete per-release or per-screen checks and per-check evidence artifacts that cite both.

It must not define:
- user journey content
- screen inventory
- wireframe layouts
- visual design direction
- QA checklist details
- implementation tasks

Other artifacts may follow these rules, but they must not duplicate this document.

## Proven Mechanics To Use
- Evidence before claims, as an operational gate: identify what proves the claim, run it fresh, read the full output, and only then state the result with the evidence. No success, completion, quality, or compliance claim without this sequence.
- Split authority by concern: PRD and journey artifacts own product scope and behavior; after the engineer's one whole-prototype approval, the Approved Visual Baseline owns visual composition, interaction detail, and frontend presentation; architecture, guardrails, and applicable standards own technical, safety, accessibility, privacy, and legal boundaries. Before approval, wireframes and design-brief spines guide candidate generation. Generic defaults, unapproved mockups, implementation guesses, and assistant preference never override these sources.
- A mockup, screenshot, prototype, or visually convincing static surface is design/visual evidence only; it is not completed functionality unless connected to source-backed behavior, real state/data/actions, runner evidence, and required DoD gates.
- Extract, do not ingest: when sources are long, pull only the relevant decisions and cite them. Do not paraphrase entire source files into this artifact.
- Right-size rigor to stakes: hobby, internal, consumer, paid, regulated, accessibility-critical, or safety-sensitive products need different guardrails.
- Default to autonomous reversible decisions within approved product intent. Define exactly one normal design approval for the complete integrated prototype and reserve separate just-in-time authorization for irreversible, destructive, financial, legal, public, security-sensitive, privacy-sensitive, privileged, or external side effects.
- Preserve artifact boundaries: later docs may reference earlier docs, not silently rewrite them.
- Stop before acting when an inaccessible named source, design system, or requirement is material to product scope, a compliance claim, or a high-risk action. An inaccessible aesthetic reference alone does not create a pre-prototype approval gate: record it, disclose the fallback, and continue with source-grounded candidate directions when possible.
- Never silently ignore unavailable files, screenshots, links, tokens, or brand materials; classify their materiality and trace the fallback or blocker.

## Gap-Check
Before writing, verify that sources identify:
- which documents are authoritative
- what AI may decide independently
- what requires explicit user approval
- what is forbidden
- how conflicts should be resolved
- required verification standard
- where visual/static evidence ends and functionality evidence begins
- which visual/design sources are authoritative, if any
- whether AI may propose aesthetic options or must wait for user-provided direction

If authority, autonomy, forbidden actions, or conflict rules are missing or contradictory and the unresolved answer materially changes product scope, compliance, or a high-risk boundary, stop and ask grill-me questions before producing the output. Otherwise use the recommended stakes baseline, record the reversible choice, and continue.

### Default Baseline For Recommendations
Sources rarely state guardrails explicitly. Do not run an open-ended interview. Identify the stakes tier first, present the matching baseline as the recommended answer for each gap-check question, and grill only on deviations and items the user marks as sensitive.

- Hobby / internal: AI may autonomously create and revise reversible SDD, layout, copy, visual, and technical details inside product intent. Ask only for material scope changes, deletion without safe recovery, the one whole-design approval, or a high-risk action.
- Consumer / paid: AI may autonomously create, revise, reconcile, and validate reversible user-facing details inside approved product intent. The engineer approves the complete integrated prototype once; ordinary artifact, screen, terminology, and transition changes do not require separate approval. Evidence remains required for completion claims.
- Regulated / accessibility-critical / sensitive data: AI may draft and revise source-backed artifacts autonomously, but compliance claims and high-risk effects require named evidence and risk-specific authorization. Do not require approval for every user-facing edit; retain the one whole-design approval and escalate only material product intent or regulated/high-risk decisions.

## Workflow
1. Inspect the input files.
2. Identify all available sources of truth.
3. Define source priority from most authoritative to least authoritative.
4. Define AI autonomy boundaries.
5. Define scope boundaries and forbidden behavior.
6. Define visual/design authority rules.
7. Define conflict resolution and stop conditions.
8. Define verification rules for SDD artifacts and future implementation.
9. Define mockup, prototype, screenshot, and static-surface limits for completion claims.
10. Preserve strict artifact separation.
11. Before writing the artifact, verify the planned content:
   - Every load-bearing rule traces to a named source file or an explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
12. Create or update only `docs/guardrails.md`.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Source Of Truth Order`, `AI Autonomy Boundaries`, `Forbidden Changes`, `When To Ask`, `When To Stop`, `Artifact Separation Rules`, `Verification Rules`, and `Open Questions`. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. List omitted optional sections in the Final Report.

```markdown
# Guardrails

## Source References

## Source Of Truth Order

## AI Autonomy Boundaries

## Allowed Changes

## Forbidden Changes

## Scope Boundaries

## Design Authority Rules

## Conflict Resolution

## When To Ask

## When To Stop

## Artifact Separation Rules

## Verification Rules

## Evidence Requirements

## Source Access Failures

## Open Questions
```

## Final Report
Return:
- `Result`
- `Created/Updated File`
- `Confirmed Rules And Constraints`
- `Omitted Optional Sections`, if any
- `Open Questions`
- `Next Recommended Action`
- `Next Recommended Skill`
