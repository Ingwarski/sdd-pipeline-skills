---
name: to-sdd-prd
description: Create or update docs/prd.md from docs/product-idea.md and current project evidence. Use when the user wants a file-based product requirements document, the first domain artifact in an autonomous SDD pipeline, or a PRD reconciled with an updated product idea.
---
# to-sdd-prd

## Universal SDD Rule

AI is not the source of truth. `docs/product-idea.md`, accessible project evidence, and explicit user answers are the source of truth. Preserve source terminology and intent. Do not silently invent scope, architecture, policy, or external commitments.

If information is discoverable in the repository or named sources, inspect it instead of asking. Resolve non-material gaps and pre-approval design ambiguity with the smallest reversible source-grounded choice and record them. Use a focused grill-me question only when a genuinely non-inferable answer materially changes product scope or a high-risk boundary. Playback is not an approval gate.

Grill-me gap-check style: when a material question is necessary, walk the relevant decision branch instead of asking a flat questionnaire. Ask exactly one question, state the recommended answer and rationale, cite the source basis or say no source confirms it, state what downstream artifacts or boundaries change if the answer differs, and after the answer play back the confirmed decision and consequences before continuing or returning to the orchestrator.

When invoked by `to-sdd-pipeline`, never surface that question only in background logs or a hidden agent session. Return one typed `ProductIntentQuestion` to the orchestrator so DAS Forge can persist it as `Input needed` and display it through the foreground Product Idea Intake UI. After the explicit answer, let `to-product-idea` version the upstream artifact when the answer changes product intent, then resume automatically. In standalone interactive use, ask the same one question directly.

## Input

Require:
- `docs/product-idea.md`

The file must contain current operator-confirmed product intent. In DAS Forge, require the matching Product Idea Intake handoff/hash supplied by the orchestrator. If the file is absent or materially incomplete, return control to `to-product-idea`; do not synthesize the mandate inside the PRD owner.

Read when present and relevant:
- `README.md`
- domain glossary or terminology sources
- ADRs and existing product documentation
- codebase structure, routes, schemas, tests, CI, design-system evidence, and runtime configuration
- explicit decisions in the current conversation

Repository evidence can confirm current implementation facts. It cannot authorize new product scope.

## Output

Create or update exactly one file:
- `docs/prd.md`

Do not publish to an issue tracker, create issues, apply labels, send messages, or perform another external side effect. Those are separate opt-in actions outside this artifact owner.

## Artifact Boundary

`docs/prd.md` owns:
- problem and product outcome
- product boundary and value proposition
- actors and user stories
- functional and non-functional product requirements
- design-first workflow and approval semantics when source-backed
- product-level implementation constraints and decisions
- product-level testing decisions and acceptance scenarios
- explicit out of scope
- open questions and source notes

It must not own:
- detailed user-journey stages
- screen/state inventory
- wireframe structure
- visual design system or Approved Visual Baseline
- technical architecture details better owned by `docs/architecture.md`
- reusable DoD/eval gates
- per-check QA details
- implementation units or build order

Reference downstream owners instead of prematurely writing their artifacts inside the PRD.

## Proven Mechanics

- Describe the problem and solution from the user's perspective.
- Make user stories extensive enough to close the product boundary, but do not duplicate the same requirement as filler.
- Use stable sequential story IDs and the form `As a <role>, I want <capability>, so that <outcome>`.
- Keep each FR/NFR traceable at clause level. When one numbered requirement contains multiple independently testable obligations, enumerate those obligations explicitly under that stable ID; downstream appearance of the parent ID alone must not be mistaken for complete coverage.
- Separate product behavior from implementation constraints and testing decisions.
- Prefer externally observable test seams and the highest practical seam. Tests verify the agreed product; they do not become the source of product truth.
- Preserve the product's autonomy model. Do not add approval gates unless the source requires them or the action crosses a high-risk authorization boundary.
- For a design-first product, distinguish the pre-design SDD baseline, prototype comparison, whole-design approval, and post-approval production implementation.
- When the source uses P0-P3 findings, carry one formal severity glossary into the PRD and keep severity separate from blocking/advisory release effect.
- When the source makes an approved prototype authoritative, state explicitly whether it is the visual Definition of Done for user-visible frontend work and preserve any source-backed prototype-to-production trace contract.
- Do not import a generic reduced-motion mode, animation cap, or automatic motion removal/simplification when the product idea instead makes approved motion part of its visual baseline.
- Do not include brittle file paths or code snippets unless a small source-backed state machine, schema, or type shape expresses a decision more precisely than prose.
- Do not claim that static documentation, a screenshot, or a prototype proves runtime functionality.

## Gap Check

Before writing, resolve:
- target user and problem
- product outcome and value proposition
- mandatory workflow and boundaries
- in-scope and out-of-scope capabilities
- autonomy, approval, and high-risk authorization semantics
- provider, platform, integration, or deployment constraints explicitly required by sources
- observable acceptance outcomes and test seams

Ask only when a missing answer materially changes product scope or a high-risk boundary. Otherwise use the smallest reversible source-grounded choice, record it, and continue.

## Workflow

1. Read `docs/product-idea.md` completely.
2. Inspect relevant current project evidence and preserve established terminology.
3. Build a source-to-requirement map before drafting.
4. Define the product boundary, actors, workflow, and success outcomes.
5. Write sequential user stories that cover the source without adding unsupported scope.
6. Capture only source-backed product-level implementation decisions; defer architecture details to their owner.
7. Define observable testing decisions, evidence limits, and minimum end-to-end acceptance scenarios.
8. Reconcile contradictions against the product idea. Stop only if the unresolved choice materially changes scope or a high-risk boundary.
9. Validate that every load-bearing requirement and every distinct obligation inside it traces to the product idea, project evidence, or an explicit answer. Split compound prose into explicit sub-obligations without inventing new behavior.
10. Create or update only `docs/prd.md`.

When invoked by `to-sdd-pipeline`, return control immediately after validation so the orchestrator can hash the artifact and dispatch downstream owners. Do not ask the user whether to continue.

## Required Output Structure

Use the smallest structure that fully represents the source. Preserve equivalent established headings in an existing PRD; the following is a semantic coverage model, not a demand to rename sections or duplicate content:

```markdown
# Product Requirements Document

## Problem Statement

## Solution

## Product Boundary And Operating Model

## Core Workflow

## User Stories

## Implementation Decisions

## Testing Decisions

## Minimum End-To-End Acceptance Scenarios

## Out Of Scope

## Open Questions

## Source Notes
```

Core semantic coverage is problem, solution/workflow, user stories, product-level implementation decisions, testing/acceptance decisions, out of scope, open or deferred decisions, and source/provenance notes. These may be nested under equivalent headings such as `Further Notes`. Optional subsections may be added only when the product idea supports them. A section may state `Not applicable: <source-backed reason>`; do not add filler.

## Final Report

Return:
- `Result`
- `Created/Updated File`
- `Source Coverage`
- `Confirmed Product Decisions`
- `Open Questions`
- `Next Recommended Skill`

When orchestrated, `Next Recommended Skill` is advisory metadata for the manifest, not a request for user confirmation.
