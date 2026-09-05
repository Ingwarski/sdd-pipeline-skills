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

DoD authoring never executes gates. QA authoring never implies execution: it may record supplied, inspected run evidence, or perform a separately requested review within the user's authorization. Name the actual executor. The checker validates records and references; it is not a test runner or a substitute for human research.

## Two independent statuses

The required `product_security_requirements` gate maps every PRD security obligation to implementation-level QA evidence under the [security traceability contract](security-contract.md). It is distinct from visual, heuristic and representative-user gates. A mockup cannot satisfy it; unrun, failed, deferred or silently excluded applicable checks cannot support a security release claim.

- `Definition Status: prepared | blocked`: can this check be executed as specified?
- `Execution Status: not_run | passed | failed | blocked | deferred | not_applicable`: what actually happened?

New checks start `prepared` / `not_run`, with evidence requirements but no invented result, finding, participant, or timestamp. `covered` in a design plan means planned coverage, never a test pass. `deferred` is not a pass. `not_applicable` requires a source-backed rationale. A failed test may be advisory; do not relabel it passed to permit release.

At planning time report **checks prepared; tests not run**. Keep release readiness `not_evaluated`, not `passed` or a fabricated product failure. When release is explicitly evaluated, readiness is binary: `passed` only when all applicable required gates and blocking findings are closed, otherwise `blocked`. An advisory finding may remain with evidence and a follow-up.

## Bind only existing references

Gate/check membership is bidirectional: every indexed check belongs to its named gate and every gate ID resolves to that check, without duplicates. An applicable gate needs at least one applicable check. Excluded checks never satisfy required clauses or H1–H10 coverage; exclusions need reasons. Trace and verification check IDs must agree; JOB/UC references resolve to canonical definitions.

Before approval, visual gates are parameterized definitions: `Binding Status: pending_baseline`; QA check references remain pending until QA creates real IDs. No invented Baseline ID, target hash, check ID, or user-test result.

After approval: `to-design-brief` records the baseline; `to-architecture` rechecks affected technical consequences; `to-dod-evals` revalidates affected gate definitions; `to-qa-checklist` creates/binds concrete checks; the orchestrator records the QA-ID bindings; `to-development-plan` maps them to units. DoD references QA **at evaluation**, not as an authoring prerequisite. Unchanged documents can be revalidated without rewriting their bytes. This order is not a second approval or a dependency loop.

## Three separate UI gates

| Gate | Parameters and pass evidence |
|---|---|
| `approved_visual_baseline_fidelity` | Active Baseline ID, immutable target hash, route/state/viewport, permitted variance, concrete QA IDs, `VisualQAEvidence`; promotion receipt when reuse is declared. Reject stale baselines, missing coverage, unexplained drift, or blocking findings. |
| `heuristic_usability_review` | Applicable H1-H10, primary journey, JOB/UC, screen/state/route/viewport, desktop/mobile when supported, error/recovery and accessible critical actions, QA IDs, reviewer/evidence/findings. Every applicable heuristic and scope needs review; unexplained omissions or deferred critical review block the gate. |
| `representative_user_task_validation` | Applicable critical/consequential/new or changed flow, JOB/UC, representative user group, task, success criterion, device/viewport, observed session evidence and findings. Only observed representative-user task completion can pass. |

Visual fidelity, heuristic review, representative-user research, accessibility verification, and functional/runtime checks are separate evidence classes. None proves another. A prototype with simulated interactions does not prove production auth, persistence, integrations, security, or real data/actions. Screenshots alone do not prove WCAG conformance.

For high-risk, regulated, safety- or accessibility-critical flows, plan representative-user validation before approval when feasible. If unavailable, record assumption, risk, owner, timing and follow-up; do not claim user validation. A deferred applicable required release check stays blocking. No extra human approval is created.

## Record shapes

Every gate definition: ID, purpose, source, applicability, required evidence, pass/block condition, rerun rule, and automation status (`automated`, `manual`, `not available yet` with a named condition, or `open question`). Do not invent runnable commands, CI, tests, thresholds, or merge policies. A missing comparison value is a named blocker, not a measurable gate.

Every QA item: stable check ID, source obligation, task, expected behavior, scope, applicability/rationale, gate ID, definition status, execution status, evidence requirements and actual evidence. UI/heuristic items also resolve H1-H10, JOB/UC, user group, route, state, viewport, finding, severity, release effect, and recommendation. Visual items additionally resolve Baseline ID, target hash and variance after approval. User-validation items add task success criterion and timing (`pre-approval | post-implementation | both`). Error items use the shared recovery sequence.

Every executed result: check/gate ID, exact evaluated artifact/baseline or implementation revision, executor, time, environment/content fixture, evidence kind/path/hash, result, findings, and rerun rule. Keep prior runs; supersede them explicitly when sources change. `passed` requires fresh, readable evidence appropriate to that claim, not merely a nonempty path.

## Severity and release effect

Use the PRD's canonical glossary; do not create a competing scale:

- P0: catastrophic actual/imminent severe harm or system-wide unusability; blocking.
- P1: broken primary journey, core capability, release invariant, or high-impact requirement without an acceptable workaround for material supported scope; blocking.
- P2: localized meaningful defect, gap, regression or drift; blocking only for a required gate, critical journey, applicable accessibility/security/privacy/legal/payment/data-integrity requirement, supported device/viewport, approved hierarchy/interaction meaning, or combined P1 impact. Otherwise advisory.
- P3: low-impact polish with no material effect on behavior, comprehension, accessibility, trust or completion; advisory.

Every finding resolves severity, release effect, applicability, source, evidence and rationale. An inactive/superseded gate cannot remain load-bearing in requirement mappings.
