# Heuristic Usability Review Reference

This is the shared canonical reference for the formal heuristic layer used by `to-design-brief`, `to-qa-checklist`, `to-dod-evals`, and `to-development-plan`. It defines the review vocabulary and evidence contract once. The consuming skills own their respective plan, concrete checks, reusable gate, and implementation mapping; none should copy this reference into a competing artifact.

## Scope And Evidence Boundary

Use the ten Nielsen Norman usability heuristics as a structured review lens for the applicable product flows, screens, states, routes, and viewports. A heuristic review is expert or rule-based evaluation of an interface. It is not representative-user research, visual-fidelity evidence, browser/runtime evidence, accessibility conformance proof, or proof that functionality works with real data and actions.

The formal review has four stages:

1. `to-design-brief` defines the intended heuristic coverage and records `covered`, `deferred`, or `not applicable` status for each relevant heuristic.
2. Prototype review checks the representative candidate routes, screens, states, and desktop/mobile viewports before whole-design approval; it may identify findings but does not create an additional approval gate.
3. `to-qa-checklist` instantiates concrete post-implementation checks and records per-check evidence, findings, severity, and release effect.
4. `to-dod-evals` evaluates the reusable `heuristic_usability_review` gate; `to-development-plan` maps that gate and its QA checks to user-visible implementation units.

Every applicable review scope must identify:

- primary journey and related `JOB-*`/`UC-*` references;
- representative screens, states, routes, and viewports, including desktop and mobile when supported;
- relevant normal, empty, loading, error, success, permission, offline, long-content, and recovery states;
- critical actions and accessibility-relevant interactions;
- reviewer, date, environment, fixture/content state, evidence references, and limits.

## H1-H10 Heuristic Contract

| Heuristic | Short definition | Owner skill | Artifact section | Main validation stage | Required evidence | Default severity and release effect | Applicability |
|---|---|---|---|---|---|---|---|
| H1 | Visibility of system status: the interface keeps users informed about what is happening, what changed, and what will happen next through timely, understandable feedback. | `to-design-brief` defines state communication; `to-qa-checklist` verifies it; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `QA > Heuristic Usability Checks` | Design brief state contract, prototype state walkthrough, post-implementation state checks | State/transition inventory, route/state/viewport, loading/progress/success/error evidence, console/runtime evidence when behavior is claimed | Missing feedback on a primary or high-risk action: P1 blocking. Localized ambiguity: P2, blocking when it affects a critical journey; otherwise advisory. | All asynchronous, destructive, submitted, saved, navigational, and state-changing actions; otherwise mark `not applicable` with rationale. |
| H2 | Match between system and the real world: words, concepts, order, and feedback use the user's language, mental model, and task sequence. | `to-design-brief` defines terminology and conceptual model; `to-qa-checklist` verifies comprehension; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `QA > Heuristic Usability Checks` | Product-intent/PRD reconciliation, design brief review, prototype task walkthrough, QA | Canonical terms, user-facing copy, task/route/state evidence, source references, representative content fixture | A misleading term or model that causes primary-task error: P1 blocking. Localized terminology mismatch: P2, release effect determined separately. | Every user-facing workflow and domain concept; include locale variants when they change comprehension. |
| H3 | User control and freedom: users can cancel, exit, undo, go back, recover, or safely revise actions without being trapped. | `to-design-brief` defines interaction/recovery intent; `to-wireframes` defines error-state structure; `to-qa-checklist` verifies controls; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `Wireframes > Error And Recovery Contract`; `QA > Heuristic Usability Checks` | Wireframe error/recovery design, prototype interaction review, QA destructive/recovery checks | Routes/states, cancel/back/undo/retry evidence, preserved-data evidence, authorization boundary, task result | Irreversible or trapping primary flow without required control: P0/P1 blocking according to impact. Missing local recovery: P2, blocking when critical/high-risk. | Forms, multi-step flows, navigation, destructive actions, unsaved changes, external effects, and any flow with failure or interruption. |
| H4 | Consistency and standards: equivalent things look and behave alike, and the product follows platform, accessibility, and established product conventions. | `to-design-brief` defines system rules; `to-wireframes` applies structural consistency; `to-qa-checklist` verifies; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `QA > Heuristic Usability Checks` | Design-system/spine review, prototype comparison, QA cross-route/device comparison | Component/state matrix, token/system references, route/state/viewport comparisons, platform convention evidence | Inconsistent behavior that causes task failure or accessibility error: P1 blocking. Isolated inconsistency: P2/P3 with release effect determined separately. | All repeated components, navigation, forms, feedback, shortcuts, touch/keyboard behavior, and supported platforms/locales. |
| H5 | Error prevention: the design prevents likely mistakes before they occur through constraints, defaults, previews, confirmation at the right risk boundary, and clear affordances. | `to-design-brief` defines prevention intent; `to-wireframes` defines prevention and error-state structure; `to-qa-checklist` verifies; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `Wireframes > Error And Recovery Contract`; `QA > Heuristic Usability Checks` | Wireframe/design review, prototype risky-action walkthrough, QA invalid-input/destructive-action checks | Input constraints, defaults, confirmation/preview evidence, validation behavior, destructive-action path, recovery evidence | Preventable high-impact error with no safe recovery: P0/P1 blocking. Localized preventable error: P2, blocking when critical; otherwise advisory. | Forms, payments, deletion, publication, permissions, external effects, irreversible or costly actions, and common invalid input paths. |
| H6 | Recognition rather than recall: users can see needed options, context, information, and next actions instead of remembering them across steps. | `to-design-brief` defines contextual information hierarchy; `to-qa-checklist` verifies; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `QA > Heuristic Usability Checks` | Design brief hierarchy review, prototype task walkthrough, QA multi-step/context checks | Labels, visible context, selected/current state, defaults, breadcrumbs/wayfinding, cross-step evidence, content fixture | Omitted context that causes primary-task error: P1 blocking. Extra memory burden: P2/P3 based on journey impact. | Multi-step workflows, dense tools, navigation, forms, returning users, permissions, and any task using prior selections or system state. |
| H7 | Flexibility and efficiency of use: novice users have a clear default path while expert or repeat users can complete frequent work efficiently through shortcuts, bulk actions, keyboard/touch alternatives, or appropriate customization. | `to-design-brief` defines the interaction strategy; `to-qa-checklist` verifies task efficiency; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `QA > Heuristic Usability Checks` | Design brief repeated-task review, prototype primary/repeat-task walkthrough, QA efficiency checks | Primary default flow, repeat-task scenario, shortcut/bulk-action evidence when applicable, keyboard/touch alternatives, measured or observable step reduction, user-group assumptions | Missing required efficiency path in a high-frequency primary workflow: P1/P2 according to impact. Optional customization/polish: P3 advisory. | High-frequency, operational, expert, accessibility-input, or repeated workflows. Do not add shortcuts or customization when sources show no efficiency need. |
| H8 | Aesthetic and minimalist design: every visible element serves the task; irrelevant information and visual noise do not compete with primary goals, hierarchy, comprehension, or trust. | `to-design-brief` defines hierarchy, density, and visual restraint; `to-qa-checklist` verifies; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `QA > Heuristic Usability Checks` | Design spine review, prototype hierarchy review, QA visual/interaction inspection | Representative route/state/viewport captures, content hierarchy, primary-action visibility, density/contrast evidence, source-backed content priority | Noise that hides or weakens a primary action, warning, or critical state: P1/P2 blocking by impact. Decorative excess: P3 advisory. | All user-visible screens; weight more heavily on dashboards, dense tools, mobile layouts, errors, empty states, and high-stakes actions. |
| H9 | Help users recognize, diagnose, and recover from errors: error messages explain the problem in user language, preserve what can be preserved, give the next action, and support retry/undo or a clear completion condition. | `to-design-brief` defines error/recovery behavior; `to-wireframes` defines the structural contract; `to-qa-checklist` verifies; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `Wireframes > Error And Recovery Contract`; `QA > Heuristic Usability Checks` | Wireframe error contract, prototype failure/recovery walkthrough, QA error/retry/recovery checks | Error state route/state/viewport, cause, preserved data, next action, retry/undo, success condition, recovery outcome evidence | Error that blocks primary recovery or loses critical user work: P0/P1 blocking. Incomplete diagnosis/recovery: P2, blocking for critical flows; otherwise advisory. | Every error, validation, timeout, offline, permission, integration, empty-with-next-step, and partial-failure state that can affect task completion. |
| H10 | Help and documentation: assistance is contextual, concise, searchable when needed, task-oriented, and available when users need to understand or complete a task. | `to-design-brief` defines contextual help intent; `to-qa-checklist` verifies; `to-dod-evals` gates the review. | `Design Brief > Heuristic Review`; `QA > Heuristic Usability Checks` | Design brief help review, prototype empty/help walkthrough, QA help/recovery checks | Inline instructions, actionable empty state, contextual help, searchable docs where warranted, recovery links, help route/state/viewport evidence | Missing task-critical help that prevents completion: P1/P2 according to impact. General documentation polish: P3 advisory. | Complex, unfamiliar, regulated, high-risk, empty, permissioned, onboarding, and recovery contexts; do not add generic help when the task is self-explanatory. |

## Required Review Record

Each heuristic review record and each concrete QA check must include:

- `Heuristic: H1 | H2 | H3 | H4 | H5 | H6 | H7 | H8 | H9 | H10` (one or more IDs);
- `Owner Skill: to-design-brief | to-qa-checklist | to-dod-evals | to-development-plan`;
- `Artifact Section`;
- `Validation Stage: design-brief | prototype | post-implementation QA | DoD/release`;
- `JOB-*`, `UC-*`, primary journey, task, and user group;
- `Route`, `State`, and `Viewport` (include desktop/mobile coverage when applicable);
- `Expected Behavior`;
- `Required Evidence` and actual `Evidence` references;
- `Finding` and `Recommendation`;
- `Severity: P0 | P1 | P2 | P3`;
- `Release Effect: blocking | advisory`;
- `Applicability` and rationale;
- `Result: covered | passed | blocked | deferred | not applicable`;
- reviewer/evaluator and timestamp where execution evidence exists.

Use the repository's canonical severity glossary and keep severity separate from release effect. P0/P1 are blocking; P2 is blocking only when it meets the existing critical-journey, accessibility, security, privacy, legal, payment, data-integrity, supported-surface, approved-meaning, or combined-impact rules; P3 is advisory. A heuristic finding does not automatically block release merely because it exists.

## H7 And H10 Minimum Rules

For H7, explicitly decide whether the flow needs: shortcuts for expert users, bulk actions, efficient repeated workflows, keyboard/touch alternatives, or customization that genuinely reduces effort. Preserve a simple default path for novice users. Do not add advanced controls without a source-backed efficiency need.

For H10, explicitly decide whether the flow needs contextual help, searchable documentation, actionable empty states, short inline instructions, recovery links, or task-oriented help. Prefer help at the point of need over a generic documentation dump.

## Error And Recovery Contract

For every applicable error or recovery state, use this canonical sequence:

> cause -> what was preserved -> next action -> retry/undo option -> condition for successful completion

The `cause` must be understandable, `what was preserved` must be explicit when relevant, `next action` must be actionable, retry/undo must be offered when safe and meaningful, and the success condition must be observable. If a field is not applicable, record the source-backed reason rather than omitting it silently.
