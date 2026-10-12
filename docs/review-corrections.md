# Specification review corrections

The QuietQueue synthetic planning review found gaps in consequence rules,
construction ownership, browser retention, evidence reuse and prototype recovery.
These changes preserve the 13 skills, document owners and implementation boundary.

| Review scope | Required result |
|---|---|
| Recovery data | A destructive decision considers recoverable records and other live pages, even when the visible list is empty. Cancel and confirmed replacement have explicit effects. |
| Construction | Architecture declares required mechanisms. The plan assigns each mechanism to an owning unit, its production files and required construction checks. Later qualification is separate. |
| Platform limits | Specify each browser, OS and use mode. State retention policy, persistence-request outcomes and backup limits. Separate a simulated storage deletion from a real browser-policy test. |
| Native files | Where required native behavior is uncertain, use a disposable feasibility experiment before dependent construction. Independently retrieve retained bytes before claiming a file result. |
| Interfaces | Specify inputs, outputs, errors and recovery ownership at each material boundary. |
| Recovery controls | Observe the actual failure-to-recovery action sequence. Retry must exist and retain valid candidate/decision bindings. |
| Focus and long lists | Record the active element and next Tab destination after controls change. Put recovery beside its result and test realistic maximum-size data. |
| Evidence labels | Separate the action name from the observed state. A metadata correction preserves original bytes and observation times. |

## Construction records

Architecture owns the canonical mechanism section. The plan owns
`construction_ref` and `construction`. The checker compares required mechanisms,
production-path ownership, clause contributions and construction-check coverage.
Files may be planned before implementation; they need not exist during planning.

The extension is compatible with older records that lack both fields. Reconcile
an affected older plan through its owners. Do not add guessed allocations or
treat legacy structural compatibility as a completed semantic review.

See the [traceability contract](../skills/to-sdd-pipeline/references/traceability-contract.md)
and [unit contract](../skills/to-sdd-pipeline/references/unit-execution-contract.md).

## Reviewed reuse of acceptance

Version 1 supports unchanged claims for an already completed unit. It requires
the same canonical unit contract, unchanged non-plan specification bytes, the
same approved baseline, complete original/current source identities and an
explicit impact review. An unrelated plan-prose change or a reviewed inert
implementation change can qualify. Changed behavior, requirements, check
definitions, ownership or dependencies require new execution.

The review is additional evidence. It does not replace an original result,
execution time, source hash, authorization or prerequisite. Every required check
and the completed unit must reference the same review. Original evidence must
remain readable and valid. A changed plan still requires fresh implementation
authorization; a review never grants it.

The checker validates record consistency. The execution host must establish the
reviewer's authority and the truth of the impact assessment. Do not present a
synthetic regression fixture as product acceptance.

See the [revalidation contract](../skills/to-sdd-pipeline/references/unit-execution-contract.md)
for exact fields and rejection rules.

## Verification scope

Focused regressions cover missing construction owners/clauses, false or stale
reuse, changed prerequisites, unreadable evidence and corrected receipt labels.
The regular suites also cover stage interruption, stale owner returns and
evidence storage. Run the complete checks in [maintenance](maintenance.md).

Fresh-context authoring cases remain separate from deterministic tests. A single
synthetic planning result does not establish reliability for human intake,
server authority, multiple roles, product execution or release.
