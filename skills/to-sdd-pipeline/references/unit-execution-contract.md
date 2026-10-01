# Independently completable implementation units

For planning, migration and implementation. Artifact dependencies stay in `pipeline-contract.json`; unit dependencies use these records.

## Mandatory full-unit execution

The plan owner must embed this rule in every generated/reconciled `docs/development-plan.md`, in `working_language`; a link or JSON alone is insufficient:

> Once implementation is authorized, ALWAYS finish the FULL active unit: all scoped work, required integration, tests, defect fixes and acceptance evidence. Continue without asking "shall I continue?"; a subtask, code edit, commit or progress report is not a stopping point. Pause only for a genuine blocker, required user input/permission, or an explicit user stop/change. Investigate failures and attempt safe in-scope fixes before declaring a blocker; never bypass safeguards, weaken acceptance or expand authority. At a pause report the unit ID, completed/remaining work, evidence, exact blocker/question and next action; keep unfinished work incomplete. Resume that unit when unblocked, revalidating changed sources. Later units require completion or a recorded explicit user sequencing exception, never waived prerequisites or acceptance.

## Planning and reconciliation

Under `strict_sequential`, units finish required acceptance using only their implementation and completed predecessors. Combine construction and acceptance dependencies, including prerequisite-check owners; reject cycles and prerequisites scheduled after consumers. Same-unit check dependencies must also be acyclic. Every required check's recursive prerequisites must be required acceptance of their owners, preventing premature owner completion. Resolve advisory-definition conflicts through QA, never projection edits.

Build and review this graph **before numbering units**. Read each unit's full work/acceptance, referenced QA task/fixtures and architecture interfaces. Ask: with every later unit absent, can this unit pass all its required checks? Record each prerequisite's source and reason in the unit's existing definition; a missing dependency in JSON is not independence. Check shared security, roles, learning/payment flows, user validation and release conditions, not only module imports. Return overbroad checks to QA for bounded additions, preserving full integration checks. Compare this walkthrough with the graph before declaring the plan validated.

Number the resulting dependency order, not feature categories. All active IDs use one shared prefix plus a final ASCII integer, e.g. `UNIT-001` or `UNIT-EXP-08`; numbers are unique and strictly increase in `order`. Zero, padding and gaps are allowed; suffixes such as `08a` and mixed prefixes are not. Every construction, acceptance and prerequisite-check-owner dependency must have a **lower number** than its consumer. Reordering the list to put 09 before 08, or a sequencing exception, cannot bypass this rule. Same-unit checks remain allowed if acyclic.

Resolve forward dependencies through source-backed splits, merges or reordering. Give independently verifiable components and required system integration explicit acceptance owners. Component checks prove only bounded contributions; a unit promising full behavior stays incomplete until reconciled. Never relabel partial work as completion.

For example, authoring plus release cannot finish before learning/assessment if release tests require both. Split into authoring → learning → assessment → release integration, then number; merging is valid when genuinely one useful unit. Test each resulting boundary, not just the reordered labels.

For an existing plan, preserve old IDs, allocations, results and authorization receipts in history. Keep valid IDs; when renumbering is necessary, record an explicit old → new ID/scope map and update all active references together. Show every moved obligation/check, old and new owner, prerequisite and reason. Reconcile changed scope/behavior through its source owner; material non-inferable decisions need the user. Reconcile architecture → DoD → QA → plan where affected, retaining unchanged sources and the approved baseline. Changed plan bytes invalidate implementation authorization: pause for a fresh explicit implementation prompt. Do not manufacture acceptance exclusions, smaller criteria, earlier completion or historical consent.

## Version 1 records

Keep `checker_contract_version: 1` and `traceability_version: 1`; add `unit_contract_version: 1`. Missing/unsupported unit records require owner-reviewed migration at plan validation, implementation, audit of a plan, and release. Earlier authoring stages remain usable. `--snapshot` does not supply unit semantics or migrate records.

The plan owner writes one JSON fence in a dedicated section of `docs/development-plan.md`, located by its `definition_ref: {path, heading}`. The orchestrator records its identical object as `unit_plan`. Localize the heading (for example, `## Unit Execution Contract`) to `working_language`; keep JSON keys unchanged. Surrounding prose explains scope/reconciliation. Unit IDs exactly match typed traceability definitions.

| Field | Meaning |
|---|---|
| `policy` | `strict_sequential`; exceptions below authorize individual starts, not an alternate acceptance standard |
| `order` | Every current unit ID once, in increasing numeric execution order |
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

The executing assistant/host must enforce this rule and checker exits and persist progress. Forced context/session interruptions preserve the unfinished active unit. No production runner is included: Markdown/checker cannot mechanically prevent a turn ending or schedule a restart.
