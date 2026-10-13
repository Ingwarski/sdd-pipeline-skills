# Heuristic Usability Review

Canonical H1-H10 vocabulary for applicable human tasks, flows and interfaces. Heuristic review is expert/rule-based evaluation—not representative-user research, visual fidelity, runtime proof or accessibility conformance.

## Ownership and stages

| Stage / artifact | Responsibility |
|---|---|
| Design brief → Heuristic Review | `to-design-brief` defines applicability, intended behavior, coverage and planned evidence. |
| Wireframes → Error And Recovery Contract | `to-wireframes` defines recovery/control/prevention structure (especially H3/H4/H5/H9). |
| Prototype walkthrough | Authorized reviewer records observed candidate findings before whole-design approval; no additional approval. |
| QA → Heuristic Usability Checks | `to-qa-checklist` defines concrete checks and records inspected per-check evidence/results. The named reviewer/runner executes them. |
| DoD → Gate Matrix | `to-dod-evals` **defines**, never executes, `heuristic_usability_review`. The authorized evaluator applies it. |
| Development plan → unit verification | `to-development-plan` maps existing gates/check IDs to units without redefining criteria. |

Use [verification-contract.md](verification-contract.md) for definition versus execution status, gate ownership, evidence classes, severity and release rules. Guardrails owns project evidence policy. Shared definitions stay here; product decisions stay with their artifact owners.

## H1-H10 Heuristic Contract

| ID / principle | Design rule and applicability | Required review evidence | Typical impact |
|---|---|---|---|
| H1 — Visibility of system status | Give timely, understandable feedback for asynchronous, submitted, saved, destructive, navigational or state-changing actions. | State/transition scope; loading/progress/success/error feedback; applicable interface context and runtime evidence when behavior is claimed. | Missing primary/high-risk feedback: P1; localized ambiguity: P2. |
| H2 — Match the real world | Use the user's terminology, mental model and task order across workflows/domain concepts; include meaningful locale differences. | Canonical terms, realistic user-facing copy, task sequence, representative fixture and source references. | Misleading language/model causing primary-task error: P1; localized mismatch: P2. |
| H3 — User control and freedom | Match safe user control and recovery to source-defined actions, risks and consequences. | Control/recovery path, preserved-data behavior, authorization boundary and observed task outcome. | Irreversible/trapping primary flow: P0/P1 by harm; local recovery gap: P2. |
| H4 — Consistency and standards | Equivalent components/actions behave consistently across routes, platforms, input modes and supported locales; follow applicable conventions/accessibility. | Component/state and token references; applicable route/device comparisons; supported input/platform behavior. | Task/accessibility failure: P1; localized inconsistency: P2/P3. |
| H5 — Error prevention | Prevent likely mistakes with constraints, defaults, previews and risk-appropriate confirmation before explaining errors; cover forms, payments, deletion, publication, permissions and costly effects. | Invalid-input path, defaults/constraints, preview/confirmation, destructive boundary and safe recovery. | Preventable high-impact error without recovery: P0/P1; local preventable error: P2. |
| H6 — Recognition rather than recall | Keep needed choices, context, selections and next actions visible in navigation, forms, multi-step/dense tools and returning-user flows. | Labels, current selections, defaults, wayfinding and cross-step context with realistic content. | Missing context causing primary-task error: P1; memory burden: P2/P3. |
| H7 — Flexibility and efficiency | Keep a clear default for intended users; support efficient repeated/expert work where sources justify it. | Default and repeat-task walkthrough; applicable shortcuts/bulk actions and input alternatives; observable step/effort reduction and user-group assumptions. | Missing required high-frequency efficiency: P1/P2; optional customization: P3. |
| H8 — Aesthetic and minimalist design | Each output element serves the task; remove noise that competes with action, hierarchy, comprehension or trust. | Representative output/captures, content priority, critical-action visibility, and applicable density/contrast. | Hidden/weakened critical action or warning: blocking P1/P2 by impact; decoration: P3. |
| H9 — Recognize, diagnose and recover from errors | Explain failure in user language and preserve recoverable work; cover applicable validation, timeout, offline, permission, integration and partial failures. | Cause, preserved work, recovery action/trigger and observed completion, tied to the task context. | Blocked primary recovery or critical data loss: P0/P1; incomplete local guidance: P2. |
| H10 — Help and documentation | Offer concise, contextual, task-oriented help where complexity, novelty, onboarding, permissions, risk or recovery needs it. | Applicable inline guidance, empty-state help, searchable docs or recovery references, tied to the task/interface context. | Missing task-critical help: P1/P2; general documentation polish: P3. |

These are examples, not automatic severity assignments. Apply the source glossary and classify release effect separately. P0/P1 block; P2 blocks only under the critical-impact rules; P3 is advisory. Any inapplicable heuristic needs a source-backed reason.

## Required review record

Resolve the [verification contract's](verification-contract.md) canonical scope, check, result and status fields. Add owner skill, artifact section, validation stage, primary journey and planned coverage. Shared scope IDs are allowed only when every applicable field resolves.

For nonvisual tasks, use its canonical QA `interaction_scope` (`kind: nonvisual`, context and source-backed rationale). Retain task/user group, applicable H1–H10/JOB/UC/evidence and native/platform duties; invent no visual fields. Human-task review remains conditional, including for headless products.

Cover supported environments/input modes, applicable normal/loading/empty/error/success/permission/offline/long-content/recovery states and accessibility-critical actions. Planned coverage is `covered | deferred | not applicable`, never a passed execution result.

## Explicit H7 and H10 decisions

H7: consider shortcuts, bulk actions, repeated-task efficiency, supported input alternatives and customization **only when it reduces effort**. Preserve a clear default for intended users; no additional controls without a source-backed need.

H10: consider contextual help, searchable documentation, actionable empty states, short inline instructions, recovery links and task-oriented assistance. Prefer help at the point of need; do not add a generic documentation dump to a self-explanatory task.

## Error and recovery contract

For every applicable error/recovery state:

> cause → what was preserved → required action or recovery trigger → condition for successful completion

Make the cause understandable, preservation explicit where relevant, the specified recovery safe and meaningful, and success observable. Record a source-backed reason for any inapplicable element. This contract does not add recovery controls absent from product scope.

For each reviewed failure path, exercise its specified trigger and observe the result: activate a recovery control when present, or observe the defined automatic/external transition. Text promising recovery is insufficient. Preserve valid unchanged decisions; renew review when their bound work or state changes. Where controls exist, keep them reachable in their context at the supported content limits. Record scope and remaining limits; a fixture walkthrough is not a product or participant test.
