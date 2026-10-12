# Independently completable implementation units

For planning, migration and implementation. Artifact dependencies stay in `pipeline-contract.json`; unit dependencies use these records.

## Mandatory full-unit execution

The plan owner must embed this rule in every generated/reconciled `docs/development-plan.md`, in `working_language`; a link or JSON alone is insufficient:

> Once implementation is authorized, ALWAYS finish the FULL active unit: all scoped work, required integration, tests, defect fixes and acceptance evidence. Continue without asking "shall I continue?"; a subtask, code edit, commit or progress report is not a stopping point. Pause only for a genuine blocker, required user input/permission, or an explicit user stop/change. Investigate failures and attempt safe in-scope fixes before declaring a blocker; never bypass safeguards, weaken acceptance or expand authority. At a pause report the unit ID, completed/remaining work, evidence, exact blocker/question and next action; keep unfinished work incomplete. Resume that unit when unblocked, revalidating changed sources. Later units require completion or a recorded explicit user sequencing exception, never waived prerequisites or acceptance.

## Planning and reconciliation

Under `strict_sequential`, units finish required acceptance using only their implementation and completed predecessors. Combine construction and acceptance dependencies, including prerequisite-check owners; reject cycles and prerequisites scheduled after consumers. Same-unit check dependencies must also be acyclic. Every required check's recursive prerequisites must be required acceptance of their owners, preventing premature owner completion. Resolve advisory-definition conflicts through QA, never projection edits.

Build and review this graph **before numbering units**. Read each unit's full work/acceptance, referenced QA task/fixtures and architecture interfaces. Ask: with every later unit absent, can this unit pass all its required checks? Record each prerequisite's source and reason in the unit's existing definition; a missing dependency in JSON is not independence. Check shared security, roles, learning/payment flows, user validation and release conditions, not only module imports. Return overbroad checks to QA for bounded additions, preserving full integration checks. Compare this walkthrough with the graph before declaring the plan validated.

Number dependency order, not feature categories. IDs use one shared prefix and a final ASCII integer, e.g. `UNIT-001`; numbers are unique and increase in `order`. Zero, padding and gaps are valid; `08a` and mixed prefixes are not. Every construction, acceptance and prerequisite-check-owner dependency has a **lower number** than its consumer. Reordering or exceptions cannot bypass this rule; same-unit checks must be acyclic.

Resolve forward dependencies through source-backed splits, merges or reordering. Give independently verifiable components and required system integration explicit acceptance owners. Component checks prove only bounded contributions; a unit promising full behavior stays incomplete until reconciled. Never relabel partial work as completion.

For release requiring assessment, use authoring → learning → assessment → release integration, then number. Merge only independently completable work; test each boundary.

Preserve existing IDs, allocations, results and authorization receipts in history. Keep valid IDs. Required renumbering needs an old → new ID/scope map and simultaneous reference updates, showing each moved obligation/check, owners, prerequisite and reason. Route changed scope/behavior through its source owner; material non-inferable decisions need the user. Reconcile affected architecture → DoD → QA → plan; retain unchanged sources/baseline. Changed plan bytes require a fresh explicit implementation prompt. Never invent exclusions, smaller criteria, earlier completion or historical consent.

## Version 1 records

Keep `checker_contract_version: 1` and `traceability_version: 1`; add `unit_contract_version: 1`. Missing/unsupported unit records require owner-reviewed migration at plan validation, implementation, audit of a plan, and release. Earlier authoring stages remain usable. `--snapshot` does not supply unit semantics or migrate records.

The plan owner writes one JSON fence in `docs/development-plan.md`, located by `definition_ref: {path, heading}`. The orchestrator mirrors it as `unit_plan`. Localize the dedicated heading (e.g. `## Unit Execution Contract`) to `working_language`; retain JSON keys. Explain scope/reconciliation in prose. Unit IDs match typed traceability definitions exactly.

| Field | Meaning |
|---|---|
| `policy` | `strict_sequential`; exceptions below authorize individual starts, not an alternate acceptance standard |
| `order` | Every current unit ID once, in increasing numeric execution order |
| `units` | Object keyed by unit ID |
| Unit | Nonempty `scope`, responsible `owner`, `kind: implementation \| integration \| release`, `construction_dependencies`, nonempty `implementation_paths`, nonempty `required_check_ids` |
| `acceptance` | Object keyed by every applicable implementation/both QA check ID, including advisory/deferred checks |
| Acceptance allocation | Exactly one `owner_unit`, `prerequisite_units`, `prerequisite_checks`, `obligation_ids` |

Lists are explicit and duplicate-free; dependencies may be empty. Implementation paths are project-relative POSIX files for relevant code/configuration/tests; planning permits absent files. Owners inventory all claim-relevant files; the checker cannot establish undeclared consumers or completeness.

When architecture declares [construction mechanisms](traceability-contract.md), `unit_plan` includes both `construction_ref` and `construction`. Allocate each required mechanism to a construction owner whose paths and clause contributions cover it, with bounded checks owned by that unit covering those paths/clauses. Split different owners' mechanisms upstream. This table adds no parallel dependency graph; existing construction/check prerequisites remain authoritative. Legacy records without either field remain compatible.

QA owns `acceptance`: boolean `required`, `level: unit | integration | release`, `evidence_mode: component | real_consumers`, nonempty `required_source_paths`. Its check-ID → definition object occupies one JSON fence in a dedicated localized QA section, referenced by `verification.acceptance_ref: {path, heading}` and mirrored exactly. Define scope from PRD/architecture/DoD before planning. Reconciliation resolves paths from the codebase map without creating a QA prerequisite. Give bounded checks distinct IDs; never replace system checks with component semantics.

Integration/release checks require `real_consumers` and an integration/release owner; release checks require a release owner. Required gate checks stay required. Required checks and each unit's `required_check_ids` agree bidirectionally; advisory checks still have an owner. An allocated obligation must have both a QA `verifies` link and an owner-unit `implements` link. Every required requirement clause/state needs required integration/release acceptance coverage. Unit checks demonstrate bounded contributions only. Deferred integration remains required/pending and cannot be counted as passed or not applicable.

## Runs, freshness and exceptions

`unit_runs` maps current unit IDs to records; absent records mean pending, never complete. Each record has `status: pending | running | blocked | completed`. Started records require timezone-aware `started_at`, current `development_plan_hash`, and `approved_baseline_id` (null for headless); storage-managed records also require stable `run_id`. Blocked records need `reason`; completed records also require `completed_at`. Findings use the verification contract's severity, release effect and `open | closed` status. Preserve superseded runs through verified history references; never rebind hashes/times to pretend they were rerun.

Required checks need prepared/passed status, actual executor, readable hash-bound evidence, no open blocker, current `evaluated_plan_hash`, and `evaluated_source_hashes` covering QA plus owner/prerequisite implementation paths. Rehash all declared sources/evidence; [shared inventories](evidence-storage-contract.md) retain identical maps. Authorization cannot be future-dated; runs follow it. Execute checks within their owning run, before consumers. Real-consumer checks require `execution_mode: real_consumers`, `integration` evidence and other required classes. Mocks/fixture execution cannot substitute; fixture data through actual consumers is allowed only by the canonical check. Labels do not prove authenticity.

Revalidate completed records, including on resume; stale evidence/open blockers invalidate completion. A predecessor must complete before its consumer starts. Release requires all units and existing gates; unit completion alone never proves release readiness.

### Reviewed acceptance reuse

Unchanged v1 records need no extension. A completed unit and every required passed check may share `revalidation_ref` (verified receipt/reference). Preserve original fields/hashes/evidence/times. Changed scope/ownership/acceptance/dependencies/non-plan definitions or required new tests prohibit retention.

Receipt: `version:1`, `event:unit_acceptance_revalidation`, `unit_id`, named `reviewer`, timezone-aware `reviewed_at`, `outcome:retained`, `original_plan_hash`, `current_plan_hash`, `approved_baseline_id`, `behavior_changed:false`, `claims_unchanged:true`, nonempty `impact_summary`, `retained_check_ids`, `retained_claims`, `original_context`, `current_source_hashes`, `changed_paths`, `required_new_check_ids:[]`. Cover every required owned check/allocated claim exactly; review follows original completion/current authorization, never future.

Immutable `original_context` JSON contains original `unit_plan`, completed `unit_run`, required passed `checks` map, all present non-plan `definition_source_hashes`, original `implementation_gate` and verified raw `plan_source`. Exclude only added `revalidation_ref`. Verify original bytes/hash/unique canonical section/authorization; current unit contract and definition bytes must match. Preserve original prompts before replacement.

Verify complete current sources: exactly the original inventory union, including QA/owner/prerequisite paths. Each difference needs `{path,original_hash,current_hash,behavior_changed:false,claims_unchanged:true,rationale}`. Missing/unexplained/affected work or altered observations block reuse. This permits reviewed prose/nonbehavioral changes, not automatic hash replacement.

Stored reviews bind unit/both plans/reviewer/time and matching provenance. Resolve observations with original execution/plan/inventory bindings. Recursively validate checks and combined unit dependencies before dependent review/new execution. Historical starts retain original chronology/authorization; new starts require current reviewed predecessors.

Changed plans still need fresh explicit implementation prompts. Review grants no start, refreshed observation or gate waiver. Hosts authenticate reviewer/impact; the checker verifies declarations/bytes.

`unit_sequence_exceptions` lists legacy `{path, content_hash}` receipts or direct/wrapped version 1 evidence references preserving actual user events. Each receipt contains `event: unit_sequence_exception`, `role: user`, original `message`, `prompt_id`, timezone-aware `received_at`, current `development_plan_hash`, explicit `approved_baseline_id`, target `unit_id`, and nonempty `prior_unit_ids` being skipped. It must follow the current implementation prompt and precede the exceptional start. Only earlier independent units may be skipped: exceptions never waive construction/acceptance prerequisites, required checks, completion evidence or release work. Unscoped generic continuation is not this event. The host authenticates original user provenance; the checker verifies its declared binding.

## Host boundary

After the fresh implementation prompt, run `--before implementation`. Immediately before each start/resume run `--start-unit UNIT-ID`; on success the host records the actual start and executes only authorized scope. After actual checks and findings are recorded, run `--complete-unit UNIT-ID` while the unit is running, then record its actual completion and rerun the same command to validate the persisted record. Revalidate before every later start. Nonzero exits block the transition; missing records must never default to success. All commands take `--project PATH` and are read-only.

The checker also validates unit records after the development-plan owner returns and during implementation/release checks and plan audits. It does not create runs, execute tests or grant authorization.

Parallel tasks may share the active unit only: assign exclusive writes, share reservations, serialize catalog mutation and integrate/check after workers settle. Stop responsible managed producers on exhaustion; mark incomplete without weakening acceptance. The host must enforce this rule, checker exits and progress. Forced context/session interruptions preserve the unfinished active unit. No production runner is included: Markdown/checker cannot mechanically prevent a turn ending or schedule a restart.
