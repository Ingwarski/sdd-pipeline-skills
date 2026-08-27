---
name: to-development-plan
description: Use when the current validated product, UX, architecture, DoD/eval, guardrail, and QA SDD artifacts plus the engineer-approved integrated design baseline exist and the user wants a development plan, implementation plan, build order, task breakdown, or verification plan. SDD readiness is not another human approval.
---
# to-development-plan

## Universal SDD Rule
AI is not the source of truth. Source files and explicit user answers are the source of truth. Mirror source terminology exactly; when sources use conflicting terms for one concept, do not pick silently - ask or flag it in `Open Questions`, then record the canonical term and aliases to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit request, otherwise use the language of the latest substantive user message. Use it for all questions, playbacks, reports, and natural-language headings and prose in the owned artifact. English template headings are semantic labels, not literal output. For Ukrainian (`uk`), write idiomatic Ukrainian and keep English only in immutable filenames/paths, code/commands, machine values, API/identifier names, names/quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary English prose or calques. Keep explicit product content locales separate from the specification language.

When a current validated `docs/canonical-terms.md` exists, use it as vocabulary authority for unit names, roles, domain objects, states, actions, interfaces, API/data contracts, and user-facing labels. It cannot create requirements or silently rename established technical identifiers. Use confirmed facts from `docs/project-context.md` only when they materially affect implementation; its assumptions remain assumptions.

If information is missing from the source files, inspect available sources and the codebase first. Use a focused grill-me gap-check before writing only when the answer is genuinely non-inferable and materially changes product scope or a high-risk boundary. Resolve the decision tree one branch at a time, ask one question at a time, and include a recommended answer. For all other gaps, including pre-approval design ambiguity, use the smallest reversible source-grounded choice, record it, and continue. Do not turn guesses into facts.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

Create only the final output file. Do not write unverified assumptions into the artifact. Before creating or updating `docs/development-plan.md`, every implementation unit must be source-backed, user-confirmed, or left in `Open Questions`.

If a gap-check ran, or if the skill synthesized decisions not fully determined by source files, play back the resolved decisions in a pithy summary and continue with the smallest reversible, source-grounded choice unless the missing answer materially changes product scope or a high-risk boundary. Playback is not an approval gate. If planning would change the Approved Visual Baseline, record `baseline_change_required` for the orchestrator; planning must not request or grant design approval itself.

Never write a repository-state observation as a bare fact. Record `<claim> — observed <ISO date> via <command>` plus the exact observed paths and content hashes in the orchestrator's scoped repository observation. Never assert that something does not exist without naming the command that would prove it still does not.

## Input
Read:
- `README.md`, if present
- `docs/project-context.md`, when present; in a full pipeline run require its current validated manifest entry
- `docs/canonical-terms.md`, when present; in a full pipeline run require its current validated manifest entry
- `docs/prd.md`
- `docs/user-journey.md`
- `docs/screen-map.md`
- `docs/wireframes.md`
- `docs/design-brief.md`
- the canonical `Approved Visual Baseline` section inside `docs/design-brief.md` and the selected prototype artifacts it references; for a UI product, `Status: approved` and a stable Baseline ID are required before production implementation units are created
- `docs/architecture.md`
- `docs/dod-evals.md`
- `docs/guardrails.md`
- `docs/qa-checklist.md`
- `skills/to-sdd-pipeline/references/heuristic-usability-review.md`, when mapping H1-H10 review evidence to user-visible units

## Output
Create or update exactly one artifact:
- `docs/development-plan.md`

Do not modify unrelated files.

## Artifact Boundary
`docs/development-plan.md` owns:
- implementation units
- build order
- dependencies
- source references per unit
- acceptance checks per unit
- verification steps
- risk sequencing
- handoff notes for implementation
- traceability and verification mapping for representative-user validation of applicable critical user-visible units
- traceability and verification mapping for `heuristic_usability_review` of applicable user-visible units
- approved-baseline visual-DoD mapping and permitted visual variance per user-visible unit
- planned prototype-to-production source/destination mapping and promotion boundaries when prototype code exists
- frontend/backend interface contracts and integration seams for cross-layer units
- implementation consequences of relevant confirmed project context and canonical vocabulary, expressed through existing source references rather than duplicated context prose

It must not define:
- new product requirements
- new user journeys
- new screens
- wireframe changes
- visual design changes
- architecture decisions
- Definition of Done or reusable eval gates
- QA checklist details beyond references

This is an SDD development plan. It may include tests and verification, but it must not reframe the workflow as TDD-first unless the source documents explicitly require that.

## Proven Mechanics To Use
- Start from source-backed scope, not engineering imagination.
- Map files or modules before tasks when a codebase exists. Follow established patterns before proposing new abstractions.
- Break work into small implementation units with clear ownership, dependency order, acceptance checks, and verification evidence.
- Avoid placeholders: no TBD, TODO, "handle edge cases", "write tests for this", or undefined future decisions.
- Every unit needs source references, work items, acceptance checks, and verification.
- Evidence before completion: the plan must say what proves each unit is done.
- SDD-first: tests and verification support the agreed spec; they do not become the source of product truth.
- Preserve the upstream trace `JOB-* -> UC-* -> journey stage -> screen/state` in every user-visible unit. When `representative_user_task_validation` applies, map the unit to the corresponding QA usability check and validation evidence; do not invent participants, findings, or research results in the plan.
- When `heuristic_usability_review` applies, map the unit to its relevant H1-H10 IDs, QA check IDs, routes/states/viewports, and evidence status. The plan references the gate and its checks; it does not redefine heuristic criteria or invent findings.
- Use the PRD and journey artifacts for behavior and scope, and treat the Approved Visual Baseline as the visual Definition of Done for visual composition, interaction detail, and frontend presentation in every user-visible frontend unit. Architecture, guardrails, and applicable standards remain hard technical and risk boundaries. Do not reinterpret or re-approve the design inside the development plan. An explicit recorded operator correction overrides the prior visual expectation only for its named scope.
- Treat image-to-code or equivalent prototype output as design evidence and an optional frontend seed, not as proof of production auth, persistence, backend/API, integrations, security boundaries, or exhaustive edge-case behavior. When prototype code will be reused, define a traced promote/diff contract and keep Phase 3 frontend, backend, and integration responsibilities explicit.
- A traced promote/diff contract freezes the approved candidate source root/tree hash, names only the prototype source paths to reuse, maps each to an explicit production destination with `copy | adapt | reimplement`, records the production base commit and allowed adaptations, and lists every production capability missing from the prototype. The Phase 3 runner applies that bounded map, derives the actual Git diff, and writes `forge/runs/{unit_id}/{run_id}/prototype-promotion.json`; the planning skill never writes that receipt and the implementation agent's free-form report cannot substitute for it.
- The `PrototypePromotionReceipt` must include schema version, promotion/unit/run IDs, development-plan reference/hash, Baseline ID and target hash, candidate/version, prototype source root/tree hash, path mappings and source/destination hashes, base/head commits, changed paths and patch hash, declared adaptations/variances, QA check IDs, visual evidence, verification status, and timestamp. It is machine evidence, not another human gate.
- Treat `docs/project-context.md` and `docs/canonical-terms.md` as contextual sources, not as owners of product requirements, architecture, design, guardrails, DoD, or QA rules. Apply them only when confirmed users/roles, platform/runtime/deployment targets, localization, privacy or operational constraints, external dependencies, risks, or canonical vocabulary materially affect an implementation unit, sequencing, interface, acceptance check, verification step, or handoff.
- Do not reproduce personas, product summaries, pain points, glossaries, or descriptive context in the plan. Cite the exact relevant section or term in the existing `Source References` and write only its implementation consequence. Ignore stale, superseded, descriptive, unrelated, or unconsumed entries and never promote an assumption to a fact.
- A missing context file does not block standalone planning when every implementation-relevant fact and term is already present in the required validated SDD. In a full pipeline run, use the validated bundle supplied by the orchestrator. If it conflicts materially with another owner artifact, return the conflict for upstream reconciliation rather than deciding it inside the plan.
- When the orchestrator records fragment-level context provenance, regenerate only plan units that consume a changed context fact or canonical term. Unconsumed prose changes do not invalidate the plan.
- Do not turn the plan into tiny commit choreography unless the user asks.

## Gap-Check
Before writing, verify that sources identify:
- current validated product scope
- current validated screens and states
- approved visual-baseline status, Baseline ID, selected candidate/version, immutable visual-target reference/hash, prototype references, covered screens/states/viewports, and permitted variance for UI products
- UX/UI expectations
- implementation constraints or stack, if available
- architecture constraints, if available
- DoD/eval gates, if available
- acceptance or QA criteria
- representative-user task validation plan, applicable critical-flow status, and available evidence, when defined upstream
- H1-H10 heuristic coverage plan, applicable user-visible scope, QA check IDs, and available evidence, when defined upstream
- required verification commands, if available
- existing architecture, file structure, or component system when a codebase exists
- deployment or runtime constraints that affect build order
- optional presentation-layer mockup-code reuse policy and every missing production capability, when code-backed interactive mockup material exists; never treat the mockup as an application implementation
- frozen prototype source root/tree hash, planned source-to-destination mapping, production base reference, allowed adaptation strategy, and required promotion-receipt path for every traced reuse
- whether confirmed project-context facts or canonical terms materially affect implementation; absence of a relevant effect is valid and does not require filler

If stack, constraints, dependencies, or verification expectations are missing, first re-invoke the owning upstream artifact skill. Ask only when the unresolved answer materially changes product scope or a high-risk boundary. Otherwise use the smallest reversible source-compatible plan seam, record the dependency, and continue.

## Workflow
1. Inspect the input files.
2. Extract implementation scope only from current validated SDD artifacts. When the context bundle exists, classify its potentially relevant entries as `applied`, `reference-only`, `irrelevant`, or `conflict`; use canonical names consistently, cite only applied/reference-only fragments, and do not duplicate descriptive context.
3. Resolve the canonical `Approved Visual Baseline` section in `docs/design-brief.md` and verify `Status: approved`, its stable Baseline ID, selected candidate/version, immutable visual-target reference/hash, approval receipt, and referenced prototype artifacts. For a UI product, stop before creating production units if this whole-baseline approval is absent; do not ask for any additional design approval. A changed or superseded Baseline ID invalidates affected plan units and requires the QA checklist plus those units to be regenerated before execution continues. If any unit's declared production destination already exists, verify its promotion receipt and recorded strategy before re-issuing the plan; record an absent receipt or `copy | adapt | reimplement` mismatch as an open finding for the DoD owner, not as a reconstructed historical receipt.
4. Inspect the codebase structure if implementation will happen in an existing project.
5. Use `docs/architecture.md` as the architecture source of truth; do not re-decide architecture inside the plan.
6. Use `docs/dod-evals.md` as the Definition of Done and eval-gate source of truth; do not redefine gates inside the plan.
7. Map likely files, modules, routes, components, services, and tests before defining tasks.
8. Break work into implementation units that can be built and verified.
9. Order units by dependency and user-value sequence.
10. Attach behavioral SDD references and, for every user-visible unit, Approved Baseline ID, target hash, covered screens/states/viewports, design contract, permitted variance/operator override, and the `approved_visual_baseline_fidelity` verification reference. For every applicable user-visible unit, attach the relevant `JOB-*`/`UC-*` references and `heuristic_usability_review` verification reference, including H1-H10 coverage, QA check IDs, applicable routes/states/viewports, and evidence status. For every applicable critical or consequential user-visible unit, also attach the `representative_user_task_validation` verification reference, including the upstream task, success criterion, applicability, and evidence status. For backend-only units, state whether the unit enables user-visible states, data, or actions. When prototype code exists, identify whether the unit reuses none of it or uses traced promote/diff; for traced reuse record the frozen source root/tree hash, source-to-destination path map, `copy | adapt | reimplement` strategy, production base commit, allowed adaptations, receipt path, and every production capability still implemented outside the prototype. For every cross-layer or independently parallelizable frontend/backend unit, name interfaces produced and consumed, API/data-contract references, ownership, compatibility expectations, and integration verification.
11. Include verification steps derived from `docs/qa-checklist.md` and `docs/dod-evals.md`, including the concrete heuristic checks/evidence and the representative-user validation check/evidence when those gates apply.
12. Self-review coverage: every distinct obligation inside each PRD requirement and every screen and state in `docs/screen-map.md` maps to an implementation unit or to Out Of Scope / Open Questions with a reason; the Approved Visual Baseline maps to every user-visible unit; architecture constraints from `docs/architecture.md` and DoD/eval gates from `docs/dod-evals.md` map to verification or sequencing notes; cross-layer interfaces have both a producer and consumer; unit names and references follow applicable canonical terms; every applied context fact has a concrete implementation consequence; assumptions were not promoted to facts; no context prose was duplicated; no placeholders remain. For traced reuse, the planned strategy, existing destination shape, and any current receipt agree; a parent requirement ID or a declared `adapt` label alone is not evidence of coverage or actual adaptation.
13. Avoid tiny commit choreography as the main teaching frame.
14. Avoid adding product scope, architecture decisions, DoD rules, or design decisions.
15. Before writing the artifact, verify the planned content:
   - Every implementation unit traces to a named source file or an explicit user answer, or it is moved to `Open Questions`.
   - No content belongs to another artifact's ownership per the Artifact Boundary.
   - No placeholder text and no generic filler written to satisfy the template.
16. Create or update only `docs/development-plan.md`.

## Required Output Structure
Use this structure:

Required contract sections are `Source References`, `Implementation Strategy`, `Implementation Units`, `Dependency Order`, `Verification Plan`, `Out Of Scope`, and `Open Questions`. `Prototype Promotion Plan` is required when any unit uses traced promote/diff and omitted otherwise. Optional sections may be omitted when sources give them no content. Required sections may use a single line `Not applicable: <reason>` only when the reason is source-backed. Never fill a section to satisfy the template. List omitted optional sections in the Final Report.

```markdown
# Development Plan

## Source References

## Implementation Strategy

## Codebase Map

## Implementation Units

## Dependency Order

## Verification Plan

## Visual And UX Verification

## Prototype Promotion Plan

## Risks And Sequencing Notes

## Out Of Scope

## Open Questions
```

For each implementation unit include:
- `Unit`
- `Purpose`
- `Source References`
- `Job And Use-Case References`, for user-visible units
- `Depends On`
- `Work Items`
- `Acceptance Checks`
- `Verification`
- `Delivery Layer: frontend | backend | full-stack | integration | infrastructure`
- `Approved Baseline ID`, for user-visible units
- `Immutable Visual Target Hash`, for user-visible units
- `Baseline Screens States And Viewports`, for user-visible units
- `Design Contract And Permitted Variance`, for user-visible units
- `Operator Visual Overrides`, when present for the unit scope
- `Visual Fidelity Verification: approved_visual_baseline_fidelity`, for user-visible units
- `Heuristic Usability Verification: heuristic_usability_review`, for applicable user-visible units
- `Heuristic IDs And QA Check IDs`, when `heuristic_usability_review` applies
- `Representative User Validation: representative_user_task_validation`, when applicable
- `Validation Task And Success Criterion`, when `representative_user_task_validation` applies
- `Validation Evidence`, when validation has already run
- `Baseline Impact: none | user-visible states/data/actions enabled`, for backend-only units
- `Prototype Reuse: none | traced promote/diff`, when prototype code exists
- `Prototype Source Root And Tree Hash`, for traced promote/diff
- `Prototype To Production Path Map`, for traced promote/diff, with `source`, `destination`, and `strategy: copy | adapt | reimplement`
- `Production Base Commit`, for traced promote/diff
- `Allowed Prototype Adaptations`, for traced promote/diff
- `Required PrototypePromotionReceipt: forge/runs/{unit_id}/{run_id}/prototype-promotion.json`, for traced promote/diff
- `Production Capabilities Added Beyond Prototype`, when prototype code exists
- `Interfaces Produced`, for cross-layer or independently parallelized units
- `Interfaces Consumed`, for cross-layer or independently parallelized units
- `API/Data Contract References`, for cross-layer or independently parallelized units
- `Interface Owner`, for cross-layer or independently parallelized units
- `Compatibility Expectations`, for cross-layer or independently parallelized units
- `Integration Verification`, for cross-layer or independently parallelized units

Do not add a mandatory context field to every unit. Add an exact `docs/project-context.md` section or `docs/canonical-terms.md` term under the existing `Source References` only when that unit consumes it; otherwise omit it.

## Final Report
Return:
- `Result`
- `Created/Updated File`
- `Confirmed Facts And Constraints`
- `Omitted Optional Sections`, if any
- `Open Questions`
- `Next Recommended Action`
- `Next Recommended Skill`
