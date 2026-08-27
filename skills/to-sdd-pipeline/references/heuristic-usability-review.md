# Heuristic Usability Review

Canonical H1-H10 vocabulary for applicable flows, screens, states, routes and viewports. Heuristic review is expert/rule-based evaluation—not representative-user research, visual fidelity, runtime proof or accessibility conformance.

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
| H1 — Visibility of system status | Give timely, understandable feedback for asynchronous, submitted, saved, destructive, navigational or state-changing actions. | State/transition scope; loading/progress/success/error feedback; route/state/viewport and runtime evidence when behavior is claimed. | Missing primary/high-risk feedback: P1; localized ambiguity: P2. |
| H2 — Match the real world | Use the user's terminology, mental model and task order across workflows/domain concepts; include meaningful locale differences. | Canonical terms, realistic user-facing copy, task sequence, representative fixture and source references. | Misleading language/model causing primary-task error: P1; localized mismatch: P2. |
| H3 — User control and freedom | Provide safe cancel, exit, back, undo, revision and recovery in forms, navigation, multi-step/destructive/external actions and interruptions. | Control/recovery path, preserved-data behavior, authorization boundary and observed task outcome. | Irreversible/trapping primary flow: P0/P1 by harm; local recovery gap: P2. |
| H4 — Consistency and standards | Equivalent components/actions behave consistently across routes, platforms, input modes and supported locales; follow applicable conventions/accessibility. | Component/state and token references; cross-route/device comparisons; keyboard/touch/platform behavior. | Task/accessibility failure: P1; localized inconsistency: P2/P3. |
| H5 — Error prevention | Prevent likely mistakes with constraints, defaults, previews and risk-appropriate confirmation before explaining errors; cover forms, payments, deletion, publication, permissions and costly effects. | Invalid-input path, defaults/constraints, preview/confirmation, destructive boundary and safe recovery. | Preventable high-impact error without recovery: P0/P1; local preventable error: P2. |
| H6 — Recognition rather than recall | Keep needed choices, context, selections and next actions visible in navigation, forms, multi-step/dense tools and returning-user flows. | Labels, current selections, defaults, wayfinding and cross-step context with realistic content. | Missing context causing primary-task error: P1; memory burden: P2/P3. |
| H7 — Flexibility and efficiency | Keep a simple novice path; support efficient frequent/expert work where sources justify it. | Default and repeat-task walkthrough; applicable shortcuts/bulk actions; keyboard/touch alternatives; observable step/effort reduction and user-group assumptions. | Missing required high-frequency efficiency: P1/P2; optional customization: P3. |
| H8 — Aesthetic and minimalist design | Each visible element serves the task; remove noise that competes with action, hierarchy, comprehension or trust, especially dense/mobile/error states. | Representative captures, content priority, primary-action visibility, density and contrast. | Hidden/weakened critical action or warning: blocking P1/P2 by impact; decoration: P3. |
| H9 — Recognize, diagnose and recover from errors | Explain failure in user language and preserve recoverable work; cover validation, timeout, offline, permissions, integrations and partial failures. | Cause, preserved work, next action, retry/undo and observed completion, tied to route/state/viewport. | Blocked primary recovery or critical data loss: P0/P1; incomplete local guidance: P2. |
| H10 — Help and documentation | Offer concise, contextual, task-oriented help where complexity, novelty, onboarding, permissions, risk or recovery needs it. | Inline guidance, actionable empty state, contextual help, searchable docs when warranted, recovery links and task/route/state/viewport. | Missing task-critical help: P1/P2; general documentation polish: P3. |

These are examples, not automatic severity assignments. Apply the source glossary and classify release effect separately. P0/P1 block; P2 blocks only under the critical-impact rules; P3 is advisory. Any inapplicable heuristic needs a source-backed reason.

## Required review record

Each scope resolves: heuristic IDs; owner skill; artifact section; validation stage; JOB/UC; primary journey/task/user group; screen/route/state/viewport; expected behavior; applicability/rationale; required and actual evidence; findings/recommendations; severity/release effect; coverage or execution status; actual reviewer/time when executed.

Use shared scope IDs where helpful, but every field must resolve. Include supported desktop/mobile, normal/loading/empty/error/success/permission/offline/long-content/recovery states and accessibility-critical actions. Mark planned coverage `covered | deferred | not applicable`; use the separate execution statuses from the verification contract. Never translate `covered` into passed.

## Explicit H7 and H10 decisions

H7: consider expert shortcuts, bulk actions, repeated-task efficiency, keyboard/touch alternatives and customization **only when it reduces effort**. Preserve a simple novice default; no advanced controls without a source-backed need.

H10: consider contextual help, searchable documentation, actionable empty states, short inline instructions, recovery links and task-oriented assistance. Prefer help at the point of need; do not add a generic documentation dump to a self-explanatory task.

## Error and recovery contract

For every applicable error/recovery state:

> cause → what was preserved → next action → retry/undo option → condition for successful completion

Make the cause understandable, preservation explicit where relevant, the next action actionable, retry/undo safe and meaningful, and success observable. Record a source-backed reason for any inapplicable element; do not omit it silently.
