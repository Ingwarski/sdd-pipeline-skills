# Evidence storage, version 1

Read at authorized pipeline entry and evidence production/resolution/import/cleanup. Storage preserves owners, source authority, baselines, acceptance and the separate implementation prompt. Setup and managed recovery use the collection's storage guide.

## Pipeline entry

On authorized pipeline start/resume, including headless scopes, check storage before owner dispatch or design questions. Opening repositories and read-only/advice requests do not trigger setup.

Resolve `../../scripts/evidence_setup.py` from the real `to-sdd-pipeline` skill directory. With supported Python, run `ensure --project ACTUAL_PRODUCT_ROOT --non-interactive`; reuse configured bindings or saved defaults without another selection question. Connected Drive setup/default adoption requires a compatible authenticated host. Use bundled `scripts/evidence_host.py` help to start, service and close the session; pass `--host-session` to setup. Missing access/capability blocks setup; never select another store without permission.

If `setup_required` means no saved choice applies, ask one foreground question in `working_language`:

> Where should I save this project’s test results, screenshots and other testing files?

Offer these plain-language choices with their descriptions before the user answers:

- **On this computer (recommended)** — I’ll create a separate folder and organize the files for you. No extra account or app is needed. (If your computer is running low on storage space, Google Drive, an external drive or a shared drive may be a better choice.)
- **In a folder I choose** — Use a folder on your computer, an external drive or a shared drive.
- **Google Drive** — Use a Google Drive folder. Connect Google Drive first through **Plugins** in Codex, or **Connectors** in Claude using the same Claude account as Claude Code. I’ll check that saving and opening files works.

> You can also say **“Decide later.”**

Map these choices to managed local, selected folder/disk, and Google Drive respectively. Keep local destinations outside the project checkout. For Claude Code, verify the authenticated connector/MCP with `/mcp`; authenticated rclone remains an optional alternative. Verify original-byte upload/readback for Drive. Keep these technical checks out of the opening question; explain only relevant setup steps after selection. Remote or external storage still needs local working/cache space.

JSON or terminal output does not ask the chat question. Wait for the answer before owner dispatch; recommendations and silence are not consent. Reuse prior explicit choices. Consult `configure --help`; collect only missing destination/account and policy choices, explain defaults and require explicit Drive retention. Save confirmed choices with `configure --project ACTUAL_PRODUCT_ROOT`, then verify `configured`. Keep machine paths/credentials outside Git. Existing evidence upload/adoption requires authorization.

Preserve unavailable, malformed or mismatched saved choices; report the issue for restoration or explicit reconfiguration, never substitute a provider. `configured` confirms saved setup, not current remote reachability. Explicit postponement permits planning with setup incomplete, without evidence production. Next resolve design materials through `to-product-idea`, reusing supplied materials/answers or headless non-applicability.

## Records and references

Git retains authored sources/tests, canonical SDD, necessary approved inputs, compact current results, approvals/authorization and references. Store generated captures/recordings, bulk logs/results/indexes and superseded history externally. Classify contents before ignoring registered generated locations: never blanket-ignore `forge/` or `output/`; ignoring does not remove tracked blobs. QA owns meaning/interpretation, executors observations, storage persistence, orchestrator the manifest.

Legacy contained `{path, content_hash, kind}` remains valid. Direct reference or `{kind, evidence_ref: reference}`:

```json
{
  "version": 1,
  "artifact_id": "stable-logical-id",
  "sha256": "original-byte-sha256",
  "size": 42,
  "kind": "integration",
  "schema": "evidence-bytes-v1",
  "provenance": {"executor": "actual-executor", "executed_at": "original-time", "run_id": "RUN-1", "unit_id": "UNIT-1"},
  "bindings": {"check_id": "QA-1", "evaluated_plan_hash": "original-plan-hash"},
  "locator": {"store_id": "stable-store-id", "provider": "local", "object_id": "immutable-object-id", "pack_sha256": "archive-hash", "pack_size": 128, "member": "content/original-byte-sha256"},
  "retention": {"sealed_at": "original-sealing-time", "class": "current_acceptance"}
}
```

Placeholders are not evidence. Preserve applicable source/plan/baseline/environment/toolchain/execution bindings and imported original path/times. Schemas: `evidence-bytes-v1`, `evidence-json-v1`, `source-inventory-v1`, `environment-v1`, `sdd-receipt-v1`, `sdd-result-v1`, `archive-attachment-v1`. `dependencies` supplies closure; split imports need contiguous offset/length/hash segments and original whole-file hash/size. URLs alone prove nothing; unsupported/incomplete/mismatched records block claims.

Evidence arrays and approval/browser/visual/promotion/prompt/sequencing receipts accept original-JSON references. `visual_target_ref` replaces paths; retain `visual_target_hash` approval bindings. Source-manifest/access/read refs replace path/hash pairs. `source_inventory_ref` expands `{version:1, source_hashes, consumed_source_fragments?}` into identical contained maps; reject inline conflicts. Preserve containment/test reuse.

Structured `interactions_checked` separates `action_name`, `observed_state_id`, `fixture_id`, `observed_result` and original `observed_at`. Optional `observation_source_index` selects an existing `original_observation_refs` entry; `observation_pointer` selects its JSON object. Compare available structured state/fixture/result/time fields; action tags, expectations and DOM prose cannot establish observed state. Legacy receipts remain valid. Structural agreement authenticates neither observations nor coverage.

Label corrections require a separate version-1 `observation_metadata_correction`: unchanged hash-bound `original_receipt`, original `observed_at`, named `reviewer`/`reason`, separate `corrected_at`, `new_execution: false`. `corrections` targets original `interaction_index` values/times; only label/source-pointer fields above may change. Reference the original, never another correction; preserve originals/history and other-state evidence. Checker validates declared agreement; owner reviews semantic accuracy. This creates no capture, authority or acceptance.

## Preparation and resources

For browser producers, use the optional [browser evidence workflow](browser-evidence-workflow.md) for absolute producer paths, runtime/profile separation, actual prerequisites, settlement and exact owned cleanup. It adds no browser requirement to other product scopes.

Storage performs network/cache writes: capture stable regular bytes → immutable pack → upload → independent retrieval → verify archive/original members → recoverable catalog → eligible local removal. Deduplicate content, retain logical associations, checkpoint transfers and journal deletion; reconcile unknown outcomes before retries.

Prepare active references/dependencies outside checkout; use `sdd_check.py --evidence-cache PATH`. Checker reads `objects/<sha256>` and verified `receipts/<artifact_id>.json`, checks actual bytes/size/identity/closure and original bindings, with no network or cache writes. Historical payloads load only when currently referenced. Import/archive/cache never refresh execution or grant changed-plan acceptance.

Stable project/unit IDs share aggregate reservations/charges across worktrees/workers/retries/resumes. Reserve peak capture/cache/staging/readback/restoration before writes; reconcile actual output. Dedup/deletion never refund generation. Version 1 refs require `evidence_accounting` inline/ref with `version`, `project_id`, `policy_sha256`, `runs`: unit ID, complete status, gross bytes/logical count, zero pending reservations/unreconciled outputs. Current unit refs match original run/unit IDs. Imported-existing mode charges zero new generation. Migration batches are separate. Enforce combined metadata/index/local/reserve policy; stop exhausted producers truthfully without truncating checks. External writers require registration/reconciliation; reject missing accounting.

For unknown producer history, read [producer-gap recovery](producer-gap-recovery.md) before quarantine or version 2 scoped accounting. Preserve failed runs, known charges, full pending holds and historical incompleteness. Only independently complete current runs may support required evidence; version 1 incomplete receipts still fail.

## Retention

One coordinator mutates/prunes; incomplete shared-client knowledge forbids remote pruning. Local default: 30 days after original sealing; Drive expiry requires explicit choice. Evict replaceable cache only with verified durable copies. Permanent expiry protects current/prerequisite acceptance, required baseline, approvals/authorization, unresolved failures, explicit retention and imported recovery pending migration policy. Report expired-but-protected reasons. Sole durable local copies are not cache.

Cleanup runs at managed boundaries/explicit command: dry-run, journal, verified absence and partial failures; no default scheduler, unregistered deletion or account-wide trash. Access/import/restore never reset age. Preserve required GitHub bytes durably before 30-day expiry; local flags cannot prevent it. Upload retention and repository artifact/log settings remain separate.
