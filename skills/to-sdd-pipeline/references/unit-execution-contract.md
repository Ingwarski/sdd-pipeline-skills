# Independently completable implementation units

Read for development planning, unit-record migration and production handoff. Artifact authoring dependencies remain in `pipeline-contract.json`; implementation dependencies use the separate records below.

## Planning and reconciliation

Under `strict_sequential`, every unit must finish its required acceptance using its own implementation and completed predecessors. Combine construction dependencies with acceptance prerequisites, including the owners of prerequisite checks. Reject cycles and any prerequisite scheduled after its consumer. Checks within one unit may depend on other checks in that unit, but their check graph must be acyclic. Every prerequisite of a required check must itself be required acceptance of its owner, recursively; otherwise that owner could finish without evidence needed downstream. Resolve conflicting advisory definitions through QA, not by silently changing the projection.

Resolve a forward dependency through a source-backed split, merge or reorder. Separate independently verifiable component work from required system integration work, with explicit acceptance ownership for both. Component checks demonstrate only their bounded contribution. If the original unit promises full behavior, it remains incomplete until reconciled; never rename partial work as completion.

For an existing plan, preserve old IDs, allocations, results and authorization receipts in history. Show every moved obligation/check, old and new owner, prerequisite and reason. Reconcile changed scope/behavior through its source owner; material non-inferable decisions need the user. Reconcile architecture → DoD → QA → plan where affected, retaining unchanged sources and the approved baseline. Changed plan bytes invalidate implementation authorization: pause for a fresh explicit implementation prompt. Do not manufacture acceptance exclusions, smaller criteria, earlier completion or historical consent.

## Version 1 records

Keep `checker_contract_version: 1` and `traceability_version: 1`; add `unit_contract_version: 1`. Missing/unsupported unit records require owner-reviewed migration at plan validation, implementation, audit of a plan, and release. Earlier authoring stages remain usable. `--snapshot` does not supply unit semantics or migrate records.

The plan owner writes one JSON fence in a dedicated section of `docs/development-plan.md`, located by its `definition_ref: {path, heading}`. The orchestrator records its identical object as `unit_plan`. Localize the heading (for example, `## Unit Execution Contract`) to `working_language`; keep JSON keys unchanged. Surrounding prose explains scope/reconciliation. Unit IDs exactly match typed traceability definitions.

| Field | Meaning |
|---|---|
| `policy` | `strict_sequential`; exceptions below authorize individual starts, not an alternate acceptance standard |
| `order` | Every current unit ID once, in execution order |
| `units` | Object keyed by unit ID |
| Unit | Nonempty `scope`, responsible `owner`, `kind: implementation \| integration \| release`, `construction_dependencies`, nonempty `implementation_paths`, nonempty `required_check_ids` |
| `acceptance` | Object keyed by every applicable implementation/both QA check ID, including advisory/deferred checks |
| Acceptance allocation | Exactly one `owner_unit`, `prerequisite_units`, `prerequisite_checks`, `obligation_ids` |

Lists are explicit, duplicate-free; empty dependency lists are valid. Implementation paths are project-relative POSIX files, including relevant code/configuration/tests. They may be absent during planning. Owners must inventory all claim-relevant files; the checker cannot discover undeclared consumers or prove inventory completeness.

QA owns each check's `acceptance` definition: `required` boolean, `level: unit | integration | release`, `evidence_mode: component | real_consumers`, and nonempty `required_source_paths`. Store the check-ID → definition object in one JSON fence in a dedicated, localized QA section, referenced by `verification.acceptance_ref: {path, heading}`; the projection must match exactly. Define semantic scope from PRD/architecture/DoD before a plan exists. Resolve concrete source paths from the codebase map during reconciliation; this later lookup never becomes a QA creation dependency. Distinct bounded checks need distinct QA IDs; never overwrite a system check with component semantics.

Integration/release checks require `real_consumers` and an integration/release owner; release checks require a release owner. Required gate checks stay required. Required checks and each unit's `required_check_ids` agree bidirectionally; advisory checks still have an owner. An allocated obligation must have both a QA `verifies` link and an owner-unit `implements` link. Every required requirement clause/state needs required integration/release acceptance coverage. Unit checks demonstrate bounded contributions only. Deferred integration remains required/pending and cannot be counted as passed or not applicable.

## Runs, freshness and exceptions

`unit_runs` maps current unit IDs to records; absent records mean pending, never complete. Each record has `status: pending | running | blocked | completed`. Started records require timezone-aware `started_at`, current `development_plan_hash`, and `approved_baseline_id` (explicit null for headless). Blocked records need `reason`; completed records also require `completed_at`. Findings use the verification contract's severity, release effect and `open | closed` status. Preserve superseded runs separately; never rebind their hashes to pretend they were rerun.

All required checks must be prepared/passed, have an actual executor and readable hash-bound evidence, no open blocking findings, current `evaluated_plan_hash`, and `evaluated_source_hashes` covering QA's required paths plus the owner/prerequisite units' implementation paths. The checker rehashes every declared file and evidence item. Authorization cannot be future-dated. Runs must follow authorization; check execution must fall between its owning unit's start and completion, and precede consuming checks. Required real-consumer checks also need `execution_mode: real_consumers` and evidence of kind `integration`, alongside other required classes (security, visual, etc.). Fixture or mock execution cannot satisfy this claim; fixture data used through actual consumers is allowed when the canonical check permits it. Evidence labels alone do not prove authenticity.

Each completed record is revalidated, including on resume; stale evidence or an open blocking finding makes the completion claim unusable. A later unit cannot rely on a predecessor completed after that later unit started. Release requires every unit complete plus all existing release gates; unit completion never implies product release readiness.

`unit_sequence_exceptions` is a list of `{path, content_hash}` receipts preserving actual user events. Each receipt contains `event: unit_sequence_exception`, `role: user`, original `message`, `prompt_id`, timezone-aware `received_at`, current `development_plan_hash`, explicit `approved_baseline_id`, target `unit_id`, and nonempty `prior_unit_ids` being skipped. It must follow the current implementation prompt and precede the exceptional start. Only earlier independent units may be skipped: exceptions never waive construction/acceptance prerequisites, required checks, completion evidence or release work. Unscoped generic continuation is not this event. The host authenticates original user provenance; the checker verifies its declared binding.

## Host boundary

After the fresh implementation prompt, run `--before implementation`. Immediately before each start/resume run `--start-unit UNIT-ID`; on success the host records the actual start and executes only authorized scope. After actual checks and findings are recorded, run `--complete-unit UNIT-ID` while the unit is running, then record its actual completion and rerun the same command to validate the persisted record. Revalidate before every later start. Nonzero exits block the transition; missing records must never default to success. All commands take `--project PATH` and are read-only.

The checker also validates unit records after the development-plan owner returns and during implementation/release checks and plan audits. It does not create runs, execute tests or grant authorization.

No production execution runner exists in this repository; its executables are checkers, installation/update helpers and tests. A separate assistant host/runner must enforce exit codes before dispatch and completion, persist receipts/results, and maintain an active-unit loop until validated completion or a genuine blocker/user-input boundary. An ordinary assistant turn ending must retain the unfinished active unit; it cannot authorize the next unit. Runtime scheduling/resumption must be implemented by that host. Neither Markdown nor this standalone checker can prevent a host/assistant from ending a turn. Planning correctness, evidence validation and runtime continuation enforcement are separate guarantees.
