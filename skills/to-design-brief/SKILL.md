---
name: to-design-brief
description: Use when docs/wireframes.md exists and the user wants the design brief, design direction, visual system, design tokens, typography and color direction, interaction rules, or design handoff.
---
# to-design-brief

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit request, otherwise use the language of the latest substantive user message. Use it for all questions, playbacks, reports, and natural-language headings and prose in the owned artifact. English template headings are semantic labels, not literal output. For Ukrainian (`uk`), write idiomatic Ukrainian and keep English only in immutable filenames/paths, code/commands, machine values, API/identifier names, names/quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary English prose or calques. Keep explicit product content locales separate from the specification language.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

For aesthetic direction, the assistant may define up to three clearly labeled, source-grounded candidate directions. Do not require the user to select one before the brief or Prototype Mockup Candidates are created. Record shared constraints, candidate differences, and rationale; the final visual direction is established only by the engineer-approved integrated mockup.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/design-brief.md`, every load-bearing claim must be source-backed, user-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized decisions not fully determined by source files, play back the resolved decisions in a pithy summary and continue with the smallest reversible, source-grounded choice unless the missing answer would materially change product scope or a high-risk action. Playback is not an approval gate. Pre-approval design ambiguity becomes candidate directions; the only normal design approval is the engineer's approval of the complete integrated prototype after candidate comparison.

## Input
Read:
- `README.md`, if present
- `docs/prd.md`
- `docs/project-context.md`, when present or supplied by `to-sdd-pipeline`
- `docs/canonical-terms.md`, when present or supplied by `to-sdd-pipeline`
- `docs/user-journey.md`
- `docs/screen-map.md`
- `docs/wireframes.md`
- `docs/guardrails.md`
- the current Phase 2 executor/handoff metadata supplied by `to-sdd-pipeline`, when present

Use confirmed relevant audience, platform, localization, brand/provenance, content, constraint, and vocabulary facts from the context bundle. Do not copy descriptive context, promote assumptions to facts, add product scope, or let either file override PRD/journey/screen/wireframe behavior. Record only the exact sections or terms consumed when pipeline provenance is requested.

## Output
Create or update exactly one artifact:
- `docs/design-brief.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/design-brief.md` owns:
- UX/UI design intent
- visual direction
- design brief
- design decision log
- information density and interface tone
- semantic design tokens
- typography direction
- color direction
- spacing and layout rhythm
- component appearance principles
- interaction feel
- responsive behavior
- accessibility floor
- design handoff guidance
- design-relevant usability validation plan and evidence status for critical user flows
- the complete Design Source Material Inventory used by design executors
- approved visual-baseline metadata and references after the whole prototype is approved

For states: `docs/screen-map.md` owns which states exist per screen; `docs/wireframes.md` owns each state's structure; this file owns system-wide state appearance and behavior patterns. Reference the screen-map state list; do not re-derive it.

It must not define:
- new product features
- new screens or routes
- detailed wireframe structure already owned by `docs/wireframes.md`
- QA checklist items
- implementation tasks

Reference prior artifacts instead of restating them.

## Proven Mechanics To Use
Adapt the strongest UX Coach mechanics into a single SDD artifact:
- Treat the brief as two spines inside one file: `Design Spine` and `Experience Spine`.
- Keep the design intent traceable from `JOB-*` to `UC-*` to journey stage and covered screen/state; reference upstream behavior instead of redefining it.
- The Design Spine is the visual contract: brand/style, colors, typography, spacing, radius, elevation, component appearance, visual do/don't rules.
- The Experience Spine is the behavior contract: form factor, IA implications, voice/tone rules, component behavior, state patterns, interaction primitives, accessibility, key flows.
- Before design approval, the Design Spine and Experience Spine guide candidate generation in either Codex or Claude Design. After the engineer approves the complete integrated prototype in Codex, the `Approved Visual Baseline` section in this file is the single canonical baseline manifest, the concrete source of truth for visual composition, interaction detail, and frontend presentation, and the visual Definition of Done for every user-visible frontend unit. Selection in Claude Design identifies the version to export but is not this approval. Do not create a second competing baseline receipt elsewhere. The spines remain authoritative for reusable system rules, unshown states, responsive behavior, and accessibility, and must be reconciled with the approved baseline. PRD and journey artifacts remain authoritative for product scope and behavior. Unapproved explorations and implementation preference never override either source.
- Keep a `Decision Log` for selected directions, rejected directions, scope cuts, tool choices, and user overrides.
- Run a concern scan: accessibility, platform conventions, brand voice, regulated language, motion, internationalization, dark mode, offline behavior, content density, input modalities, notifications, AI control and reversibility.
- Surface UI system inheritance. If shadcn, MUI, Tailwind, native UIKit, Compose, or an internal design system exists, extend or reference it instead of inventing a parallel system.
- Use visual-first structures where useful: token tables, state matrices, component spec tables, Mermaid flow diagrams, and small swatch/type/spacing examples.
- When current UI systems, accessibility standards, platform HIGs, or named visual references may have changed, verify them with current sources before creating or updating the artifact.

Use the strongest production UX/UI mechanics:
- Start from user goal, audience, primary action, and product context.
- For every critical flow, define a representative-user task validation plan with the applicable `JOB-*`/`UC-*`, user group, task, device or viewport, success criterion, and evidence status. A plan or heuristic review is not user research; if representative-user validation was not run, label that as an assumption or open risk.
- Match experience type: SaaS/operational tool, checkout, AI product, course/content, dashboard, landing/sales, mobile app, internal tool, or regulated workflow.
- Preserve existing design systems unless the user explicitly wants a redesign.
- Define complete states: default, hover, focus, active, disabled, loading, empty, error, success, long-content, offline, and permission-denied when relevant.
- Meet WCAG 2.2 AA by default: contrast, visible focus, keyboard access, semantic structure, labels, errors, and target sizes.
- Preserve source-approved motion and make required state or information understandable without relying on animation alone. Do not invent a reduced-motion variant or automatically remove, replace, or simplify approved motion unless an explicit product source requires it.
- When project principles or user policy define font constraints, verify font licensing and provenance before selection. If provenance cannot be confidently verified, prefer system stacks or verified independent foundries.
- Plan responsive behavior at 390, 430, 768, 1280, and 1440px unless sources specify different target devices.
- Avoid one-note palettes, decorative blobs, meaningless gradients, hidden scrollbars, card-in-card layouts, and visual trend choices that weaken usability.

## Gap-Check
Before writing, verify that sources identify:
- target audience and product category
- brand or desired product feeling
- platform and device priorities
- complexity and information-density needs
- accessibility expectations
- visual constraints, if any
- existing design system, visual source, brand deck, screenshots, tokens, component library, or inspiration/rejection references
- expected interactivity and motion level
- primary `JOB-*` and `UC-*` references, and whether representative-user task validation is required, available, or explicitly deferred
- whether the user wants a fast path with explicit assumptions or a coached path with decisions resolved section by section

If audience, product category, platform priorities, existing-system inheritance, or another constraint is missing or contradictory, ask only when the answer would materially change product scope or a high-risk boundary. Missing aesthetic direction alone is not a blocker: derive up to three source-grounded candidate directions, record the reversible assumptions, and continue to whole-prototype comparison.

## Workflow
1. Inspect the input files.
2. Find grounding material before inventing: design docs, screenshots, Figma links, Storybook, tokens, components, CSS variables, brand assets, or reference products named by the user. Catalog every discovered material or link in `Design Source Material Inventory`; do not leave a source implicit in prose.
3. Extract UX intent from the PRD, user journey, screen map, and wireframes.
4. Resolve the applicable `JOB-*` and `UC-*` references without restating their definitions.
5. Identify the product type, stakes, form factor, and level of visual sophistication needed.
6. Run the concern scan and decide which concerns deserve sections.
7. Define a source-backed Design Spine.
8. Define a source-backed Experience Spine.
9. Define the representative-user task validation plan for critical flows; keep execution evidence and per-check results in QA/DoD owners.
10. Critique the planned Design Spine against generic AI defaults: templated palettes, interchangeable type pairings, decorative filler, and styles that could belong to any product in the category. Name one signature element or one deliberate restraint principle grounded in the product's domain, and state where the design spends or withholds boldness. If the direction is not product-specific, revise it or turn the strongest source-grounded alternatives into clearly labeled Prototype Mockup Candidates for whole-design comparison; do not add a pre-mockup selection gate. These candidates are design-only interaction simulations, not application implementations.
11. Define semantic tokens and component appearance principles without overbuilding a design-system monster.
12. Define responsive, accessibility, state, and interaction expectations.
13. Add handoff prompts or guidance for Figma, v0, Stitch, Codex, or Claude Design only when useful and only from captured content. Handoff guidance must name frozen inputs, the complete Design Source Material Inventory, and equivalent design scope, never grant the design tool authority to edit SDD artifacts or production code.
14. Run the Validation Pass defined below before creating or updating the artifact.
15. When an integrated prototype has been approved, atomically update the canonical `Approved Visual Baseline` section with its stable Baseline ID, selected candidate/version, origin `codex | claude_design`, handoff ID when applicable, immutable visual target/hash, frozen normalized prototype source root/tree hash and algorithm, durable repository-relative artifact references, visual-DoD scope, coverage, Codex whole-design approval receipt, and permitted variance. Never use a Claude chat URL, temporary export path, or external result ID as the sole durable baseline reference. Keep the prior approved baseline active while a revision is only proposed. An explicit scoped operator correction becomes a recorded baseline override for that scope; a newly approved integrated whole creates a new active Baseline ID and marks the old immutable baseline superseded. Record the prior ID and receipt in the Decision Log and downstream invalidation intent in this artifact. Do not create another design approval merely to acknowledge an operator-authored correction. Only the orchestrator changes manifest/runtime status, re-invokes QA and development-plan owners, and marks affected production units invalidated.
16. Avoid changing scope, adding screens, or rewriting wireframes.
17. Before writing the artifact, verify the planned content:
   - Every load-bearing claim traces to a named source file or an explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
18. Create or update only `docs/design-brief.md`.

## Validation Pass
Run both passes on the planned artifact content. Record results in the artifact's `Validation Report` as findings ranked by downstream impact: Critical, High, Medium, Low. If a pass has no findings, state `0 findings` for that pass.

Pass 1 - Mechanical coverage:
- Every key flow referenced names its journey source and has success and failure coverage in the Experience Spine.
- Every token referenced anywhere in the brief resolves to a defined value in the Design Spine.
- Every component named in either spine has both an appearance principle and a behavior principle.
- Every screen and state in `docs/screen-map.md` is covered by a state pattern or explicitly deferred with a reason.
- Every visual reference, link, or source named in the brief has exactly one inventory entry with a required/optional decision, location, access status, and content hash or capture ID when applicable.
- Every required inventory entry resolves in the executor environment or has an authorized self-contained capture/bundle; unavailable required sources are blocking and are listed in `Open Questions`, never silently dropped.
- Every link or material named elsewhere in the brief appears in the inventory, and every inventory entry is referenced by the brief or handoff contract.
- Every `JOB-*` and `UC-*` reference resolves to an upstream artifact, and every critical flow has a representative-user task validation plan with an explicit `run`, `deferred`, or `not applicable` status and reason.

Pass 2 - Judgment:
- Bloat: no pixel specs where tokens suffice, no decorative prose, no sections filled to satisfy the template.
- Inheritance: named UI systems, versions, and source terminology are used faithfully; no parallel system is invented.
- Shape: sections follow the required structure; spines stay contracts, not restated wireframes.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Design Source Material Inventory`, `Design Brief`, `Decision Log`, `Product Experience Goal`, `Design Spine`, `Experience Spine`, `Approved Visual Baseline`, `Validation Report`, and `Open Questions`. Before prototype approval, `Approved Visual Baseline` uses `Status: proposed`; after approval it must identify the approved whole. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. List omitted optional sections in the Final Report.

Each inventory entry must record `material_id`, `kind`, `location` (repository-relative path or URL), `required_for_candidate_generation`, `purpose`, `source_basis`, `access_status` (`resolved`, `unavailable`, or `not_required`), and `content_hash_or_capture_id` when applicable. For external material also record the authorized access mode (`browser_open`, `captured_bundle`, or `handoff_export`). A required item with `access_status: unavailable` is a source-access blocker; it is not an approval decision and must not be converted into a guessed substitute.

```markdown
# Design Brief

## Source References

## Design Source Material Inventory

## Design Brief

## Decision Log

## Audience And Context

## Product Experience Goal

## Concern Scan

## Design Spine

Token values live only in `### Design Tokens`; other spine sections reference tokens by name instead of repeating values.

### Brand And Style

### Colors

### Typography

### Layout And Spacing

### Elevation And Depth

### Shapes

### Component Appearance

### Visual Do's And Don'ts

### Design Tokens

## Experience Spine

### Foundation

### Information Architecture Implications

### Voice And Tone

### Component Behavior

### State Patterns

### Interaction Primitives

### Accessibility Floor

### Key Flow Implications

## Usability Validation Plan

## Responsive And Platform Behavior

## Design Handoff Prompt

## Approved Visual Baseline

- Status: proposed | approved | superseded
- Baseline ID:
- Selected Candidate And Version:
- Candidate Origin And Handoff ID:
- Immutable Visual Target Reference And Hash:
- Frozen Prototype Source Root Tree Hash And Algorithm:
- Prototype Artifact References:
- Visual Definition Of Done Scope:
- Covered Screens States And Viewports:
- Approval Receipt:
- Approved At:
- Permitted Variance:
- Operator Overrides:
- Supersedes:
- Superseded By:
- Downstream Invalidation:

## Validation Report

## Confirmed Design Decisions

## Rejected Directions

## Out Of Scope

## Open Questions
```

## Final Report
Return:
- `Result`
- `Created/Updated File`
- `Confirmed Design Decisions`
- `Omitted Optional Sections`, if any
- `Open Questions`
- `Next Recommended Action`
- `Next Recommended Skill`
