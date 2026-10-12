# Verification: Definitions, Runs, and Evidence

## Responsibility

| Responsibility | Owner |
|---|---|
| When evidence is necessary and what claims it supports | `to-guardrails` / `docs/guardrails.md` |
| Reusable gates, pass/block conditions, rerun and release rules | `to-dod-evals` / `docs/dod-evals.md` |
| Product-specific check definitions, findings, and per-check evidence | `to-qa-checklist` / `docs/qa-checklist.md` |
| Design-time coverage, task-validation plan and open risks | `to-design-brief` / `docs/design-brief.md` |
| Unit-to-gate/check mapping and implementation sequence | `to-development-plan` / `docs/development-plan.md` |
| Running checks and producing observations/receipts | Authorized reviewer, user-test facilitator, test harness or Phase 3 runner |
| Hash-bound operational index and scheduling | `to-sdd-pipeline` / `forge/sdd-manifest.json` |

QA interprets inspected evidence; executors produce observations; storage persists them; the orchestrator indexes them. Name the actual executor. Authoring/checker validation neither executes tests nor substitutes for research.

## Two independent statuses

Required `product_security_requirements` maps every PRD protection to implementation QA under the [security contract](security-contract.md). Visual, heuristic, participant or mockup evidence cannot substitute. Unrun, failed, deferred or silently excluded applicable checks block security release claims.

- `Definition Status: prepared | blocked`: can this check be executed as specified?
- `Execution Status: not_run | passed | failed | blocked | deferred | not_applicable`: what actually happened?

New checks start `prepared` / `not_run`, with evidence requirements; invent no result, finding, participant or timestamp. `covered` means planned, not passed. Deferred work is nonpassing; `not_applicable` needs source-backed rationale. Advisory failures remain failed.

Report **checks prepared; tests not run** during planning, with release readiness `not_evaluated`. Explicit release evaluation is binary: `passed` only with all applicable required gates and blockers closed; otherwise `blocked`. Advisory findings may remain with evidence/follow-up. Invent no product failure.

Bounded acceptance proves contributions only. Accountable integration/release units retain full requirements and required real-consumer checks; mocks cannot substitute, and deferred checks remain required/pending. Apply the [unit contract](unit-execution-contract.md) for ownership, dependencies, evidence and transitions. DoD defines rules before QA/planning; later bindings create no artifact cycle.

## Bind only existing references

Gate/check membership is bidirectional: every indexed check belongs to its named gate and every gate ID resolves to that check, without duplicates. An applicable gate needs at least one applicable check. Excluded checks never satisfy required clauses or H1–H10 coverage; exclusions need reasons. Trace and verification check IDs must agree; JOB/UC references resolve to canonical definitions.

Before approval, visual gates are parameterized definitions: `Binding Status: pending_baseline`; QA check references remain pending until QA creates real IDs. No invented Baseline ID, target hash, check ID, or user-test result.

After approval: `to-design-brief` records the baseline → `to-architecture` reviews affected mechanisms → `to-dod-evals` revalidates gates → `to-qa-checklist` binds checks → orchestrator indexes QA IDs → `to-development-plan` allocates units. DoD consults QA **at evaluation**, never as an authoring prerequisite. Revalidate unchanged documents without rewriting bytes or repeating approval.

## Three separate UI gates

| Gate | Parameters and pass evidence |
|---|---|
| `approved_visual_baseline_fidelity` | Active Baseline ID, immutable target hash, route/state/viewport, permitted variance, concrete QA IDs, `VisualQAEvidence`; promotion receipt when reuse is declared. Reject stale baselines, missing coverage, unexplained drift, or blocking findings. |
| `heuristic_usability_review` | Applicable H1-H10, primary journey, JOB/UC, screen/state/route/viewport, desktop/mobile when supported, error/recovery and accessible critical actions, QA IDs, reviewer/evidence/findings. Every applicable heuristic and scope needs review; unexplained omissions or deferred critical review block the gate. |
| `representative_user_task_validation` | Applicable critical/consequential/new or changed flow, JOB/UC, representative user group, task, success criterion, device/viewport, observed session evidence and findings. Only observed representative-user task completion can pass. |

Visual, heuristic, participant, accessibility and runtime evidence remain separate. Simulations prove no production auth, persistence, integration, security or actual data/actions. Screenshots alone cannot establish WCAG conformance.

For high-risk, regulated, safety- or accessibility-critical flows, plan representative-user validation before approval when feasible. If unavailable, record assumption, risk, owner, timing and follow-up; do not claim user validation. A deferred applicable required release check stays blocking. No extra human approval is created.

## Record shapes

Every gate definition: ID, purpose, source, applicability, required evidence, pass/block condition, rerun rule, and automation status (`automated`, `manual`, `not available yet` with a named condition, or `open question`). Do not invent runnable commands, CI, tests, thresholds, or merge policies. A missing comparison value is a named blocker, not a measurable gate.

Every QA item: stable check ID, source obligation, task, expected behavior, scope, applicability/rationale, gate ID, definition status, execution status, evidence requirements and actual evidence. UI/heuristic items also resolve H1-H10, JOB/UC, user group, route, state, viewport, finding, severity, release effect, and recommendation. Visual items additionally resolve Baseline ID, target hash and variance after approval. User-validation items add task success criterion and timing (`pre-approval | post-implementation | both`). Error items use the shared recovery sequence.

Results retain check/gate ID, evaluated artifact/baseline/revision, executor, original time, environment/fixture, evidence identity/hash, outcome, findings and rerun rule. QA keeps compact current records and verified detailed/history references. Apply [storage procedures](evidence-storage-contract.md); passing needs fresh readable evidence. Migration/access never executes checks.

Reuse unchanged completed work only through the unit contract's `revalidation_ref`: retain original observation bindings/executor/time and record current reviewer/time separately. Review verifies unchanged claims, complete current sources and prerequisites. Changed behavior/definitions/scope or required new tests need execution; review grants no implementation authorization.

## Severity and release effect

Use the PRD's canonical glossary; do not create a competing scale:

- P0: catastrophic actual/imminent severe harm or system-wide unusability; blocking.
- P1: broken primary journey, core capability, release invariant, or high-impact requirement without an acceptable workaround for material supported scope; blocking.
- P2: localized meaningful defect, gap, regression or drift; blocking only for a required gate, critical journey, applicable accessibility/security/privacy/legal/payment/data-integrity requirement, supported device/viewport, approved hierarchy/interaction meaning, or combined P1 impact. Otherwise advisory.
- P3: low-impact polish with no material effect on behavior, comprehension, accessibility, trust or completion; advisory.

Every finding resolves severity, release effect, applicability, source, evidence and rationale. An inactive/superseded gate cannot remain load-bearing in requirement mappings.
