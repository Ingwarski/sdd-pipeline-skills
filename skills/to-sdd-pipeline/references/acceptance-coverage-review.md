# Reviewing acceptance coverage

Use this review while preparing or reconciling QA definitions. QA owns check
actions and expected results; product owners resolve unclear requirements.
The existing verification contract governs statuses, evidence and approval.
This review neither adds product requirements nor executes checks.

For each source obligation, compare its actual meaning with the proposed check:

| Review | Evidence needed in the definition |
|---|---|
| Conditions and scope | The supported actor, interface, data and starting state apply to the claimed behavior. |
| Trigger | An action or observed external transition actually reaches the required condition. |
| Outcome | Assertions distinguish the required result from a plausible incorrect result. |
| Preservation and exclusions | Source-required unchanged data, denied effects or recovery behavior are checked. |
| Remaining clauses | Each conjunction, alternative, timing condition and supported state is exercised or explicitly blocked. |

Return a compact coverage-review table using:

| Source clause/condition and locator | Existing check ID plus concrete step/assertion | Expected observation | States/conditions exercised | Uncovered clause or blocker and reason (or none) |
|---|---|---|---|---|

Split distinct outcomes and timing, preservation or alternative conditions into
separate rows, even when they share a source ID; reference existing detailed check
text where sufficient. Record planned coverage until execution supplies observations.
Parent-ID links, blanket state lists or general coverage prose alone do not complete
this review. Use existing IDs and evidence fields; this creates no new product
requirement, gate, approval or independent specification. A check title, screenshot
filename or successful checker report cannot establish semantic coverage.

## Review examples

These artificial examples illustrate coverage review, not requirements for
other products.

- Source: “On invalid input, the command reports the offending field and leaves
  the destination unchanged.” A check that asserts a nonzero exit code covers
  neither the diagnostic content nor preservation. Define observations of the
  named field and destination before/after, including the invalid-input trigger.
- Source: “After connectivity returns, the view shows the latest saved result.”
  Loading an already connected view demonstrates an initial state only. Observe
  the supported loss/return sequence and the resulting value. If the test cannot
  reach that transition, the recovery claim remains unverified.

During execution, review the actual test assertions and observations against
the definitions. An attempted trigger is not an observed transition; a common
mock or fixture can make expected and actual values agree without testing the
real claim. Explain simulated versus real evidence under the existing contract.

If a check misses a clause, preserve the earlier definition/results and reconcile
the affected owner bindings. Keep unrelated valid work. Run affected tests
genuinely when execution is authorized; do not extend old evidence to cover the
new assertion. Unclear product meaning returns to its owner as a named question,
not an agent-invented requirement or a weaker acceptance rule.
