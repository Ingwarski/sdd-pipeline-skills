---
name: to-sdd-prd
description: Create or reconcile docs/prd.md from validated product intent, defining product requirements, use cases and observable acceptance outcomes.
---
# to-sdd-prd

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve the link from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs

Required before starting: current operator-confirmed `docs/product-idea.md`. DAS Forge also supplies its matching intake handoff/hash. If absent or materially incomplete, return to `to-product-idea`; do not invent the mandate.

Optional grounding: README, domain glossary, ADRs/product documentation, explicit decisions and relevant code/routes/schemas/tests/CI/design-system/runtime evidence. Existing code confirms facts, not new scope.

Downstream context, UX, architecture, DoD, QA and planning artifacts are not prerequisites or authorities for new product intent.

## Output and ownership

Write only `docs/prd.md`. Own problem/outcome, product boundary/value, actors/stories, product-level use cases, FR/NFR requirements, product-level implementation/testing constraints, acceptance scenarios, exclusions and source/open questions.

Do not create detailed journeys, screens/states, layouts, visual systems/baselines, technical architecture, reusable gates, concrete QA items or implementation units. No issue-tracker publication, labels, messages or other external effects.

## Workflow

1. Read the complete product idea and relevant current evidence. Map sources to requirements before drafting.
2. Define the user problem, solution/workflow, actors, product boundary and observable success.
3. Map every material `JOB-*` to one or more `UC-*` product use cases; record unresolved relationships explicitly.
4. Write stable sequential user stories: As a <role>, I want <capability>, so that <outcome>. Cover the boundary without duplicate filler.
5. Keep FR/NFR IDs stable. Split each compound requirement into independently observable sub-obligations; a parent ID alone is not complete coverage.
6. Record only source-backed product-level implementation decisions. Architecture and build order remain downstream.
7. Define observable test seams and minimum end-to-end acceptance scenarios. Prefer the highest practical external seam; tests verify the specification, not redefine it.
8. Preserve source-backed design-first, autonomy, single whole-design approval, high-risk authorization and prototype-to-production trace rules. Static docs/prototypes do not prove runtime functionality.
9. Resolve contradictions through the product-idea owner. In pipeline mode return one visible `ProductIntentQuestion` for material gaps; after an answer, upstream intent is versioned before this owner resumes.
10. Validate every requirement, clause and use-case path against sources; write only the PRD and return control without asking whether to continue.

When relevant, carry the source P0–P3 glossary and separate severity from release effect. Preserve source-approved motion; do not import generic animation removal or an unrequested reduced-motion variant. Use precise schema/state examples only when more useful than prose; avoid brittle paths and snippets.

## Use-case contract

Each materially distinct `UC-*` resolves: canonical name; JOB references; primary/supporting actors; trigger; goal; preconditions; numbered actor/system success path; alternate and error/recovery paths; postconditions; authority/privacy/data boundaries; linked FR/NFR obligations and acceptance scenarios.

Use cases own system-facing behavior, not visual layout or implementation. One case may cover several stories; one job may require several distinct cases. Journey, screen map and QA reference IDs rather than copy these paths. No separate use-case document.

## Artifact coverage

Preserve equivalent existing/localized headings. Core coverage: Problem Statement; Solution/Core Workflow; Product Boundary; Use Cases; User Stories; product-level Implementation Decisions; Testing Decisions and Minimum End-To-End Acceptance Scenarios; Out Of Scope; Open Questions; Source Notes.

No unsupported scope or empty template sections. State a source-backed reason when a required concern does not apply.

## Return

Report file, source/clause coverage, changed product decisions and open questions. Follow the shared provenance contract. Next-owner metadata is advisory, not a continuation approval.
