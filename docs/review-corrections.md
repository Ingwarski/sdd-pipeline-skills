# Specification review corrections

The QuietQueue synthetic planning review supplied the original findings. Its
generated specifications, selected prototype and observations belong to a separate
test project. They are not skillset components or default product requirements.
This document describes the reusable rules derived from that review. They preserve
the 13 skills, document owners and implementation boundary.

| Review scope | Required result |
|---|---|
| Recovery data | Consequential decisions account for recoverable data and pending work across affected contexts. Define applicable cancellation and replacement effects. |
| Construction | Architecture declares required mechanisms. The plan assigns each mechanism to an owning unit, its production files and required construction checks. Later qualification is separate. |
| Platform limits | Specify source-defined environments, versions and use modes. For persistent data, state applicable retention and recovery limits. Separate simulated recovery from actual platform-policy qualification. |
| Feasibility | Where a required capability is uncertain, use a disposable experiment before dependent construction. Observe its required outcome; starting an operation does not prove completion. |
| Interfaces | Specify inputs, outputs, errors and recovery ownership at each material boundary. |
| Recovery controls | Observe each required failure-to-recovery action sequence. Provide the recovery actions required by the product and preserve valid work/decision bindings where applicable. |
| Focus and large views | For keyboard-capable UI, record focus and subsequent navigation after controls change. Keep recovery reachable through supported input modes with realistic maximum content. |
| Evidence labels | Separate the action name from the observed state. A metadata correction preserves original bytes and observation times. |

## Construction records

Architecture owns the canonical mechanism section and its `construction_ref`.
The plan copies that pointer and owns `construction`. The checker compares required mechanisms,
production-path ownership, clause contributions and construction-check coverage.
Files may be planned before implementation; they need not exist during planning.

Only older sources without a mechanism declaration can omit these records.
A structured declaration requires owner metadata and complete plan allocation. Reconcile
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

## Generic scope audit

The follow-up audit found assumptions that name searches did not detect. Reusable
rules now derive unit order and component labels from the project's architecture.
They no longer prescribe an education workflow or a web-layer taxonomy. Browser
storage, web accessibility, input modes and visual intake use explicit applicability.
Completion rules require a pull request only when the project uses that workflow.
Portable prototype review uses the shared verification policy, with optional host
adapters kept separate from product runtime choices.

Workflow artifact names, schema fields and the three-candidate UI process remain
intentional pipeline contracts. Headless scope still omits visual stages. Synthetic
fixtures may use concrete products and expected outcomes; they must not supply
product truth to unrelated authoring. Historical examples and the two retired skill
identifiers remain provenance or compatibility data, not product requirements.
