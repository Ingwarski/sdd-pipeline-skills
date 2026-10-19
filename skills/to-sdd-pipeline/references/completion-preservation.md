# Current workflow, migration and completion preservation

Use the latest tested SDD release for new and resumed projects. Version 2 is the current record format; version 1 is import-only. Migrate older records on authorized resume without a version-choice prompt, preserving work and reverifying acceptance. This adds no product approval, implementation permission, skill name or canonical SDD document.

## Boundaries and owners

Preserve completed unit IDs, obligations and original events. Reconcile pending additions, splits, merges and renumbering through the plan owner, including every requirement, check, prerequisite and consumer. Keep the numeric order contract. Same design and product scope are necessary but insufficient: changes to relevant shared requirements, implementation, tests, runtime/configuration, evidence or findings require revalidation. A new consumer can add integration obligations without changing an earlier bounded component claim.

PRD/design/architecture owners determine their meanings; DoD owns completion/rerun conditions; QA owns exact checks and shared acceptance definitions; the plan owner allocates units and reviews their relevant inputs. The authorized executor records actual starts, tests and observations. The orchestrator stages/indexes operational history and the manifest from those returns. It never invents decisions, test results or semantic equivalence. Helpers calculate/capture supplied facts; the checker remains read-only.

Project AGENTS.md continues to govern full-unit execution, six pause reasons, coordination and recovery. A history record cannot restart an ended session. Existing approved-decision documentation corrections retain their narrow [authorization exception](authorization-corrections.md); actual pending-scope or unit-boundary changes need the normal fresh current-plan prompt. Archived permission alone never authorizes a new start; unchanged current permission remains valid only within its existing scope.

## Immutable history and current acceptance

Capture the actual authorized context before execution can overwrite it. Finalize completion only from an actual completed run whose required acceptance passes. Retain original plan bindings, chronology, authorization/correction receipts, sequencing exceptions, prototype-promotion receipts, implementation/evidence identities and original QA results. Shared immutable snapshots are referenced rather than copied into every unit.

Each assessment of a revised plan points directly to the actual completed run. Do not chain assessments, rewrite old hashes/timestamps, or copy an old pass onto a changed definition. Later genuine revalidation creates a new run and retains the earlier history. Pending/running/blocked attempts cannot qualify as completed. Preserve their partial work and route resumption through current authorization and acceptance.

New acceptance requirements may require a new run of the same unit. Preserve its original scope, kind, owner and implementation paths; retain old completion references in `completion_history`, add acceptance/prerequisites without dropping existing obligations, and mark current acceptance pending. Validate the revised graph and obtain the normal current-plan authorization before starting. Reassigning a completed identity to different work remains invalid.

Archive full canonical sources for provenance. Compare the owner-reviewed relevant sections, shared definitions, exact check actions/outcomes, DoD conditions, source/test/configuration/dependency/runtime inputs and prerequisite acceptance. Review all changed canonical sources for newly introduced obligations affecting the completed claim; a matching old inventory cannot prove none exists. Include relevant plan prose as well as structured fields. Missing or ambiguous input selection cannot justify preservation.

For new plans, separate stable shared completion/evidence rules from mutable status and pending allocations into selectable headings before authorization/context capture. Review excluded sections for relevant obligations. Existing mixed sections may retain complete broader selections and incur conservative revalidation when status changes. Do not force restructuring for migration or narrow historical selections to force preservation. Reorganizing an existing authorized plan follows the normal authority or verified documentation-correction rules.

Version 2 reports plan validity, historical completion applicability and current execution permission separately. A coherent revised plan may validate while earlier acceptance requires revalidation and execution awaits a prompt. Missing or stale acceptance cannot satisfy dependent starts or release. Corrupt records, false assertions and lost obligations are errors; a structurally invalid plan is never accepted merely because history exists.

One resolved acceptance result is used for unit prerequisites, generic gates, security and release. Stored historical `passed` or `completed` labels alone never qualify. Keep actual execution results and dates visible; report when acceptance relies on an earlier run rather than implying it ran again. Recheck applicability against current sources, evidence, findings and dependencies before each dependent start/resume and at release. Full integration/release obligations remain required.

## Resume and migration

Resolve the actual installed collection and verify its provenance against published `stable`, the CI-tested release. Use the supported updater if stale; do not substitute untested `main`, overwrite local edits or claim currency without verification. Installation updates tools only: it never scans project repositories or migrates their records.

During authorized SDD resume, inspect the actual project, sources, receipts and workers. Checkpoint and stop active legacy workers before migration. Read-only requests permit inspection only. Use `adopt-legacy` for supported version 1 records; a missing unit version is supported only before any unit plan or execution. For unsupported/malformed records, archive original bytes and available evidence first, then have owners recover only source-verified metadata. Never invent missing history. Preserve code, documents, IDs and original events; never rebuild, reset or delete work merely to change formats.

A candidate report of `migration_ready` validates the exact format conversion, archive and unchanged gate, not project readiness. Nested `project_validation` may remain blocked or incomplete. Inspect the candidate, activate only with matching active/source hashes, then rerun the normal checker and reconcile affected owners. Activation preserves those diagnostics; it grants no acceptance or permission.

Migration archives actual legacy records, retains blocking findings and removes old current-acceptance claims. Keep the exact implementation gate and receipts: valid unchanged authority retains its scope; missing, stale or invalid authority remains blocked. Do not rebind a changed plan or manufacture consent. Review the current requirements/QA, capture fresh authorized context and run genuine acceptance checks in dependency order before relying on earlier work. Old passes cannot be copied forward. Missing evidence/capability remains a named blocker; fixes follow existing authorization boundaries. A newly required prompt is for missing or changed authority, never for the format upgrade itself.

Current-format projects retain immutable history and applicability checks. Reverify affected acceptance after toolchain/rule changes; do not clear sound current history on every resume. Continue only when current checks and existing permission allow it.

## Capture and correction procedure

1. Inspect current records, sources and original evidence. Perform the resume procedure above when needed. Preserve insufficient history as unverified and plan genuine revalidation; do not reconstruct consent or completion.
2. Have the concern owners review the exact acceptance input inventory and rerun conditions. Capture the authorized execution context before starting the unit. Record actual tests against their evaluated source versions; final changes invalidate affected evidence.
3. Validate the actual completed run and capture immutable completion history. Stage the manifest index, validate the complete candidate, then activate it only if the expected active revision and referenced sources still match. Serialize these operational writes. On interruption, retain the previous active manifest; incomplete staging is not completion.
4. For a plan correction, owners reconcile affected documents and pending-unit mappings. Preserve completed identity and original history. Calculate current applicability from reviewed inputs and the original run. Show specific changed/missing inputs and required checks; loss of acceptance does not itself require rebuilding code.
5. Validate the current plan separately from execution permission. Retain the existing fresh-prompt boundary outside the verified documentation-correction exception. New execution checks use the current graph/authorization; historical execution checks use the original graph/authorization and genuine original exceptions.
6. Before subsequent execution and release, recompute acceptance. Do not trust a cached assessment after any bound source, evidence, finding or runtime condition changes. Use the same result for every applicable gate.

## Worked example

Login completed under plan A with real passing checks. Profile and Notifications remain pending. The plan owner revises Profile twice and splits Notifications, retaining all obligations and mappings. Each revised-plan assessment refers directly to Login's original completion. Login remains applicable only while its relevant requirements, code, checks and evidence remain valid. Added Profile/Login integration checks belong to the new integration work. If a shared session-security requirement changes, the affected Login acceptance requires named revalidation; its original completion record remains unchanged.

The user sees: “Login remains complete. Profile and the two Notifications units remain pending. The revised plan is valid and awaits its implementation prompt.” That message must reflect actual validation, not be copied as an assumed outcome.

## Records and helper

Use both `checker_contract_version: 2` and `unit_contract_version: 2`; keep `traceability_version: 1`. Keep the existing `unit_plan`, acceptance ownership, QA definitions and actual execution records. A reference is exactly `{path, content_hash}`, with a project-relative regular file and SHA-256. The helper appends immutable records below `forge/unit-history/`; it never overwrites a completed run.

| Record | Binding and use |
| --- | --- |
| `execution_contexts[unit_id]` | Reference to `unit_execution_context`, captured before start; contains the actual authorized manifest, reviewed inventory, source snapshots and toolchain identity. |
| `unit_runs[unit_id]` after archival | `{status: "completed", completion_ref, applicability_ref?}`. Completion retains the original `run_id`, run, checks, context reference, promotion records and snapshot files. |
| `completion_history[unit_id]` | Original completion references retained when a new revalidation run replaces the active run. Archived results grant no current acceptance by themselves. |
| `completion_applicability` | Direct original `completion_ref`, current plan hash, current reviewed inventory, immediately prior active manifest reference, explicit pending-unit mapping and calculated outcome/reasons. A stored outcome is never trusted without recomputation. |
| `legacy_history` | References to actual version 1 manifest archives, labeled `unverified_not_reusable`. These preserve history and cannot satisfy a check or authorize a start. |
| Staged candidate and activation journal | Candidate manifest, expected active revision, observed inputs and validation report; journal preserves before/after manifest references for recovery. |

The inventory contains `review: {reviewer, reviewed_at, complete: true, rationale}`, non-secret `environment` identities, and `sources` covering every applicable canonical artifact. Each source selection uses `mode: "full"`, `mode: "sections"` with exact unique `headings`, or a permitted `mode: "unused"` with a reason. The helper calculates selected-byte hashes and binds current full canonical hashes. The owner must include shared definitions and new obligations; a mechanically valid selection does not establish semantic completeness.

Also supply `execution_inputs`, mapping relevant code/test/configuration/dependency paths to `{mode: "file"}`, `{mode: "tree"}` or `{mode: "absent"}`. Tree fingerprints include membership, so newly added files invalidate the old observation. Select bounded unit inputs, not the whole repository; a pending unit's unrelated files should not invalidate an earlier component. `absent` asserts absence; use `file` for a planned implementation file that will be created. Observe real input fingerprints before and after each check, require equality, and record them as that check's `evaluated_execution_inputs` alongside the actual source hashes, result and evidence. A helper observation alone never proves a test ran. Completion captures the post-run inputs; it does not expect newly implemented files to match their pre-start absence. Do not put credentials in snapshots.

Use Python 3.12+ and the bundled `scripts/sdd_history.py` with `--project PROJECT`. For storage-backed evidence, prepare verified original bytes using the [storage contract](evidence-storage-contract.md), then pass the global `--evidence-cache PATH` before the command, as with the checker. History retains external references, compact receipts and source snapshots without copying archived bulky evidence into Git. Missing prepared originals, dependency closure or required accounting block accepted history. Migration may preserve unavailable legacy references as unverified history; they require genuine current revalidation. Storage and history preserve existing authority only.

Its commands are:

- `capture-context --unit ID --inventory reviewed.json`: returns the pre-start reference; index it in `execution_contexts` before the normal checker start boundary.
- `observe-inputs --unit ID [--inventory reviewed.json]`: reads actual execution inputs, using the captured inventory when omitted. Bind matching before/after observations to the genuine check event.
- `capture-completion --unit ID --context-ref context-ref.json --run-id ACTUAL_RUN_ID [--inventory reviewed-current.json]`: validates the actual completed run and returns its immutable reference. After a canonical owner update, such as appending QA execution history, supply a fresh current owner review after the actual checks. Relevant definitions must remain unchanged. The record retains original canonical context and actual post-run provenance separately; it cannot mark unfinished work complete.
- `--manifest candidate-manifest.json assess --completion-ref completion-ref.json --inventory reviewed.json --pending-map pending-map.json`: reviews the candidate against the actual active `forge/sdd-manifest.json`. Mapping values are current unit IDs; keys are changed pending IDs or `__added__`. Preserve every old acceptance obligation, including obligations introduced in earlier revisions.
- `stage --candidate candidate-manifest.json --expected-manifest-hash SHA256 [--pending-map pending-map.json]`, then `activate --candidate-ref candidate-ref.json --expected-manifest-hash SHA256`: validate and atomically replace the active manifest only while the expected revision and inputs still match. Mapping may come from its matching assessments; supply it explicitly for a transition without them.
- `adopt-legacy --expected-manifest-hash SHA256`: archives supported version 1 records and stages version 2 with the exact existing gate. Its `migration_ready` report means conversion only; inspect nested `project_validation`, activate and verify as above. Prior execution needs genuine revalidation; no pre-start context or old pass is reconstructed.
- `recover --journal-ref journal-ref.json`: reports whether the recorded activation happened, did not happen, or conflicts with later state. It never overwrites later work or silently removes another writer's lock.

Reference arguments name JSON files containing the returned reference, not the history envelope itself. For completion, put the actual finished run and owner-reconciled results in a candidate manifest; use `--manifest candidate-manifest.json capture-completion ...`, then index the returned completion reference and stage/activate. The helper runs the complete-unit validation boundary before returning a valid completion. Never publish an unvalidated completed status. Save each actual command output and checker report.

Source documents are owner-written before candidate validation; activation makes only the manifest replacement atomic. During staging, other workers must not dispatch from an invalidated old manifest. A crashed writer's lock needs verified process ownership and explicit local recovery; incomplete directories grant no authority. Re-run validation after recovery.

## Compatibility and verification

Keep legacy reading for import and immutable history, not ongoing version 1 execution. Live planning, start, completion, audit and release validation requires current records; old records report migration needed. Test actual frozen supported predecessor checkers rejecting the new format at those boundaries. Do not claim every historical checker supports version detection. Reject mixed versions and version-2 records disguised as version 1. Existing approval and security requirements remain enforced.

Regression tests cover repeated corrections, exact QA wording/shared definitions, missing or changed sources/evidence/runtime, invalid historical authority, partial attempts, completed-ID reassignment, obligation mappings, original order/exceptions, prototype reuse, real-consumer release acceptance, interrupted activation and concurrent changes. A separate fresh-context assistant exercise must produce actual observations, use genuine available history and disclose unavailable approval/host behavior. Record deterministic instruction loads including conditional references and retries separately from observed agent cost/time. No synthetic fixture proves product acceptance or authenticates a user event.
