---
name: to-product-idea
description: Create or validate docs/product-idea.md through visible, resumable, one-question-at-a-time discovery of product intent, jobs and design-critical user needs.
---
# to-product-idea

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve the link from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Mission and inputs

Turn operator-confirmed intent into `docs/product-idea.md`, the Phase 0 input to SDD. Intake is a Product Creation Run, not a Feature Unit or a design approval.

Accept a rough description, an existing/imported idea, explicit answers/corrections, relevant README/CODEX or project evidence, and saved intake state. A product-idea file is **optional at entry**.

- No file: discover only unresolved material intent; write the authoritative file on the start command.
- Existing/imported file: validate it first. Skip a redundant interview if coherent; ask only about actual material gaps, contradictions or corrections. Preserve unchanged content byte-for-byte.
- Inspect discoverable facts. Repository evidence cannot authorize new scope, and a recommendation is not confirmed intent.

## Ownership

Write only `docs/product-idea.md`; never put an incomplete draft there. The DAS Forge `ProductIdeaIntake` adapter owns draft/session persistence, browser routing, input events and receipts under `forge/intake/`, including `product-idea.json` and `product-idea-handoff.json`.

The runtime shows the live draft and decision coverage in Mission Control. This owner creates no PRD, UX, architecture, QA, plan, Feature Unit or production code.

## Visible questioning

Ask one material question per turn with a recommendation, rationale, source basis (or its absence), affected downstream decisions and a brief playback after the answer. Follow the relevant branch, not a fixed questionnaire. Silence, timeout and recommendations never supply consent.

In DAS Forge, return one request and yield:

```yaml
status: awaiting_operator_input
question_id: stable-id
working_language: BCP-47 language tag
question: one material question
why_material: affected product intent
recommendation: preferred answer and rationale
answer_type: choice|multi_choice|free_text|confirmation
options: []
target_decision: intent field or boundary
affected_artifact: docs/product-idea.md
```

The runtime persists it as `Input needed`, displays it in the foreground intake, routes the external default browser to the request when needed, and resumes the same session automatically after the answer. Standalone, ask in the conversation and wait.

## Design-ready discovery

Establish the primary user/problem, outcome/value, core workflow, V1/MVP scope and exclusions, target surfaces/locales, business rules, data/authority boundaries, external commitments, autonomy and observable success.

Where sources leave a design-critical gap, explore only relevant branches:

1. **Job and progress:** what is the person trying to accomplish?
2. **Situation and trigger:** what starts the need, and why now?
3. **Outcome and alternatives:** what is success, and how is this done today?
4. **Conditions:** device/environment, time, attention, accessibility, language, connectivity, interruption and recovery.
5. **Trust and risk:** hesitation, highest-cost mistake, reversibility and confirmation boundaries.
6. **Content and evidence:** information, proof or explanation needed to decide or act.
7. **Success signal:** observable completion/progress, not merely viewing a screen.

Capture functional, emotional or social needs when they affect motivation, trust, wording, interaction or priority. Do not prescribe screens, style, components, frameworks, databases or build order unless explicitly part of product intent; those decisions belong downstream.

Show coverage as `confirmed | source-inferred | assumed | missing-material`. Record safe non-material assumptions and deferred risks. A missing material primary job remains a question, not an invented feature.

## Jobs To Be Done

Own the canonical `JOB-*` IDs. Each materially distinct job resolves:

- Statement: When <situation>, I want <progress>, so I can <outcome>.
- Primary user; trigger/urgency; current alternative.
- Relevant functional/emotional/social dimension and design conditions.
- Observable success signal; source/evidence; confidence.
- Core-workflow/use-case candidate reference or explicit open relationship.

Jobs explain why users act. Do not duplicate user stories, system paths or the journey. The PRD later owns `UC-*` product use cases; no separate JTBD artifact is created.

## Completion, change and handoff

1. Check that every load-bearing statement has a named source or explicit answer, all answers retain their meaning, and no material contradiction or scope ambiguity remains.
2. Verify primary user/problem/outcome, V1 boundary and all material JOBs. Each primary job maps to a core workflow/use-case candidate or an explicit unresolved relationship.
3. Present the complete draft. `Create product idea and start SDD` is an execution command, not approval.
4. On that command, atomically create/version the final file only when absent or confirmed intent changed; otherwise keep its bytes. Validate and hash the final content.
5. Return the hash, source mode, language/selection source, separate product locales, intake/session ID, answered decision IDs, assumptions, non-blocking questions and submission time. The runtime writes the handoff receipt and dispatches `to-sdd-pipeline`.

Use `source_mode: existing-file | imported | seed | interview` accurately. Restore the exact pending question, answers, branch, draft and assumptions after interruption. Detect user edits by content hash. Preserve earlier answer provenance when intent changes.

A downstream material gap returns through the same intake, updates this artifact through this owner, and invalidates only affected dependents. Do not require another Resume, file approval or section approval.

## Artifact and return

Use the smallest coherent structure covering positioning, target user/problem, outcome, Jobs To Be Done, core workflow, V1 scope, exclusions, principles/authority, success, assumptions/open questions and source notes. Preserve an existing equivalent structure; no empty ceremony.

Return file/hash, source mode, working language/product locales, confirmed JOBs and changed decisions, assumptions/questions and handoff to `to-sdd-pipeline`. While waiting, return only the typed question and required persisted request/run IDs.
