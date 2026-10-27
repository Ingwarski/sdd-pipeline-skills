# Current workflow, migration and completion preservation

Use the latest tested SDD release for new/resumed projects. Version 2 is current; version 1 is import-only. On authorized resume, migrate without a version-choice prompt, preserving work and reverifying acceptance. This adds no approval, implementation permission, skill name or canonical document.

## Boundaries and owners

Preserve completed unit IDs, obligations and original events. Reconcile pending additions, splits, merges and renumbering through the plan owner, including every requirement, check, prerequisite and consumer. Keep the numeric order contract. Same design and product scope are necessary but insufficient: changes to relevant shared requirements, implementation, tests, runtime/configuration, evidence or findings require revalidation. A new consumer can add integration obligations without changing an earlier bounded component claim.

PRD/design/architecture owners determine their meanings; DoD owns completion/rerun conditions; QA owns exact checks and shared acceptance definitions; the plan owner allocates units and reviews their relevant inputs. The authorized executor records actual starts, tests and observations. The orchestrator stages/indexes operational history and the manifest from those returns. It never invents decisions, test results or semantic equivalence. Helpers calculate/capture supplied facts; the checker remains read-only.

Project AGENTS.md continues to govern full-unit execution, six pause reasons, coordination and recovery. A history record cannot restart an ended session. Existing approved-decision documentation corrections retain their narrow [authorization exception](authorization-corrections.md); actual pending-scope or unit-boundary changes need the normal fresh current-plan prompt. Archived permission alone never authorizes a new start; unchanged current permission remains valid only within its existing scope.

## Immutable history and current acceptance

Capture the actual authorized context before execution can overwrite it. Finalize completion only from an actual completed run whose required acceptance passes. Retain original plan bindings, chronology, authorization/correction receipts, sequencing exceptions, prototype-promotion receipts, implementation/evidence identities and original QA results. Shared immutable snapshots are referenced rather than copied into every unit.

Assess revised plans directly against the actual completed run. Never chain assessments, rewrite hashes/timestamps or copy passes onto changed definitions. Genuine revalidation creates a new run, retaining history. Pending/running/blocked attempts remain unfinished; preserve partial work and resume through current authorization/acceptance.

New acceptance requirements may require a new run of the same unit. Preserve its original scope, kind, owner and implementation paths; retain old completion references in `completion_history`, add acceptance/prerequisites without dropping existing obligations, and mark current acceptance pending. Validate the revised graph and obtain the normal current-plan authorization before starting. Reassigning a completed identity to different work remains invalid.

Archive full canonical sources. Compare owner-reviewed relevant sections, shared definitions, exact check actions/outcomes, DoD conditions, source/test/configuration/dependency/runtime inputs and prerequisite acceptance. Review all changed canonical sources for new relevant obligations, including plan prose and structured fields; matching old inventories cannot exclude them. Missing/ambiguous selections cannot justify preservation.

For new plans, separate stable shared completion/evidence rules from mutable status and pending allocations into selectable headings before authorization/context capture. Review excluded sections for relevant obligations. Existing mixed sections may retain complete broader selections and incur conservative revalidation when status changes. Do not force restructuring for migration or narrow historical selections to force preservation. Reorganizing an existing authorized plan follows the normal authority or verified documentation-correction rules.

Version 2 reports plan validity, historical completion applicability and current execution permission separately. A coherent revised plan may validate while earlier acceptance requires revalidation and execution awaits a prompt. Missing or stale acceptance cannot satisfy dependent starts or release. Corrupt records, false assertions and lost obligations are errors; a structurally invalid plan is never accepted merely because history exists.

One resolved acceptance result is used for unit prerequisites, generic gates, security and release. Stored historical `passed` or `completed` labels alone never qualify. Keep actual execution results and dates visible; report when acceptance relies on an earlier run rather than implying it ran again. Recheck applicability against current sources, evidence, findings and dependencies before each dependent start/resume and at release. Full integration/release obligations remain required.

## Resume and migration

Verify the actual installed collection against published CI-tested `stable`. If stale, use the supported updater; never substitute untested `main`, overwrite local edits or claim unverified currency. Installation neither scans projects nor migrates records.

During authorized SDD resume, inspect the actual project, sources, receipts and workers. Checkpoint and stop active legacy workers before migration. Read-only requests permit inspection only. Use `adopt-legacy` for supported version 1 records; a missing unit version is supported only before any unit plan or execution. For unsupported/malformed records, archive original bytes and available evidence first, then have owners recover only source-verified metadata. Never invent missing history. Preserve code, documents, IDs and original events; never rebuild, reset or delete work merely to change formats.

`migration_ready` validates conversion, archive and unchanged gate only; nested `project_validation` can remain blocked/incomplete. Inspect the candidate, activate with matching active/source hashes, rerun the checker and reconcile owners. Activation retains diagnostics and grants no acceptance/permission.

Migration archives actual legacy records, retains blocking findings and removes old current-acceptance claims. Keep the exact implementation gate and receipts: valid unchanged authority retains its scope; missing, stale or invalid authority remains blocked. Do not rebind a changed plan or manufacture consent. Review the current requirements/QA, capture fresh authorized context and run genuine acceptance checks in dependency order before relying on earlier work. Old passes cannot be copied forward. Missing evidence/capability remains a named blocker; fixes follow existing authorization boundaries. A newly required prompt is for missing or changed authority, never for the format upgrade itself.

Retain current-format history/applicability; toolchain/rule changes require affected revalidation, not clearing sound history each resume. Continue only with current checks and existing permission.

## Capture and correction procedure

1. Inspect current records, sources and original evidence. Perform the resume procedure above when needed. Preserve insufficient history as unverified and plan genuine revalidation; do not reconstruct consent or completion.
2. Have the concern owners review the exact acceptance input inventory and rerun conditions. Capture the authorized execution context before starting the unit. Record actual tests against their evaluated source versions; final changes invalidate affected evidence.
3. Validate the actual completed run and capture immutable completion history. Stage the manifest index, validate the complete candidate, then activate it only if the expected active revision and referenced sources still match. Serialize these operational writes. On interruption, retain the previous active manifest; incomplete staging is not completion.
4. For a plan correction, owners reconcile affected documents and pending-unit mappings. Preserve completed identity and original history. Calculate current applicability from reviewed inputs and the original run. Show specific changed/missing inputs and required checks; loss of acceptance does not itself require rebuilding code.
5. Validate the current plan separately from execution permission. Retain the existing fresh-prompt boundary outside the verified documentation-correction exception. New execution checks use the current graph/authorization; historical execution checks use the original graph/authorization and genuine original exceptions.
6. Before subsequent execution and release, recompute acceptance. Do not trust a cached assessment after any bound source, evidence, finding or runtime condition changes. Use the same result for every applicable gate.

## Worked example

After pending Profile revisions/Notifications splits, assess completed Login directly from its original run. Retain obligations/mappings; assign new integration to new work and revalidate changed session security. Report applicability, pending work, plan validity and permission separately.

## Records and helper

Use both `checker_contract_version: 2` and `unit_contract_version: 2`; keep `traceability_version: 1`. Keep the existing `unit_plan`, acceptance ownership, QA definitions and actual execution records. A reference is exactly `{path, content_hash}`, with a project-relative regular file and SHA-256. The helper appends immutable records below `forge/unit-history/`; it never overwrites a completed run.

| Record | Binding and use |
| --- | --- |
| `execution_contexts[unit_id]` | Reference to `unit_execution_context`, captured before start; contains the actual authorized manifest, reviewed inventory, source snapshots and toolchain identity. |
| `unit_runs[unit_id]` after archival | `{status: "completed", completion_ref, applicability_ref?}`. Completion retains the original `run_id`, run, checks, context reference, promotion records and snapshot files. |
| `completion_history[unit_id]` | Original completion references retained when a new revalidation run replaces the active run. Archived results grant no current acceptance by themselves. |
| `unit_runs[unit_id].attempt_ref` | Immutable `unit_attempt` retaining an actual running/blocked run, every owned check including unrun checks, original context, current work snapshots and owner-reviewed status documents. Never completion. |
| `attempt_history[unit_id]` | Original unfinished-attempt references retained across retries. A continuation context points to its `prior_attempt_ref`; new evidence uses a distinct run ID. |
| `completion_applicability` | Direct original `completion_ref`, current plan hash, current reviewed inventory, immediately prior active manifest reference, explicit pending-unit mapping and calculated outcome/reasons. A stored outcome is never trusted without recomputation. |
| `legacy_history` | References to actual version 1 manifest archives, labeled `unverified_not_reusable`. These preserve history and cannot satisfy a check or authorize a start. |
| Staged candidate and activation journal | Candidate manifest, expected active revision, observed inputs and validation report; journal preserves before/after manifest references for recovery. |

The inventory contains `review: {reviewer, reviewed_at, complete: true, rationale}`, non-secret `environment` identities, and `sources` covering every applicable canonical artifact. Each source selection uses `mode: "full"`, `mode: "sections"` with exact unique `headings`, or a permitted `mode: "unused"` with a reason. The helper calculates selected-byte hashes and binds current full canonical hashes. The owner must include shared definitions and new obligations; a mechanically valid selection does not establish semantic completeness.

Map relevant code/test/configuration/dependency paths in `execution_inputs` to `{mode: "file"}`, `{mode: "tree"}` or `{mode: "absent"}`. Tree fingerprints include membership; added files invalidate old observations. Bound selections to the unit; unrelated pending files should not invalidate earlier components. `absent` asserts absence; planned files to create use `file`. Require equal real before/after check fingerprints; record `evaluated_execution_inputs`, actual source hashes, result and evidence. Observations alone prove no test execution. Completion captures post-run inputs, allowing implementation to replace pre-start absence. Exclude credentials from snapshots.

Use Python 3.12+ and the bundled `scripts/sdd_history.py` with `--project PROJECT`. For storage-backed evidence, prepare verified original bytes using the [storage contract](evidence-storage-contract.md), then pass the global `--evidence-cache PATH` before the command, as with the checker. History retains external references, compact receipts and source snapshots without copying archived bulky evidence into Git. Missing prepared originals, dependency closure or required accounting block accepted history. Migration may preserve unavailable legacy references as unverified history; they require genuine current revalidation. Storage and history preserve existing authority only.

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
- `observe-inputs --unit ID [--inventory reviewed.json]`: reads actual execution inputs, using the captured inventory when omitted. Bind matching before/after observations to the genuine check event.
- `capture-completion --unit ID --context-ref context-ref.json --run-id ACTUAL_RUN_ID [--inventory reviewed-current.json]`: validates completion and returns its immutable reference. Canonical owner updates (e.g. QA history) require fresh owner review after checks, with unchanged relevant definitions. Retain original context/post-run provenance separately; unfinished work cannot complete.
- `capture-attempt --unit ID --context-ref context-ref.json --run-id ACTUAL_RUN_ID --outcome failed|interrupted --inventory reviewed-current.json`: preserves unfinished work without passed acceptance. Add `attempt_ref` to the unchanged run; stage/activate. Status-only owner edits require fresh review, unchanged relevant acceptance/authority and original check hashes/times/outcomes.
- `observe-runtime --probes probes.json`: executes explicit identity commands once and returns an immutable receipt. The input maps identity names to argument lists starting with an absolute executable; no shell is used. Its `environment` maps each name to stripped stdout. Probe the runtime/session that will execute evidence; an installed binary version alone does not identify an attached process. Use non-secret, bounded identity commands that do not start background helpers.
- `capture-continuation --unit ID --attempt-ref attempt-ref.json --run-id NEW_RUN_ID --inventory reviewed-continuation.json`: returns candidate `manifest`, `context_ref` and `prior_attempt_ref`. Fresh inventory includes the new probe's `runtime_observation_ref`/exact `environment`. Preserve work/attempts, capture new context, reset owned checks to unrun. Save candidate, reconcile progress, stage/activate, pass `--start-unit`, record actual start. Acceptance requires subsequent executed checks.
- `--manifest candidate-manifest.json assess --completion-ref completion-ref.json --inventory reviewed.json --pending-map pending-map.json`: reviews the candidate against the actual active `forge/sdd-manifest.json`. Mapping values are current unit IDs; keys are changed pending IDs or `__added__`. Preserve every old acceptance obligation, including obligations introduced in earlier revisions.
- `stage --candidate candidate-manifest.json --expected-manifest-hash SHA256 [--pending-map pending-map.json]`, then `activate --candidate-ref candidate-ref.json --expected-manifest-hash SHA256`: validate and atomically replace the active manifest only while the expected revision and inputs still match. Mapping may come from its matching assessments; supply it explicitly for a transition without them.
- `adopt-legacy --expected-manifest-hash SHA256`: archives supported version 1 records and stages version 2 with the exact existing gate. Its `migration_ready` report means conversion only; inspect nested `project_validation`, activate and verify as above. Prior execution needs genuine revalidation; no pre-start context or old pass is reconstructed.
- `recover --journal-ref journal-ref.json`: reports whether the recorded activation happened, did not happen, or conflicts with later state. It never overwrites later work or silently removes another writer's lock.

Reference arguments name JSON files containing returned references, not history envelopes. Put the finished run and owner-reconciled results in a candidate; use `--manifest candidate-manifest.json capture-completion ...`, index its reference, then stage/activate. Completion requires complete-unit validation; never publish unvalidated completion. Save actual command outputs/checker reports.

Capture attempts before repairs when possible. Edits, deletions or new tree members
differing from test inputs retain old observations/current work as
`observation_validity: unverified_stale_inputs`. Capture validates bytes/authority,
not unavailable tested sources or results against later work. Validation treats
these checks as unrun and reports preserved failure/interruption; source manifest
and archive retain original outcomes. Changed acceptance/authority or corrupt/
missing evidence still block capture. Fresh continuations rerun required checks.

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

Keep legacy reading for import and immutable history, not ongoing version 1 execution. Live planning, start, completion, audit and release validation requires current records; old records report migration needed. Test actual frozen supported predecessor checkers rejecting the new format at those boundaries. Do not claim every historical checker supports version detection. Reject mixed versions and version-2 records disguised as version 1. Existing approval and security requirements remain enforced.

Regression tests cover repeated corrections, exact QA wording/shared definitions, missing or changed sources/evidence/runtime, invalid historical authority, partial attempts, completed-ID reassignment, obligation mappings, original order/exceptions, prototype reuse, real-consumer release acceptance, interrupted activation and concurrent changes. A separate fresh-context assistant exercise must produce actual observations, use genuine available history and disclose unavailable approval/host behavior. Record deterministic instruction loads including conditional references and retries separately from observed agent cost/time. No synthetic fixture proves product acceptance or authenticates a user event.
