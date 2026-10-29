# Specification quality rules

This document defines reusable rules for specification quality, construction
ownership, acceptance evidence and recovery. Apply them to each project's
requirements. They preserve the 13 skills, document owners and implementation
boundary.

| Review scope | Required result |
|---|---|
| Recovery data | Consequential decisions account for recoverable data and pending work across affected contexts. Define applicable cancellation and replacement effects. |
| Construction | Architecture declares required mechanisms. The plan assigns each mechanism to an owning unit, its production files and required construction checks. Later qualification is separate. |
| Platform limits | Specify source-defined environments, versions and use modes. For persistent data, state applicable retention and recovery limits. Separate simulated recovery from actual platform-policy qualification. |
| Feasibility | Where a required capability is uncertain, use a disposable experiment before dependent construction. Observe its required outcome; starting an operation does not prove completion. |
| Interfaces | Specify inputs, outputs, errors and recovery ownership at each material boundary. |
| Recovery | Observe each required action or specified automatic/external recovery trigger. Preserve valid work/decision bindings where applicable. |
| Focus and large views | For supported focus-based navigation, record focus and the next destination after controls change. Keep recovery reachable through supported input modes with realistic maximum content. |
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

Supported version 2/3 contracts preserve original authorized execution and completed
work separately from current applicability. Owner-reviewed inventories include
exact acceptance definitions, relevant requirements, code, tests, configuration,
runtime, prerequisite acceptance and readable original evidence. Each applicability
assessment points directly to the original run and is recomputed before use.
Changed relevant inputs or new acceptance requirements need genuine revalidation;
pending-work edits cannot erase obligations or reassign completed identities.

Preservation never changes original observations, execution times or authorization.
Plan validity, current acceptance and implementation permission remain separate.
A changed plan needs fresh authority unless the verified approved-decision
correction contract preserves the original scope. The checker validates declarations
and bytes; the host must establish reviewer authority and semantic completeness.

Legacy version 1 records and `revalidation_ref` receipts remain readable for import
and audit only. Migrate on authorized resume, retain the original history as
unverified, and perform current checks before relying on it. A synthetic regression
fixture is not product acceptance.

See [completion preservation](../skills/to-sdd-pipeline/references/completion-preservation.md)
and the [unit contract](../skills/to-sdd-pipeline/references/unit-execution-contract.md).

## Verification scope

Verify missing construction owners/clauses, false or stale reuse, changed
prerequisites, unreadable evidence and corrected receipt labels. Include stage
interruption, stale owner returns and evidence storage. Run the complete checks
in [maintenance](maintenance.md); record results in a separate report.

Fresh-context authoring cases remain separate from deterministic tests. A single
synthetic planning result does not establish reliability for human intake,
server authority, multiple roles, product execution or release.

## Product scope

Derive unit order and component names from project requirements and architecture.
Apply platform, storage, accessibility, input and delivery rules only to supported
capabilities. Optional adapters do not determine the product's runtime platform.

Workflow artifact names, schema fields and the three-candidate UI process are
pipeline contracts. Confirmed headless scope omits visual stages. Keep product
examples and executable fixtures separate from requirements for another project.
