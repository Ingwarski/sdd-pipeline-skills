---
name: to-product-idea
description: Create or update docs/product-idea.md through a visible, resumable, one-question-at-a-time product-intent intake. Use when a DAS Forge project begins from a short idea, the product idea is absent or materially incomplete, an existing or imported product-idea.md needs validation or handoff, or an explicit operator decision changes upstream product intent before the SDD pipeline runs or resumes.
---
# to-product-idea

## Mission

Turn operator-confirmed intent into the authoritative `docs/product-idea.md` input without inventing the product mandate. Make the interview foreground and inspectable. Reduce operator work by discovering repository facts first, asking only material non-inferable questions, recommending an answer for every question, and asking one question at a time.

This is the Phase 0 artifact owner immediately upstream of `to-sdd-pipeline`. Product Idea Intake is a Product Creation Run, not a Feature Unit and not a design approval.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit language request, otherwise use the language of the latest substantive user message. Use that language for every question, recommendation, rationale, playback, status, final report, and all natural-language headings and prose in `docs/product-idea.md`. English headings shown in this skill are semantic templates, not literal output strings.

For Ukrainian (`uk`), write natural, idiomatic Ukrainian. Keep English only in immutable filenames/paths, code and commands, machine-readable schema or enum values, API/identifier names, proper names or verbatim quotations, and established IT terms such as `SDD Pipeline`; do not leave ordinary headings, prose, or displayed status labels in English and do not produce literal calques. A few English IT terms do not change `working_language`. Keep product content locales separate: an explicitly required product locale may control UI/content examples while intake, specification prose, and reports remain in `working_language`.

## Inputs

Accept any combination of:

- a short product description supplied by the operator;
- an imported or existing `docs/product-idea.md`;
- explicit answers and corrections from the current intake session;
- relevant README, CODEX, repository, product, business, or domain evidence;
- DAS Forge intake state supplied by the `ProductIdeaIntake` runtime adapter.

A pre-existing `docs/product-idea.md` is optional. Support both entry scenarios explicitly:

1. **No existing file:** begin from the operator's short or rough description, ask only unresolved material questions, and create the authoritative file only on the start command.
2. **Existing or imported file:** treat the selected file as the candidate source, validate it before asking anything, skip the interview when its material intent is coherent, and ask only focused questions for actual material gaps, contradictions, or explicit corrections.

Never require the operator to create a file before invoking this skill. Never discard or replace an existing file during intake; preserve it unchanged unless the final operator-confirmed submission requires a new version.

Inspect discoverable sources instead of asking the operator. Repository evidence may establish current facts but cannot authorize new product scope. Never treat a recommendation, inferred preference, or unconfirmed assumption as operator-confirmed intent.

## Output And Ownership

Create or update exactly one human-readable artifact:

- `docs/product-idea.md`

Do not write an incomplete interview draft to the authoritative path. During DAS Forge execution, the `ProductIdeaIntake` runtime adapter owns draft/session persistence under `forge/intake/`; render its current draft in Mission Control. After intent is complete and the operator invokes `Create product idea and start SDD`, atomically create or version `docs/product-idea.md` only when it is absent or confirmed intent changed; otherwise preserve the validated existing file byte-for-byte.

The runtime adapter, not this artifact owner, owns:

- `forge/intake/product-idea.json`;
- `forge/intake/product-idea-handoff.json`;
- operator-input events, browser routing, durable wait/resume, timestamps, and session transport.

Do not create PRD, design, architecture, QA, development-plan, Feature Unit, or production-code artifacts.

## Foreground Intake Contract

When running inside DAS Forge, never bury a question in agent logs or continue silently. Return one typed `ProductIntentQuestion` and yield control to the runtime:

```yaml
status: awaiting_operator_input
question_id: stable-id
working_language: BCP-47 language tag
question: one material question
why_material: why the answer changes product intent
recommendation: preferred answer with concise rationale
answer_type: choice|multi_choice|free_text|confirmation
options: []
target_decision: product-intent field or boundary
affected_artifact: docs/product-idea.md
```

The runtime must persist the request, project it as `Input needed`, display it in the dedicated Product Idea Intake page, keep the live draft and decision coverage visible, and durably pause only the affected Product Creation Run. If the intake page is not active, route the operator's external default browser to the exact pending request. A submitted answer resumes the same session automatically without a separate resume confirmation.

In a direct interactive Codex session without the DAS Forge adapter, ask the same question in the conversation and wait for the answer.

## Question Rules

- Ask exactly one question per turn.
- Include a recommended answer and short rationale.
- Follow only decision branches made relevant by prior answers.
- Walk the relevant decision branch instead of asking a flat questionnaire.
- For each material question, cite the source basis or say no source confirms it.
- State what downstream artifacts or boundaries change if the answer differs.
- After the answer, play back the confirmed decision and consequences before continuing or handing off.
- Ask only when the answer is genuinely non-inferable and materially changes user, problem, outcome, primary journey, MVP boundary, business rule, data/authority boundary, target surface, or another upstream product commitment.
- Inspect source files and the codebase instead of asking for discoverable facts.
- Resolve non-material detail with the smallest reversible source-grounded assumption and show it in the draft coverage view.
- Do not ask for architecture, framework, database, API shape, implementation sequencing, visual styling, or other decisions owned downstream unless the operator explicitly made them part of product intent.
- Do not use a timeout, silence, or model recommendation as consent for a material answer.
- Do not turn answers, draft playback, section completion, or intake resume into approval receipts.

## Intake Coverage

Continue the adaptive interview until the available sources and explicit answers establish, when applicable:

- primary operator/user and their problem;
- desired product outcome and value proposition;
- primary journey or core use case;
- V1/MVP scope and explicit exclusions;
- target surfaces, platforms, locales, or environments that materially constrain the product;
- business rules, data sensitivity, authority limits, and external commitments;
- autonomy, intervention, and high-risk authorization expectations;
- observable success outcomes;
- unresolved risks or decisions that are safe to defer.

There is no fixed question count. Show coverage as `confirmed`, `source-inferred`, `assumed`, or `missing-material` so the operator knows what remains without receiving a large static form.

## Completion And Handoff

Before writing the artifact, validate that:

- every load-bearing statement traces to an explicit answer or named source;
- all submitted operator answers appear without semantic distortion;
- no unresolved contradiction or materially ambiguous product boundary remains;
- primary user/problem/outcome and V1 boundary are explicit;
- assumptions remain labeled and reversible;
- downstream architecture, design, DoD, QA, and implementation ownership is preserved.

Present the complete draft in Mission Control. The operator action `Create product idea and start SDD` submits the intent and starts automation; it is not an approval gate. On that command:

1. atomically create or version `docs/product-idea.md` when it is absent or confirmed intent changed; otherwise preserve the validated existing file byte-for-byte;
2. validate that final file and compute its content hash;
3. return the hash, source mode, `working_language`, its selection source, any distinct product content locales, intake/session ID, answered decision IDs, assumptions, unresolved non-blocking questions, and submission timestamp to the runtime;
4. let the runtime write `forge/intake/product-idea-handoff.json` and dispatch `to-sdd-pipeline` automatically.

Use `source_mode: existing-file` for a repository-existing file, `source_mode: imported` for an externally supplied file, and `seed` or `interview` for a no-file path as applicable.

An existing or imported product idea may use the same handoff after validation and any required focused questions. Do not force a full interview when the artifact already contains coherent material intent.

## Change And Resume Rules

- Restore the exact current question, answers, decision branches, draft version, and assumptions after restart.
- Detect operator edits to an existing product idea by content hash and preserve them as authoritative input.
- When an accepted answer changes, create a new idea version; never discard prior answer provenance.
- When downstream SDD work discovers a missing material product decision, route one scoped question back through the same Product Idea Intake UI. After the answer, re-run this owner, version `docs/product-idea.md`, and let `to-sdd-pipeline` invalidate and regenerate only transitive dependents.
- Never require a separate `Resume`, file approval, or section approval after the operator answers.

## Recommended Artifact Structure

Use the smallest structure that captures confirmed intent. Preserve an existing coherent structure when updating. Typical coverage is:

```markdown
# Product Idea

## Positioning
## Target User And Problem
## Product Outcome
## Core Workflow
## V1 Scope
## Explicit Exclusions
## Product Principles And Authority Boundaries
## Success Outcomes
## Assumptions And Open Questions
## Source Notes
```

Do not add empty ceremonial sections.

## Final Report

Return:

- `Result`
- `Created/Updated File`
- `Working Language And Product Content Locales`
- `Product Idea Hash`
- `Source Mode`
- `Confirmed Decisions`
- `Assumptions`
- `Open Questions`
- `Intake Handoff`
- `Next Skill: to-sdd-pipeline`

When awaiting an answer, return only the typed `ProductIntentQuestion` plus the persisted run/request identifiers required by the runtime.
