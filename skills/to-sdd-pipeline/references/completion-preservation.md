# Current workflow, migration and completion preservation

Use the latest tested SDD release. New authoring uses 3/3; 2/2 retains conservative behavior and uses [reviewed adoption](contract3-adoption.md) for per-check comparison and seals. Version 1 is import-only. Opt-in 4/4 adds [reviewed evidence acceptance](reviewed-acceptance.md) for adequate legacy or contextless observations. Preserve history and permission.

## Boundaries and owners

Preserve completed unit IDs, obligations and original events. Reconcile pending additions, splits, merges and renumbering through the plan owner, including every requirement, check, prerequisite and consumer. Keep the numeric order contract. Same design and product scope are necessary but insufficient: changes to relevant shared requirements, implementation, tests, runtime/configuration, evidence or findings require revalidation. A new consumer can add integration obligations without changing an earlier bounded component claim.

PRD/design/architecture owners determine meanings; DoD owns completion/rerun conditions; QA owns checks and shared acceptance definitions; planning owns allocation/input review. The authorized executor records actual execution. The orchestrator indexes supplied returns, never invented decisions, results or equivalence. Helpers capture facts; the checker remains read-only.

Project AGENTS.md governs full-unit execution, pauses, coordination and recovery; history cannot restart an ended session. Approved-decision documentation corrections retain their narrow [authorization exception](authorization-corrections.md); actual pending-scope or unit-boundary changes need the normal fresh current-plan prompt. Archived permission never authorizes a new start; unchanged current permission retains its existing scope.

## Immutable history and current acceptance

For normal execution, capture the authorized context before starting; finalize completion only from an actual completed run whose required acceptance passes. Retain original plan bindings, chronology, authorization/correction receipts, sequencing exceptions, prototype-promotion receipts, implementation/evidence identities and QA results. Share immutable snapshots. A 4/4 review is a separate current acceptance decision, never a reconstructed context or completed run.

Assess revised plans directly against the actual completed run. Never chain assessments, rewrite hashes/timestamps or copy passes onto changed definitions. Genuine revalidation creates a new run, retaining history. Pending/running/blocked attempts remain unfinished; preserve partial work and resume through current authorization/acceptance.

New acceptance requirements may require a new run of the same unit. Preserve its original scope, kind, owner and implementation paths; retain old completion references in `completion_history`, add acceptance/prerequisites without dropping existing obligations, and mark current acceptance pending. Validate the revised graph and obtain the normal current-plan authorization before starting. Reassigning a completed identity to different work remains invalid.

Archive full canonical sources. Compare owner-reviewed relevant sections, shared definitions, exact check actions/outcomes, DoD conditions, source/test/configuration/dependency/runtime inputs and prerequisite acceptance. Review all changed canonical sources for new relevant obligations, including plan prose and structured fields; matching old inventories cannot exclude them. Missing/ambiguous selections cannot justify preservation.

For new plans, separate stable shared completion/evidence rules from mutable status and pending allocations into selectable headings before authorization/context capture. Review excluded sections for relevant obligations. Existing mixed sections may retain complete broader selections and incur conservative revalidation when status changes. Do not force restructuring for migration or narrow historical selections to force preservation. Reorganizing an existing authorized plan follows the normal authority or verified documentation-correction rules.

Report plan validity, historical acceptance and current permission separately: a valid plan may still need revalidation or authorization. Missing/stale acceptance blocks dependent starts and release; corrupt records, false assertions and lost obligations remain errors.

Unit prerequisites, generic gates, security and release use one resolved acceptance result. Stored labels alone never qualify. Show original results/dates and identify reused runs. Recheck current sources, evidence, findings and dependencies before dependent starts/resumes and release; full integration/release obligations remain required.

In contracts 3/4, owner-reviewed `history_integrity: {legacy_payloads: "audit_only"}` defers inactive `legacy_execution_archive` payloads only at ordinary gates. Default `every_gate`, audits, release and import/migration validate them. Metadata, membership and required proof remain checked. Reports include deferred counts and `not_audited_this_gate`; unknown last verification is null. This permits no pruning or overall cost guarantee.

[Lifecycle adoption](evidence-lifecycle.md) binds exact optional snapshot members through `history_integrity.optional_diagnostics_ref`. Full audits may omit only these reviewed diagnostics. Required proof/input/authority reads remain strict. Original records and outcomes remain unchanged.

## Resume and migration

Default to published CI-tested `stable`. An explicitly selected candidate requires recorded revision/scope, clean source, matching required CI and verified installed targets; report stable publication separately. Otherwise report unverified provenance. Update stale tooling through the supported updater; never overwrite edits, silently downgrade or substitute untested `main`. Installation never migrates projects.

During authorized SDD resume, inspect the actual project, sources, receipts and workers. Checkpoint and stop active legacy workers before migration. Read-only requests permit inspection only. Use `adopt-legacy` for supported version 1 records; a missing unit version is supported only before any unit plan or execution. For unsupported/malformed records, archive original bytes and available evidence first, then have owners recover only source-verified metadata. Never invent missing history. Preserve code, documents, IDs and original events; never rebuild, reset or delete work merely to change formats.

`migration_ready` validates conversion, archive and unchanged gate only; nested `project_validation` can remain blocked/incomplete. Inspect the candidate, activate with matching active/source hashes, rerun the checker and reconcile owners. Activation retains diagnostics and grants no acceptance/permission.

Migration archives actual legacy records, retains blocking findings and removes unsupported current-acceptance claims. Keep the exact implementation gate and receipts: unchanged valid authority retains its scope; missing/stale/invalid authority stays blocked. Do not rebind a changed plan or manufacture consent. Before rerunning old work, review evidence sufficiency through the 4/4 procedure when applicable. Reuse only computed applicable checks; execute unresolved, changed or fresh-only checks under fresh authorized contexts in dependency order. Never copy passes forward. Missing evidence/capability stays a named blocker. A newly required prompt concerns missing/changed authority, never the format upgrade itself.

Retain sound history on resume; revalidate affected toolchain/rule changes within current permission.

## Capture and correction procedure

1. Inspect current records, sources and original evidence. Perform the resume procedure above when needed. Preserve insufficient history as unverified and plan genuine revalidation; do not reconstruct consent or completion.
2. Have the concern owners review the exact acceptance input inventory and rerun conditions. Capture the authorized execution context before starting the unit. Record actual tests against their evaluated source versions; final changes invalidate affected evidence.
3. Validate the actual completed run and capture immutable completion history. Stage the manifest index, validate the complete candidate, then activate it only if the expected active revision and referenced sources still match. Serialize these operational writes. On interruption, retain the previous active manifest; incomplete staging is not completion.
4. For a plan correction, owners reconcile affected documents and pending-unit mappings. Preserve completed identity and original history. Calculate current applicability from reviewed inputs and the original run. Show specific changed/missing inputs and required checks; loss of acceptance does not itself require rebuilding code.
5. Validate the current plan separately from execution permission. Retain the existing fresh-prompt boundary outside the verified documentation-correction exception. New execution checks use the current graph/authorization; historical execution checks use the original graph/authorization and genuine original exceptions.
6. Before subsequent execution and release, recompute acceptance. Do not trust a cached assessment after any bound source, evidence, finding or runtime condition changes. Use the same result for every applicable gate.

## Worked example

When splitting pending work, preserve original completions and obligations; allocate new integration and revalidate affected security. Report acceptance, pending work, plan validity and permission separately.

## Records and helper

Use matched checker/unit versions: 2/2 conservative, 3/3 selective verification, 4/4 reviewed acceptance; keep `traceability_version: 1`. Existing history envelopes remain version 2. Preserve `unit_plan`, QA ownership and execution records. References are `{path, content_hash}` with project-relative regular files and SHA-256. The helper appends immutable records below `forge/unit-history/`; completed runs are never overwritten.

| Record | Binding and use |
| --- | --- |
| `execution_contexts[unit_id]` | Reference to `unit_execution_context`, captured before start; contains the actual authorized manifest, reviewed inventory, source snapshots and toolchain identity. |
| `unit_runs[unit_id]` after archival | `{status: "completed", completion_ref, applicability_ref?}`. Completion retains the original `run_id`, run, checks, context reference, promotion records and snapshot files. |
| `completion_history[unit_id]` | Original completion references retained when a new revalidation run replaces the active run. Archived results grant no current acceptance by themselves. |
| `unit_runs[unit_id].attempt_ref` | Immutable `unit_attempt` retaining an actual running/blocked run, every owned check including unrun checks, original context, current work snapshots and owner-reviewed status documents. Never completion. |
| `attempt_history[unit_id]` | Original unfinished-attempt references retained across retries. A continuation context points to its `prior_attempt_ref`; new evidence uses a distinct run ID. |
| `completion_applicability` | Direct original `completion_ref`, current plan hash, current reviewed inventory, immediately prior active manifest reference, explicit pending-unit mapping and calculated outcome/reasons. A stored outcome is never trusted without recomputation. |
| `legacy_history` | Actual version 1 archives remain `unverified_not_reusable`; the archive alone supplies no acceptance or permission. A separate 4/4 review may adopt sufficient original observations. |
| `reviewed_acceptance[unit_id]` | Append-only review references under 4/4; the latest is recomputed against current requirements. Original run status/times remain unchanged. See the [review contract](reviewed-acceptance.md). |
| Staged candidate and activation journal | Candidate manifest, expected active revision, observed inputs and validation report; journal preserves before/after manifest references for recovery. |

The inventory contains `review: {reviewer, reviewed_at, complete: true, rationale}`, non-secret `environment` identities, and `sources` covering every applicable canonical artifact. Each source selection uses `mode: "full"`, `mode: "sections"` with exact unique `headings`, or a permitted `mode: "unused"` with a reason. The helper calculates selected-byte hashes and binds current full canonical hashes. The owner must include shared definitions and new obligations; a mechanically valid selection does not establish semantic completeness.

Map relevant code/test/configuration/dependency paths in `execution_inputs` to `{mode: "file"}`, `{mode: "tree"}` or `{mode: "absent"}`. Tree fingerprints include membership; added files invalidate old observations. Bound selections to the unit; unrelated pending files should not invalidate earlier components. `absent` asserts absence; planned files to create use `file`. Require equal real before/after check fingerprints; record `evaluated_execution_inputs`, actual source hashes, result and evidence. Observations alone prove no test execution. Completion captures post-run inputs, allowing implementation to replace pre-start absence. Exclude credentials from snapshots.

Contract 3 derives `check_execution_fingerprints` from QA's reviewed [per-check inputs](unit-execution-contract.md#current-unit-records). Use `observe-inputs --check-id CHECK` before/after execution; retain its exact map as `evaluated_execution_inputs`. Missing review keeps whole-unit fallback; inputs unassigned to required checks enter every check. Canonical definitions, environment and prerequisites remain conservative.

Seal a passed `deterministic_isolated` check only after its independent execution group has settled, before attempt archival. The executor supplies a hash-bound `execution_group_settlement` version 1: `unit_id`, original `run_id`, `group_id`, `check_ids`, `completed_at`, `isolation: independent`, `status: settled`, `producer_state: stopped`, `cleanup_state: complete`, `accounting_state: complete`, and empty `pending_actions`, `unknown_outcomes`, `open_resources`. Retain actual supporting evidence; the checker validates declared agreement and storage accounting, not OS-cleanup authenticity. Unsettled groups and live/mutable-provider observations are not reusable under this policy.

Seals freeze original run facts, post-run canonical bytes and per-check dependencies/evidence, retaining the validated context reference. Attach each as the original check's `seal_ref`. A continuation may retain an applicable seal using `reused_from: {attempt_ref, seal_ref}` with unchanged executor, `run_id`, `executed_at`, evidence and outcome. The earlier unit stays interrupted/failed. Invalid seals block; valid but stale seals become `not_run` with `rerun_reasons`. No seal, fresh-only policy or `--fresh-checks` requires new execution. Current authority and inherited findings remain required; never reseal an inherited result as newly executed.

Use Python 3.12+ and bundled `scripts/sdd_history.py --project PROJECT`. For managed evidence, prepare verified original bytes under the [storage contract](evidence-storage-contract.md), then pass global `--evidence-cache PATH` before the command. History retains external references, compact receipts and source snapshots without copying bulky archives into Git. Missing originals, dependency closure or required accounting block acceptance. Migration may preserve unavailable legacy references as unverified history; restore/review sufficient proof or execute checks whose essential facts remain missing. Storage/history preserve existing authority only.

Optional `source_archive_index_ref` names an immutable `unit_source_archive_index`,
binding original record references, snapshot roots, paths/hashes to managed
evidence without rewriting contexts/attempts/results. Use
`create-source-archive-index --mapping FILE` with reviewed mappings; optional
`--encoding sha_objects_v1` retains all logical members with one reference per SHA.
Default `private_copy` uses independent verified payload inodes; explicit
`--view-strategy shared_cache_links` selects verified cache hardlinks with fresh
integrity checks. Shared views lack private isolation: retain cache objects,
count physical occupancy once/logical generation separately, fail missing/changed
bytes. Reserve measured preparation capacity before either operation; explicitly
run `prepare-source-views --index-ref REF_JSON --max-bytes N --max-files N` before
checking. The checker never fetches/prepares; neither mode proves tests/completion.

Prepared-reference closures use the validated project metadata limits, including
fresh resolvers. Project-aware storage may classify exact verified source-view
members as payloads; controls and unknown JSON remain metadata. Require immutable
native membership, ordinary-byte/inode proof, aggregate input/reference bounds
and an operation-exit audit. Missing project context keeps conservative counting.
Payload occupancy and logical file/generation accounting still apply; legitimate
older views gain no current acceptance through classification.

Its commands are:

- `capture-context --unit ID --inventory reviewed.json`: returns the pre-start reference; index it in `execution_contexts` before the normal checker start boundary.
- `observe-inputs --unit ID [--inventory reviewed.json] [--check-id CHECK]`: reads execution inputs from the supplied or captured inventory. Contract 3's check selector resolves reviewed per-check inputs or conservative fallback. Bind matching before/after observations to the genuine check event.
- `seal-group --unit ID --check-ids CHECK_A CHECK_B --settlement-ref settlement-ref.json [--inventory reviewed.json]`: seals passed, independently settled checks with one shared gate validation. Attach each returned check ID's reference as `seal_ref` before archiving. For one check, `seal-check --check-id CHECK` uses the same other arguments. Neither command executes tests or completes a unit.
- `capture-completion --unit ID --context-ref context-ref.json --run-id ACTUAL_RUN_ID [--inventory reviewed-current.json]`: validates completion and returns its immutable reference. Canonical owner updates (e.g. QA history) require fresh owner review after checks, with unchanged relevant definitions. Retain original context/post-run provenance separately; unfinished work cannot complete.
- `capture-attempt --unit ID --context-ref context-ref.json --run-id ACTUAL_RUN_ID --outcome failed|interrupted --inventory reviewed-current.json`: preserves unfinished work without passed acceptance. Normally add `attempt_ref` to the unchanged run and stage/activate before continuation; malformed original start metadata uses the bounded recovery below. Status-only owner edits require fresh review, unchanged relevant acceptance/authority and original check hashes/times/outcomes.
- `observe-runtime --probes probes.json`: executes explicit identity commands once and returns an immutable receipt. The input maps identity names to argument lists starting with an absolute executable; no shell is used. Its `environment` maps each name to stripped stdout. Probe the runtime/session that will execute evidence; an installed binary version alone does not identify an attached process. Use non-secret, bounded identity commands that do not start background helpers.
- `capture-continuation --unit ID --attempt-ref attempt-ref.json --run-id NEW_RUN_ID --inventory reviewed-continuation.json [--fresh-checks]`: returns candidate `manifest`, `context_ref` and `prior_attempt_ref`. Fresh inventory includes the new probe's `runtime_observation_ref`/exact `environment`. Contract 3 validates eligible seals; other checks become unrun. Save candidate, reconcile progress, stage/activate, pass `--start-unit`, record actual start. Execute missing/failed/stale checks; version 2 always requires fresh checks.
- `--manifest candidate-manifest.json assess --completion-ref completion-ref.json --inventory reviewed.json --pending-map pending-map.json`: reviews the candidate against the actual active `forge/sdd-manifest.json`. Mapping values are current unit IDs; keys are changed pending IDs or `__added__`. Preserve every old acceptance obligation, including obligations introduced in earlier revisions.
- `stage --candidate candidate-manifest.json --expected-manifest-hash SHA256 [--pending-map pending-map.json]`, then `activate --candidate-ref candidate-ref.json --expected-manifest-hash SHA256`: validate and atomically replace the active manifest only while the expected revision and inputs still match. Mapping may come from its matching assessments; supply it explicitly for a transition without them.
- `adopt-legacy --expected-manifest-hash SHA256`: archives supported version 1 records and stages version 2 with the exact existing gate. `migration_ready` means conversion only; inspect nested `project_validation`, activate and verify. Then review adequate evidence under 4/4 or run missing checks; never reconstruct pre-start context or old passes.
- `recover --journal-ref journal-ref.json`: reports whether the recorded activation happened, did not happen, or conflicts with later state. It never overwrites later work or silently removes another writer's lock.

Reference arguments name JSON files containing returned references, not history envelopes. Put the finished run and owner-reconciled results in a candidate; use `--manifest candidate-manifest.json capture-completion ...`, index its reference, then stage/activate. Completion requires complete-unit validation; never publish unvalidated completion. Save actual command outputs/checker reports.

### Malformed unfinished-run recovery

When original unfinished-run metadata prevents normal intermediate attempt staging,
archive the exact original bytes and available evidence first. Validate the immutable
attempt, original authority and current plan/prompt. Owners review current sources
and fresh runtime inventory. `capture-continuation` may consume that attempt directly
against the unchanged live manifest, without separately activating its `attempt_ref`.
Retain the exact original run/checks/context and every history reference; create a
distinct pending run and fresh context linked to that attempt, retaining only
validated contract-3 seals; other checks stay `not_run`. Stage/activate against the unchanged active hash,
then pass implementation/start gates before execution. Missing history, invalid
authority or failed validation blocks recovery. Never reconstruct old fields,
rebind results, grant acceptance/permission or alter accounting/quotas. This groups
publication only; the normal sequence remains the default.

Capture attempts before repairs when possible. Edits, deletions or new tree members
differing from test inputs retain old observations/current work as
`observation_validity: unverified_stale_inputs`. Capture validates bytes/authority,
not unavailable tested sources or results against later work. Validation treats
these checks as unrun and reports preserved failure/interruption; source manifest
and archive retain original outcomes. Changed acceptance/authority or corrupt/
missing evidence still block capture. Continuations rerun every required check without a valid applicable seal.

Only validated limits-only `forge/evidence-policy.json` lineage may replace its exact frozen raw-ancestor fingerprint during reconciliation and fresh continuation. Preserve other inputs, acceptance, authority and original records. Stale starts and completions remain blocked until fresh review, runtime and checks.

Probe continuation runtime between attempt/context captures. After the new start,
probe the execution session again; bind its receipt to each executed check's
`runtime_observation_ref` before `executed_at`. Completion requires observed environment to match the new
context. Drift requires another preserved attempt/continuation, never rebinding
old receipts. Command identities prove neither host authenticity nor continuous
stability; the harness must verify actual runtime at the test boundary.

Retain inherited findings/original fields. Closing requires status `closed` and
`closure: {closed_at, rationale, check_ids}` naming this continuation's fresh passes
with readable evidence and matching inputs/runtime. Close after checks, before
completion; deletion, substituted identity or bare status cannot clear findings.
Reclosing a reopened finding may replace closure; history retains the prior one.

Source documents are owner-written before candidate validation; activation makes only the manifest replacement atomic. During staging, other workers must not dispatch from an invalidated old manifest. A crashed writer's lock needs verified process ownership and explicit local recovery; incomplete directories grant no authority. Re-run validation after recovery.

## Compatibility and verification

Keep version 1 import/history-only. Preserve 2/2 behavior; per-check/sealed reuse requires 3/3 or 4/4, reviewed acceptance requires 4/4. Test frozen predecessors at planning, start, completion, audit and release. Reject mixed pairs and newer semantics disguised as older versions. Preserve history, approval and security requirements; unsupported tools must stop rather than ignore acceptance fields.

Regression tests cover repeated corrections, exact QA wording/shared definitions, missing or changed sources/evidence/runtime, invalid historical authority, partial attempts, completed-ID reassignment, obligation mappings, original order/exceptions, prototype reuse, real-consumer release acceptance, interrupted activation and concurrent changes. A separate fresh-context assistant exercise must produce actual observations, use genuine available history and disclose unavailable approval/host behavior. Record deterministic instruction loads including conditional references and retries separately from observed agent cost/time. No synthetic fixture proves product acceptance or authenticates a user event.
