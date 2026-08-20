---
name: to-qa-checklist
description: Use when the current product, UX, architecture, guardrail, and DoD/eval SDD artifacts exist and the user wants a QA checklist, acceptance checks, accessibility checks, responsive checks, visual regression checks, or release-readiness criteria. Artifact readiness is a validation state, not a human approval.
---
# to-qa-checklist

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/qa-checklist.md`, every checklist group must be source-backed, user-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized decisions not fully determined by source files, play back the resolved decisions in a pithy summary and continue with the smallest reversible, source-grounded check unless the missing answer materially changes product scope or a high-risk boundary. Playback is not an approval gate. If a correction would change an already Approved Visual Baseline, record `baseline_change_required` for the orchestrator instead of asking or approving inside this skill.

Never write a repository-state observation as a bare fact. Record `<claim> — observed <ISO date> via <command>` plus the exact observed paths and content hashes in the orchestrator's scoped repository observation. Never assert that something does not exist without naming the command that would prove it still does not.

## Input
Read:
- `README.md`, if present
- `docs/prd.md`
- `docs/project-context.md`, when present or supplied by `to-sdd-pipeline`
- `docs/canonical-terms.md`, when present or supplied by `to-sdd-pipeline`
- `docs/user-journey.md`
- `docs/screen-map.md`
- `docs/wireframes.md`
- `docs/design-brief.md`
- the canonical `Approved Visual Baseline` section inside `docs/design-brief.md` and its referenced prototype artifacts, when its status is `approved`
- `docs/architecture.md`
- `docs/dod-evals.md`
- `docs/guardrails.md`
- the codebase, when one exists: package manifest, source/test directories, CI, build, runtime, and deployment configuration, to confirm which checks are currently executable
- `docs/development-plan.md`, only when it already exists and only to observe declared destination/receipt paths after implementation began; it is never a prerequisite or source of QA rules

Use confirmed relevant platforms, devices, locales, roles, operational constraints, risks, and canonical vocabulary from the context bundle only when they change an applicable check or fixture. Do not copy descriptive context, promote assumptions to checks, add product scope, or let either file override the owning SDD or Approved Visual Baseline. Record only the exact sections or terms consumed when pipeline provenance is requested.

## Output
Create or update exactly one artifact:
- `docs/qa-checklist.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/qa-checklist.md` owns:
- source-backed acceptance checklist
- journey completion checks
- screen and state coverage checks
- UX/UI consistency checks
- responsive checks
- accessibility checks
- browser/device checks
- regression risk checks
- release readiness checks

Evidence policy (when evidence is required, what counts) belongs to `docs/guardrails.md`; this file owns per-check evidence artifacts and cites that policy instead of restating it.

Definition of Done, reusable gates, eval result format, and completion rules belong to `docs/dod-evals.md`; this file owns concrete QA checklist items and cites that contract instead of restating it.

Architecture-driven verification concerns belong to `docs/architecture.md`; this file verifies them through checklist items without redefining architecture.

For states: verify the state list owned by `docs/screen-map.md`; cite it, do not re-derive it.

It must not define:
- new product requirements
- new user journeys
- new screens
- wireframe layout changes
- visual design direction
- architecture decisions
- Definition of Done or reusable eval gates
- implementation tasks

Reference source artifacts instead of repeating their full content.

## Proven Mechanics To Use
- Evidence before claims: the checklist must define what evidence proves each important claim.
- Separate UX risks from accessibility risks and visual polish issues.
- Tie every recommendation back to the user goal, workflow, screen state, or accessibility outcome.
- Do not imply WCAG compliance from screenshots or static docs alone. State verification limits.
- Include complete state checks: default, hover, focus, active, disabled, loading, empty, error, success, long-content, offline, permission-denied, and repeat-click where relevant.
- Include responsive reflow and zoom resilience checks.
- Include keyboard access, focus behavior, labels, instructions, errors, target sizes, motion, timing, and state-change communication.
- For QA, compare product scope and behavior against the current validated SDD; treat the engineer-approved integrated prototype recorded in the canonical `Approved Visual Baseline` section of `docs/design-brief.md` as the visual Definition of Done for every user-visible frontend unit; verify technical, accessibility, privacy, legal, and safety boundaries against architecture, guardrails, and applicable standards. Wireframes and the design brief guide uncovered states and reusable rules but do not override the approved visual baseline. Generic defaults apply only where current sources are silent.
- Bind every visual-DoD check to a check ID, active Baseline ID, immutable target hash, route, state, viewport, permitted variance, expected evidence, and result. An explicit recorded operator override replaces the prior visual expectation only for its named scope; unexplained implementation drift never becomes a new default.
- Use the canonical severity glossary from the product sources: P0 is catastrophic actual or imminent severe harm or system-wide unusability; P1 is a broken primary journey, core capability, release invariant, or high-impact requirement with no acceptable workaround for a material supported scope; P2 is a localized but meaningful defect, regression, requirement gap, or visual/interaction drift while the product remains broadly usable or a reasonable workaround exists; P3 is low-impact polish or cosmetic inconsistency without material effect on supported behavior, comprehension, accessibility, trust, or journey completion.
- Assign severity and release effect separately. P0 and P1 are blocking. P2 is blocking only when it violates a source-backed required gate, affects a primary or critical journey, violates an applicable accessibility, security, privacy, legal, payment, or data-integrity requirement, breaks a supported viewport or device, materially changes approved hierarchy or interaction meaning, or combines with related findings into P1 impact. Other P2 findings are advisory. P3 is minor and advisory.
- Release readiness is binary: `passed` when every applicable required gate and every blocking finding is closed; otherwise `blocked` with the blockers named. Advisory P2 and P3 findings may remain with evidence and a concrete follow-up action; they do not create an approval gate.
- Use concrete floors as defaults, overridable by sources: touch targets at least 44x44px where touch interaction matters, with at least 8px gaps; text contrast at least 4.5:1 and at least 3:1 for large text in both light and dark themes; mobile input text at least 16px to prevent iOS auto-zoom; body text usually 14-16px depending on product type; visible focus on all interactive elements; no emoji as icons; no horizontal page overflow; approved motion preserved with non-motion state communication; breakpoints 390, 430, 768, 1280, and 1440px unless sources specify devices.

## Gap-Check
Before writing, verify that sources identify:
- expected product behavior
- critical user journey
- required screens and states
- UX/UI expectations
- target platforms or browsers, if relevant
- acceptance criteria or equivalent success conditions
- architecture-driven verification concerns, if relevant
- DoD/eval gates, if `docs/dod-evals.md` exists
- accessibility target
- source of visual truth for UI comparison, if any
- verification limits, if some checks require implementation rather than docs

If acceptance criteria, required states, or target platforms are missing and cannot be derived from current sources, ask only when the unresolved answer materially changes product scope or a high-risk boundary. Otherwise use the smallest applicable source-backed or documented fallback check, record applicability and evidence limits, and continue.

## Workflow
1. Inspect the input files.
   Re-run the exact repository-observation commands for any codebase-derived status; confirmed code may narrow or close a blocker but cannot add product scope.
2. Derive checks only from current validated SDD artifacts. Before prototype approval, define visual verification against the proposed design contract without pretending that an Approved Visual Baseline exists. After whole-prototype approval, instantiate the visual-DoD checks against the active Baseline ID, immutable visual-target reference/hash, covered route/state/viewport combinations, permitted variance, and referenced prototype without requesting another approval. A changed or superseded Baseline ID, target hash, or recorded operator override invalidates the affected visual checks and requires this artifact to be regenerated before development planning or release evaluation continues.
3. Group checklist items by product behavior, journey, screens, states, UX/UI, responsive, accessibility, and release readiness.
4. Include source references for important checklist groups. `Product Acceptance` items must cite the PRD requirement or user story they verify instead of restating it.
5. Include checks that verify architecture and DoD/eval contracts when `docs/architecture.md` or `docs/dod-evals.md` exist, without redefining those contracts.
6. Include expected evidence for checks that will later require implementation or screenshots.
7. State evidence limits where docs cannot prove runtime behavior.
8. Avoid adding requirements, architecture decisions, DoD rules, or implementation details.
   When a current development plan declares traced prototype reuse and a declared destination exists, verify that the Phase 3 receipt exists at the declared path and that its recorded `copy | adapt | reimplement` strategy matches. Record absence or mismatch as a blocking fidelity finding; never synthesize the receipt and never make the plan a dependency of the pre-design QA node.
9. Before writing the artifact, verify the planned content:
   - Every checklist group traces to a named source file or an explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
   - Clause-level coverage: every distinct observable obligation inside each applicable FR/NFR maps to at least one concrete check or an explicit blocker. Repeating the parent requirement ID is not clause coverage.
10. Create or update only `docs/qa-checklist.md`.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Product Acceptance`, `Screen And State Checks`, `UX/UI Checks`, `Evidence Requirements`, `Evidence Limits`, `Release Readiness`, and `Open Questions`. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. When the baseline is approved, `Source References` records its Baseline ID and immutable target hash. Every checklist item carries `Check ID`, `Severity: P0 | P1 | P2 | P3`, `Release Effect: blocking | advisory`, applicability, source, evidence, and rationale. Every visual-DoD item additionally carries `Baseline ID`, `Target Hash`, `Route`, `State`, `Viewport`, `Permitted Variance`, and `Result: passed | blocked | advisory`. `Release Readiness` must conclude with exactly `passed` or `blocked`, with blockers named when blocked. List omitted optional sections in the Final Report.

```markdown
# QA Checklist

## Source References

## Product Acceptance

## User Journey Checks

## Screen And State Checks

## Wireframe Consistency Checks

## UX/UI Checks

## Visual Regression Checks

## Responsive Checks

## Accessibility Checks

## Interaction And State-Change Checks

## Browser And Device Checks

## Evidence Requirements

## Evidence Limits

## Regression Risks

## Release Readiness

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
