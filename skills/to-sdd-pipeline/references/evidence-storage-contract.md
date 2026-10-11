# Evidence storage, version 1

Read for production/resolution/import/cleanup only. Storage preserves owners, source authority, baselines, acceptance and the separate implementation prompt. Detailed user setup is in the collection's storage guide.

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

Evidence arrays and approval/browser/visual/promotion/prompt/sequencing receipts accept references with original JSON semantics. `visual_target_ref` replaces the path; retain `visual_target_hash` for semantic approval bindings. Source-manifest/access/read refs replace path/hash pairs. `source_inventory_ref` expands `{version:1, source_hashes, consumed_source_fragments?}` into identical contained maps; inline conflicts fail. Source containment and test reuse stay strict.

## Preparation and resources

Storage performs network/cache writes: capture stable regular bytes → immutable pack → upload → independent retrieval → verify archive/original members → recoverable catalog → eligible local removal. Deduplicate content, retain logical associations, checkpoint transfers and journal deletion; reconcile unknown outcomes before retries.

Prepare active references/dependencies outside checkout; use `sdd_check.py --evidence-cache PATH`. Checker reads `objects/<sha256>` and verified `receipts/<artifact_id>.json`, checks actual bytes/size/identity/closure and original bindings, with no network or cache writes. Historical payloads load only when currently referenced. Import/archive/cache never refresh execution or grant changed-plan acceptance.

Stable project/unit IDs share aggregate reservations/charges across worktrees/workers/retries/resumes. Reserve peak capture/cache/staging/readback/restoration before writes; reconcile actual output. Dedup/deletion never refund generation. Version 1 refs require `evidence_accounting` inline/ref with `version`, `project_id`, `policy_sha256`, `runs`: unit ID, complete status, gross bytes/logical count, zero pending reservations/unreconciled outputs. Current unit refs match original run/unit IDs. Imported-existing mode charges zero new generation. Migration batches are separate. Enforce combined metadata/index/local/reserve policy; stop exhausted producers truthfully without truncating checks. External writers require registration/reconciliation; reject missing accounting.

## Retention

One coordinator mutates/prunes; incomplete shared-client knowledge forbids remote pruning. Local default: 30 days from original sealing; Drive expiry requires explicit choice. Verified durable copies permit replaceable cache eviction. Permanent expiry additionally protects current/prerequisite acceptance, required baseline, approvals/authorization, unresolved failures, explicit retention and imported recovery pending migration policy. Report expired-but-protected reasons. A sole durable local copy is not cache.

Cleanup runs at managed boundaries/explicit command: dry-run, journal, verified absence and partial failures; no default scheduler, unregistered deletion or account-wide trash. Access/import/restore never reset age. Preserve required GitHub bytes durably before 30-day expiry; local flags cannot prevent it. Upload retention and repository artifact/log settings remain separate.
