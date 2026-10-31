# Verification: Definitions, Runs, and Evidence

## Responsibility

| Responsibility | Owner |
|---|---|
| Evidence need and claim scope | `to-guardrails` |
| Gates, pass/block conditions, reruns and release | `to-dod-evals` |
| Product check definitions, findings and evidence | `to-qa-checklist` |
| Design coverage, task-validation plan and risks | `to-design-brief` |
| Unit allocation to gates/checks and sequence | `to-development-plan` |
| Executed checks and observations/receipts | Authorized reviewer, user-test facilitator, test harness or Phase 3 runner |
| Hash-bound index and scheduling | `to-sdd-pipeline` |

QA interprets inspected evidence; name actual executors. Storage preserves observations. Authoring/checker validation neither runs tests nor replaces research.

## Two independent statuses

Required `product_security_requirements` maps every PRD protection to implementation QA and security evidence under the [security contract](security-contract.md). Other evidence cannot substitute. Unrun, failed, deferred or excluded applicable checks block security release.

- `Definition Status: prepared | blocked`: executability.
- `Execution Status: not_run | passed | failed | blocked | deferred | not_applicable`: actual outcome.

New checks start `prepared` / `not_run`, with evidence requirements; invent no result, finding, participant or timestamp. `covered` means planned, not passed. Deferred work is nonpassing; `not_applicable` needs source-backed rationale. Advisory failures remain failed.

Report **checks prepared; tests not run**, release readiness `not_evaluated`, during planning. Explicit release evaluation is `passed` only with all applicable required gates and blockers closed; otherwise `blocked`. Advisory findings need evidence/follow-up. Invent no product failure.

Bounded acceptance proves contributions only. Integration/release owners retain full requirements and required real-consumer checks; mocks cannot substitute and deferred checks stay required/pending. The [unit contract](unit-execution-contract.md) defines ownership, dependencies, evidence and transitions. DoD precedes QA/planning; later bindings create no artifact cycle.

## Economical execution

Choose the least costly boundary that proves each claim: logic for deterministic rules, the actual platform's enforcement/persistence boundary, UI for layout/input, and supported native/provider environments where required. Retain real integration coverage; browser repetition does not strengthen an engine-independent assertion.

One setup or journey may support several separately observed assertions, including applicable H1-H10. Record each outcome; a successful bundle cannot pass skipped or unexecuted checks. Share infrastructure with isolated contexts/data. Resize existing states for layout where equivalent; separately cover initialization and interactions that depend on the starting environment. Independent groups may run concurrently inside the active unit, with shared mutations serialized.

During edits, run checks that resolve the current change or uncertainty. Before completion, every required outcome needs fresh or validly reusable evidence. Rerun failed and affected checks, not a full matrix by habit; unknown impact requires broader coverage. A retry needs a relevant change, diagnostic hypothesis or bounded transient-failure investigation. Preserve original failures and unresolved flakiness; retry limits are ceilings, not targets.

## Bind only existing references

Gate/check membership must agree bidirectionally, without duplicates. Each applicable gate needs an applicable check. Excluded checks need reasons and cannot cover required clauses or H1–H10. Trace/verification check IDs agree; JOB/UC references resolve to canonical definitions.

Before approval, visual gates use `Binding Status: pending_baseline`; check references await actual QA IDs. Invent no Baseline ID, target hash, check ID or user-test result.

After approval, owners act in order: brief records baseline → architecture reviews affected mechanisms → DoD revalidates gates → QA binds checks → orchestrator indexes QA IDs → plan allocates units. DoD consults QA **at evaluation**, never as an authoring prerequisite. Revalidate unchanged documents without byte changes or repeat approval.

## Separate visual and interaction gates

| Gate | Parameters and pass evidence |
|---|---|
| `approved_visual_baseline_fidelity` | Active Baseline ID, immutable target hash, route/state/viewport, permitted variance, concrete QA IDs, `VisualQAEvidence`; promotion receipt when reuse is declared. Reject stale baselines, missing coverage, unexplained drift, or blocking findings. |
| `heuristic_usability_review` | Applicable H1-H10, primary journey, supported inputs, error/recovery, accessible critical actions; screen for visual checks. Review every applicable heuristic/scope; unexplained omissions or deferred critical review block. |
| `representative_user_task_validation` | Flow requiring participant evidence because of an explicit requirement or material task risk; representative group and observed session evidence, device for visual checks. Newness alone is insufficient. Only observed representative-user task completion can pass. |

Headless scope excludes visual fidelity. Source-backed applicability/exclusion determines interaction gates; use the nonvisual record when applicable.

Visual, heuristic, participant, accessibility and runtime evidence remain separate. Simulations prove no production auth, persistence, integration, security or actual data/actions. Screenshots alone cannot establish WCAG conformance.

For high-risk, regulated, safety- or accessibility-critical flows, plan representative-user validation before approval when feasible. Otherwise record assumption, risk, owner, timing and follow-up; claim no validation. No extra approval is created.

## Record shapes

Every gate: ID, purpose, source, applicability, required evidence, pass/block condition, rerun rule, automation status (`automated`, `manual`, `not available yet` with a named condition, or `open question`). Invent no commands, CI, tests, thresholds or merge policies. A missing comparison value is a named blocker.

Every QA item: stable check ID, source obligation, task, expected behavior, scope, applicability/rationale, gate ID, definition/execution statuses, evidence requirements and actual evidence. Interaction items add applicable H1-H10, JOB/UC, user group, finding, severity, release effect and recommendation. Visual checks need route/state/viewport plus Baseline ID, target hash and variance after approval. User-validation adds task success criterion and timing (`pre-approval | post-implementation | both`). Error items use the shared recovery sequence.

Heuristic/user-task checks may declare `interaction_scope: {kind: "nonvisual", context, rationale}`. Both strings must be nonempty and present in canonical QA: `context` identifies the actual interface/workflow and supported conditions; `rationale` explains source-backed applicability. It replaces visual context/baseline bindings only; all other fields/rules remain. Applicable headless interaction checks require it; mixed UI products may use it for genuinely nonvisual checks. Otherwise UI checks retain visual requirements. Visual fidelity cannot use it. Existing inapplicability/status rules remain.

Every executed result retains check/gate ID, exact evaluated inputs/baseline, executor/reviewer, original time, environment/fixture, evidence identity/hash, outcome, findings and rerun rule. Keep compact current records and verified detail/history references under [storage rules](evidence-storage-contract.md). Supersede stale acceptance without changing observations. [Completion preservation](completion-preservation.md) resolves applicability consistently for unit, security and release gates; a stored pass alone is insufficient. Passing needs readable evidence appropriate to the current claim. Migration and storage access never execute checks.

## Severity and release effect

Use the PRD's canonical glossary; do not create a competing scale:

- P0: catastrophic actual/imminent severe harm or system-wide unusability; blocking.
- P1: broken primary journey, core capability, release invariant, or high-impact requirement without an acceptable workaround for material supported scope; blocking.
- P2: localized meaningful defect, gap, regression or drift; blocking only for a required gate, critical journey, applicable accessibility/security/privacy/legal/payment/data-integrity requirement, supported device/viewport, approved hierarchy/interaction meaning, or combined P1 impact. Otherwise advisory.
- P3: low-impact polish with no material effect on behavior, comprehension, accessibility, trust or completion; advisory.

Every finding resolves severity, release effect, applicability, source, evidence and rationale. An inactive/superseded gate cannot remain load-bearing in requirement mappings.
