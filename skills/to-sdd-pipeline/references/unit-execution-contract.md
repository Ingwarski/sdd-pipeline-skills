# Independently completable implementation units

For planning, migration and implementation. Artifact dependencies stay in `pipeline-contract.json`; unit dependencies use these records.

## Project instructions and unit completion

Project `AGENTS.md` owns coding execution behaviour: full-unit continuation, coordination, permitted pauses and resumption. This contract owns unit dependencies, completion data, authorization bindings and validation transitions. Before implementation or resumption, the main agent must verify the effective instruction sources under the [setup contract](project-instructions.md), read them and provide relevant instructions to delegated workers. Preserve the instruction basis and recoverable checkpoints in existing execution records; changed policy requires review of affected execution.

The plan states the completion condition once: a unit remains incomplete until its scoped work, integration, required checks and acceptance evidence meet the referenced DoD and QA requirements. Reference project `AGENTS.md` for execution behaviour; do not copy its continuation or pause policy.

Plan authoring does not require project `AGENTS.md` to exist. If absent, record [project instruction setup](project-instructions.md) as a handoff prerequisite before implementation. The plan owner must not create it or duplicate its behavioural rules in the plan.

## Planning and reconciliation

Under `strict_sequential`, units finish required acceptance using only their implementation and completed predecessors. Combine construction and acceptance dependencies, including prerequisite-check owners; reject cycles and prerequisites scheduled after consumers. Same-unit check dependencies must also be acyclic. Every required check's recursive prerequisites must be required acceptance of their owners, preventing premature owner completion. Resolve advisory-definition conflicts through QA, never projection edits.

Build and review this graph **before numbering units**. Read each unit's full work/acceptance, referenced QA task/fixtures and architecture interfaces. Ask: with every later unit absent, can this unit pass all its required checks? Record each prerequisite's source and reason in the unit's existing definition; a missing dependency in JSON is not independence. Check applicable product flows, security, roles, user validation and release conditions, not only module imports. Return overbroad checks to QA for bounded additions, preserving full integration checks. Compare this walkthrough with the graph before declaring the plan validated.

Number dependency order, not feature categories. IDs use one shared prefix and a final ASCII integer, e.g. `UNIT-001`; numbers are unique and increase in `order`. Zero, padding and gaps are valid; `08a` and mixed prefixes are not. Every construction, acceptance and prerequisite-check-owner dependency has a **lower number** than its consumer. Reordering or exceptions cannot bypass this rule; same-unit checks must be acyclic.

Resolve forward dependencies through source-backed splits, merges or reordering. Give independently verifiable components and required system integration explicit acceptance owners. Component checks prove only bounded contributions; a unit promising full behavior stays incomplete until reconciled. Never relabel partial work as completion.

Derive producer, consumer and acceptance order from project requirements and interfaces. No domain-specific sequence overrides that graph. Merge only independently completable work; test each boundary.

For an existing plan, preserve old IDs, allocations, results and authorization receipts in history. Keep valid IDs; when renumbering is necessary, record an explicit old → new ID/scope map and update all active references together. Show every moved obligation/check, old and new owner, prerequisite and reason. Reconcile changed scope/behavior through its source owner; material non-inferable decisions need the user. Reconcile architecture → DoD → QA → plan where affected, retaining unchanged sources and the approved baseline. Changed plan bytes require a fresh explicit implementation prompt unless the [verified documentation-correction exception](authorization-corrections.md) preserves existing authorization. Do not manufacture acceptance exclusions, smaller criteria, earlier completion or historical consent.

## Record versions

Use [completion preservation](completion-preservation.md). Contract 3 adds reviewed per-check inputs and sealed-result reuse; contract 2 remains supported with whole-unit comparison and fresh continuation checks. Version 1 is import/audit only. Owners review adoption of new semantics; installation never rewrites project records or grants permission.

## Current unit records

New efficient authoring uses `checker_contract_version: 3`, `unit_contract_version: 3` and `traceability_version: 1`; retain existing 2/2 records until owner-reviewed adoption. Mixed pairs are invalid. Missing/unsupported records need reconciliation at plan/implementation/release validation; read-only audits never migrate. `--snapshot` supplies no unit semantics.

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

For declared mechanisms, follow the [construction allocation contract](traceability-contract.md). Copy `artifacts.architecture.construction_ref` exactly to `unit_plan.construction_ref` and provide complete `unit_plan.construction`. Required owners/checks cover paths and obligations. Existing prerequisite graphs remain authoritative. Only architecture without a mechanism declaration permits legacy omission.

QA owns `acceptance`: boolean `required`, `level: unit | integration | release`, `evidence_mode: component | real_consumers`, nonempty `required_source_paths`. Its check-ID → definition object occupies one JSON fence in a dedicated localized QA section, referenced by `verification.acceptance_ref: {path, heading}` and mirrored exactly. Define scope from PRD/architecture/DoD before planning. Reconciliation resolves paths from the codebase map without creating a QA prerequisite. Give bounded checks distinct IDs; never replace system checks with component semantics.

In contract 3, QA may define `verification.source_sets: {id: [relative paths]}` in a JSON section bound by `source_sets_ref: {path, heading}`. Acceptance adds `source_set_ids`; their union with `required_source_paths` must be nonempty. `dependency_review: {complete: true, reviewer, rationale}` enables per-check comparison; otherwise use whole-unit fallback. Include tests, fixtures, shared dependencies and configuration. Required checks collectively account for execution inputs; unassigned selections enter every check, preserving tree membership. Optional `reuse_policy: deterministic_isolated` permits validated sealed reuse; omitted or `fresh` requires execution. See [capture and applicability](completion-preservation.md#records-and-helper).

Integration/release checks require `real_consumers` and an integration/release owner; release checks require a release owner. Required gate checks stay required. Required checks and each unit's `required_check_ids` agree bidirectionally; advisory checks still have an owner. An allocated obligation must have both a QA `verifies` link and an owner-unit `implements` link. Every required requirement clause/state needs required integration/release acceptance coverage. Unit checks demonstrate bounded contributions only. Deferred integration remains required/pending and cannot be counted as passed or not applicable.

## Runs, freshness and exceptions

`unit_runs` maps current unit IDs to records; absent records mean pending, never complete. Each record has `status: pending | running | blocked | completed`. Started records require timezone-aware `started_at`, current `development_plan_hash`, and `approved_baseline_id` (null for headless); storage-managed records also require stable `run_id`. Blocked records need `reason`; completed records also require `completed_at`. Findings use the verification contract's severity, release effect and `open | closed` status. Preserve superseded runs through verified history references; never rebind hashes/times to pretend they were rerun.

Required checks need prepared/passed status, actual executor, readable hash-bound evidence, no open blocker, valid plan/source bindings and the contract's actual input inventory. Version 2 covers QA plus owner/prerequisite implementation paths; reviewed contract-3 inputs follow the rules above. Rehash declared sources/evidence; [shared inventories](evidence-storage-contract.md) retain identical maps. Fresh checks execute within their owning run before consumers; validated contract-3 seals retain original run/times through [completion preservation](completion-preservation.md). Real-consumer checks need `execution_mode: real_consumers`, integration evidence and other required classes. Mocks cannot substitute; fixture data through actual consumers requires canonical permission. Labels prove no authenticity.

Preserve failed/interrupted runs with `capture-attempt` and an `attempt_ref` on
their unchanged running/blocked record. This path permits reviewed status-only
owner updates without completion. It retains all actual check outcomes and
preserves stale observations separately from later partial work. A fresh retry
uses `capture-continuation`, a distinct run ID and new pre-start context; earlier
attempts remain in `attempt_history`. Probe the actual execution runtime and bind
the fresh receipt to continuation checks. Follow the normal command order and
nonaccepting-history rules in [completion preservation](completion-preservation.md),
including its bounded [malformed unfinished-run recovery](completion-preservation.md#malformed-unfinished-run-recovery)
when original metadata prevents intermediate attempt staging.

Revalidate completed records, including on resume; stale evidence/open blockers invalidate completion. A predecessor must complete before its consumer starts. Release requires all units and existing gates; unit completion alone never proves release readiness.

### Current acceptance and historical compatibility

Current work uses [completion preservation](completion-preservation.md): capture authorized context before execution, retain immutable actual completion, and calculate current applicability against owner-reviewed inputs and the original run. Shared unit, security and release gates consume that same resolved acceptance. Changed relevant definitions, sources, runtime, findings or evidence require specific revalidation; no historical pass or changed-plan review grants implementation authority.

The legacy `revalidation_ref` receipt is readable only for preserving and auditing imported history. Migration archives its original observations and receipts as unverified history and removes old current-acceptance claims. It does not carry version 1 acceptance into version 2. Perform genuine current checks under valid existing authorization before dependent execution.

`unit_sequence_exceptions` lists legacy `{path, content_hash}` receipts or direct/wrapped version 1 evidence references preserving actual user events. Each receipt contains `event: unit_sequence_exception`, `role: user`, original `message`, `prompt_id`, timezone-aware `received_at`, current `development_plan_hash`, explicit `approved_baseline_id`, target `unit_id`, and nonempty `prior_unit_ids` being skipped. It must follow the current implementation prompt and precede the exceptional start. Only earlier independent units may be skipped: exceptions never waive construction/acceptance prerequisites, required checks, completion evidence or release work. Unscoped generic continuation is not this event. The host authenticates original user provenance; the checker verifies its declared binding.

## Host boundary

With current implementation authorization, run `--before implementation`. Immediately before each start/resume run `--start-unit UNIT-ID`; on success the main agent or explicitly selected executor records the actual start and executes only authorized scope. After actual checks and findings are recorded, run `--complete-unit UNIT-ID` while the unit is running, then record its actual completion and rerun the same command to validate the persisted record. Revalidate before every later start. Nonzero exits block the transition; missing records must never default to success. All commands take `--project PATH` and are read-only.

The checker also validates unit records after the development-plan owner returns and during implementation/release checks and plan audits. It does not create runs, execute tests, verify host instruction loading or grant authorization. The schema/checker does not enforce host policy loading or checkpoints. Record migration uses the bundled history helper; do not invent legacy fields or relabel manual preflight as checker enforcement.

The main agent or explicitly selected executor applies project `AGENTS.md` for worker coordination, continuation, permitted pauses and resumption. Keep shared evidence reservations and operational record mutations serialized. Enforce checker exits and record actual progress; missing or failed required evidence keeps completion blocked. Instructions and checker commands cannot restart an ended session.
Stop responsible managed evidence producers on reservation exhaustion and retain incomplete status without weakening acceptance. Forced interruptions preserve the unfinished active unit.
