# Evidence storage

Choose where generated evidence lives before producing it. Canonical SDD, compact current results, approvals/authorization receipts and references remain in Git; large captures, detailed results and superseded history use a durable store. The store differs from disposable capture/cache/staging/readback/restoration space, even when both are on the same disk.

## Select and save a destination

From the durable SDD clone, with supported Python 3.12+:

```bash
python3 scripts/evidence_setup.py wizard --project /path/to/product
python3 scripts/evidence_setup.py status --project /path/to/product
```

Use `python` on Windows when it is the detected supported executable. When a new choice or explicit reconfiguration is needed, an agent's storage-choice popup/dialog must include the following prerequisites **in the option descriptions before the user answers**. A separate notice or README link is insufficient; reuse saved choices without repeating the question. The wizard offers:

| Choice | Durable destination | Requirements |
|---|---|---|
| Managed local | Outside the checkout in the configured evidence home | Python standard library; no Drive plugin/connector, rclone or cloud account |
| Folder/disk/mount | An explicitly selected available folder outside the checkout | Writable destination and sufficient measured working space; no Drive plugin/connector or rclone |
| Google Drive | Explicit selected Drive destination/account | Connected: first install/connect Google Drive in Codex Plugins, or authenticate the Drive connector/MCP in Claude's Customize → Connectors, use the same Claude account in Code and verify `/mcp`. A qualified host bridge and independent upload/readback probe are required. Authenticated rclone is an optional alternative. |

The wizard reviews combined local space, run/unit/project byte/file limits, retained content/object limits, metadata budget, retention and optional archive adoption. Changing a folder on the same disk reduces Git clutter but does not free disk space. A mounted destination being unavailable is a storage failure; the tool never silently changes providers.

`SDD_EVIDENCE_HOME` overrides the external machine configuration/state root, otherwise `~/.sdd-pipeline/evidence`. Machine paths and transport configuration stay outside Git. Portable `forge/evidence-policy.json` holds version 1 policy, stable project/store IDs, limits and retention. Preserve that policy across worktrees. Saved choices avoid repeated questions; changing them requires explicit reconfiguration:

```bash
python3 scripts/evidence_setup.py wizard --project /path/to/product --reconfigure
```

A noninteractive local selection can be explicit:

```bash
python3 scripts/evidence_setup.py configure --project /path/to/product --provider local
python3 scripts/evidence_setup.py configure --project /path/to/product --provider folder --destination /mounted/evidence --reconfigure
```

Installation/update checks setup after validating links. A fully current installation still detects missing setup. First managed use after a plain Git pull runs `ensure --project PATH`; a saved default is reused. Noninteractive missing setup returns `setup_required` and a concrete command. Merely opening a repository never selects cloud accounts, uploads existing evidence or purges it. An explicit selected policy authorizes routine operations within its bounds, including its synthetic probe.

## Google Drive

Drive setup succeeds only when synthetic original bytes are uploaded and independently downloaded and verified. Sync-folder writes and upload responses are insufficient. If the host cannot provide original-byte download, metadata/lookup, stable object identity, bounded transfer and recovery capabilities, setup reports the exact missing capabilities without fallback.

Connected hosts expose a callable bridge or a machine-local JSON command bridge. Pass its command through `--bridge-command` as a JSON argument array (recommended for Windows portability), for example `'["python3", "/outside/bridge.py"]'`; do not put account tokens or credential arguments in that command or portable project records. The bridge runs the connected tools and returns exact original bytes through bounded file transfer. [Protocol and supported standalone transport](drive-transport.md).

Standalone hosts may use optional rclone. Authenticate with `rclone config`, selecting Google Drive and the intended account. As of the reviewed rclone documentation on 2026-10-11, **your own Google OAuth client ID is required**; create it using rclone's official instructions. Finish the browser consent yourself, or use the documented remote/headless authentication flow. Store the rclone configuration outside Git. The toolkit does not install rclone or choose accounts automatically. [Official Google Drive authentication](https://rclone.org/drive/#making-your-own-client-id).

After authentication, select a destination and explicitly choose Drive archive retention:

```bash
python3 scripts/evidence_setup.py configure --project /path/to/product --provider google-drive --transport rclone --destination evidence:synthetic-project --rclone-config /private/config/rclone.conf --drive-retention-days never
```

`never` is an explicit policy choice, not an implicit default; a positive day count is also supported. The operation probes only its synthetic test object and cleans its own resources. Missing credentials, expired authorization, unavailable storage, corrupt readback or incomplete capabilities fail setup. Credential values never belong in logs, manifests, fixtures or Git.

Transfers use immutable archive-pack identities and external recoverable journals. After an unknown upload outcome, look up and verify the deterministic object before retrying; do not blindly duplicate uploads. A connector that cannot resume one upload resumes at verified pack boundaries. Real Drive verification must be reported separately from synthetic/mock transport tests.

## Capture, archive and validate

The focused manager is `skills/to-sdd-pipeline/scripts/evidence_store.py`. Run its `--help` and command-specific help from the installed real skill directory. Use absolute real paths for external inputs/outputs; resolve operating-system aliases first (on macOS, `/var` commonly resolves to `/private/var`). The tool rejects linked parents instead of silently traversing them. Its operations are `setup-probe`, `run`, `archive`, `prepare`, `restore`/`recover`, `import`/`adopt`, `accounting-receipt`, `cleanup`, `reconcile`, `retention-policy`, `status` and `git-review`. For a configured project:

```bash
python3 skills/to-sdd-pipeline/scripts/evidence_store.py archive --project /path/to/product --spec /external/capture-spec.json --output /external/evidence-refs.json
python3 skills/to-sdd-pipeline/scripts/evidence_store.py prepare --project /path/to/product --refs /external/active-refs.json
python3 skills/to-sdd-pipeline/scripts/evidence_store.py restore --project /path/to/product --refs /external/active-refs.json --destination /external/restored
python3 skills/to-sdd-pipeline/scripts/evidence_store.py accounting-receipt --project /path/to/product --output /external/accounting.json
python3 skills/to-sdd-pipeline/scripts/evidence_store.py git-review --project /path/to/product --base origin/main --head HEAD
```

The archive spec is `{version:1, files:[...]}`. When archiving output already settled by the managed `run` command, copy the returned `output_id` into the spec's `managed_output_id` so the manager verifies that observation binding and avoids charging the same original generation twice. Each file carries its actual path, original timezone-aware `sealed_at`, `provenance` with stable `run_id`/`unit_id` and actual executor/time, relevant `bindings`, `kind`, `schema`, `retention_class` and any `protections`/`dependencies`. Managed captures derive portable original paths relative to their registered output root. For unmanaged nested captures or duplicate basenames, supply explicit distinct relative `original_path` values or distinguishing check provenance; ambiguous collisions fail rather than overwrite logical associations. Absolute machine paths belong in external capture journals. The manager computes original hashes/sizes. Reuse the exact spec to resume an interrupted operation; its checkpoint preserves completed packs. `--remove-local` requests eligible removal only after verification and deletion journaling. `--migration` is for existing evidence, never a way to avoid charges for new tests.

The lifecycle is stable capture → immutable pack → upload → independent original-byte retrieval → archive/member verification → recoverable catalog → eligible local-copy removal. Regular-file hashes stream; links, unsafe members, duplicates, changed inputs, invalid lengths/hashes and excessive decompression fail. Verified archive extraction supports ZIP, tar, tar.gz and tar.bz2. Archive metadata defaults to 16 MiB and encoded archives to declared maximum original bytes plus 16 MiB; header counts/chains and compressed tails are bounded before extraction. XZ adoption fails explicitly with `requires bounded repack before adoption` because its decoder dictionary can allocate unbounded memory. An opaque XZ attachment can be stored as original bytes, but its members cannot be asserted verified by this resolver. Deduplication stores identical content once while retaining every logical check/run/path association. Catalog roots and immutable index segments share one aggregate metadata budget.

The `run` wrapper reserves before launching an authorized producer, sets `SDD_EVIDENCE_OUTPUT_DIR`, captures a complete process log, monitors registered output and stops its own process group on budget exhaustion or timeout. Create the chosen capture directory first and keep it empty; `run` registers only an existing empty regular directory. For an existing authorized capture script:

```bash
python3 skills/to-sdd-pipeline/scripts/evidence_store.py run --project /path/to/product --run-id RUN-1 --unit-id UNIT-1 --output-dir /external/capture --reserve-bytes 8388608 --reserve-files 20 --timeout 300 -- python3 /path/to/authorized-capture.py
```

Use measured allowances for the real check; this example reserves 8 MiB/20 files. The wrapper is not an OS sandbox: writes outside its registered folder and rapid unobserved rewrites can bypass monitoring. It preserves partial output and marks incomplete instead of truncating required diagnostics. Before managed generation, reserve peak bytes and logical file counts using stable project/run/unit IDs. Workers share reservations and one coordinator mutates/prunes the catalog. Register output locations and reconcile actual artifacts before recording completion. Managed tooling can stop its own producers; unrestricted external writers can bypass physical enforcement. Missing accounting blocks completion rather than pretending a post-run inventory prevents every write.

Prepare active references and their dependencies into an external bounded cache before invoking the checker. Preparation atomically reserves the whole shared pack: encoded archive, every declared extracted member, reassembled original and receipt metadata. A small selected member does not justify reserving only its own bytes. Within a preparation operation, a verified shared pack is reused through one bounded staging area; each referenced member is freshly hash-checked. Receipts record only required member closure, avoiding a full pack-member list copied into every artifact receipt. Metadata, cache, staging and producers share outstanding holds; external restored copies remain registered and charged after copying:

```bash
python3 skills/to-sdd-pipeline/scripts/sdd_check.py --project /path/to/product --evidence-cache /external/prepared-cache --before implementation
```

The checker performs no network or cache writes. It verifies actual original bytes, hashes, sizes, stable identities, closure and unchanged source/plan/baseline/environment/toolchain/execution bindings. Source paths stay contained inside the consuming project. Optional shared source inventories expand the same hash maps and fragments, rejecting conflicts. Current-state checks need not load every superseded historical payload.

To avoid repeating evaluated source maps in each capture, use a shared `source-inventory-v1` reference whose original JSON is `{version:1, source_hashes:{...}}`. Set the current check's `source_inventory_ref`, bind each capture to that inventory's original byte hash, and include the inventory in the capture's verified dependency closure. Given the real reference returned by archiving that inventory:

```python
check["source_inventory_ref"] = inventory_ref
capture_entry.setdefault("bindings", {})["evaluated_source_inventory_sha256"] = inventory_ref["sha256"]
capture_entry.setdefault("dependencies", []).append(inventory_ref)
```

`Checker.check_bindings(check)` proposes the compact hash binding for a shared inventory. Existing full `evaluated_source_hashes` bindings remain valid when they exactly match the expanded map; if both forms are supplied, both must match. A compact binding requires its own verified inventory dependency, including through another receipt. Declaring or caching an unrelated inventory is insufficient. Required live source paths, original execution time, plan, baseline and other bindings still apply; storage never refreshes an observation.

New storage references require `evidence_accounting` bound to the portable policy/project and original run/unit IDs. Storage-managed `unit_runs` records also include their stable `run_id`; it must match the complete accounting run and evidence provenance. A complete receipt records gross generated bytes, original logical count, zero pending reservations and zero unreconciled outputs; otherwise completion is blocked. Existing-data import uses explicit `imported-existing` accounting with zero new generation while retaining historical run identity. Missing/corrupt active evidence blocks the claim. Cache, archive verification, import and restoration preserve original execution times and never count as reruns or changed-plan passes. [Versioned reference and owner contract](../skills/to-sdd-pipeline/references/evidence-storage-contract.md).

## Defaults and sizing

All values are concrete configurable version 1 policy in [defaults.json](../skills/to-sdd-pipeline/scripts/evidence/defaults.json). MiB/GiB use powers of 1024. Use `configure --limit KEY=INTEGER` repeatedly to override named limits; the wizard exposes the principal allowances. Values must pass policy validation; changing limits must not erase existing charges or obligations. If lowering combined local allowance below the cache allowance, lower `cache_stop_bytes` accordingly; the cache always fits inside local space.

| Scope | Warning | Enforced stop / purpose |
|---|---:|---|
| Gross generation per run | 250 MiB | 500 MiB and 10,000 logical files |
| Cumulative unit generation | 1 GiB | 2 GiB, 50,000 logical files, four retries |
| Cumulative project generation | 10 GiB | 20 GiB and 500,000 logical files across sessions/worktrees |
| Retained unique content | 5 GiB | 10 GiB and 100,000 physical objects per project |
| Combined metadata/history/index | — | 128 MiB and 10,000 metadata files/objects; splitting indexes cannot bypass it |
| Combined local working space | — | 2 GiB covering capture, cache, staging, readback and restoration |
| Cache within local allowance | — | 512 MiB; never an additional 512 MiB allowance |
| Preserved free-space reserve | — | 256 MiB default; honor the already selected project floor |
| Existing-data migration batch | — | 500 MiB and 10,000 logical files, with 1 GiB local staging allowance |
| Immutable archive pack | 64 MiB target | 128 MiB maximum; total migration volume is not capped by pack size |

A run allowance accommodates deliberately selected screenshots and diagnostics; the unit/project counters prevent retry/session/split-file bypass. Retained limits bound original unique content; pack aggregation reduces remote object overhead. Combined metadata counts catalog, history, indexes and accounting instead of granting each file its own allowance. Local budgets include outstanding concurrent reservations and measured restoration peak, preserving free space without a universal 10 GiB prerequisite. Separate migration accounting permits bounded evacuation of an already over-budget collection without charging old bytes as new tests. The 500 MiB/10,000-file migration allowance applies to the complete submitted spec and is enforced independently of pack sizing. For a larger original or batch, explicitly raise `migration_batch_stop_bytes` and, where required, `migration_local_stop_bytes` to cover measured original/capture/readback/restoration peak plus the preserved reserve. Pack size still bounds each transfer, rather than capping total migration volume. Do not split logical originals to evade aggregate charges.

Synthetic starter-profile workloads accept 40 MiB across 200 captures, warn at 300 MiB across 60 diagnostics, then reject a further 201 MiB in that same run. A controlled two-worker reservation test accepts exactly one 6-byte reservation under a shared 10-byte unit allowance; bounded migration batches retain separate charges. These are deterministic accounting tests, not product-performance guarantees. Further regressions cover repeated charges, split/many-small-file cases and reservations. Actual workload validation and full-suite measurements are recorded in [maintenance](maintenance.md); tune a source-backed policy when required coverage needs more space. Required evidence is never truncated, split to evade a limit, omitted or relabeled passed to fit a budget.

| Review or compactness target | Value | Meaning |
|---|---:|---|
| Changed/new Git blob | 1 MiB | Review threshold, not automatic rejection of legitimate source |
| Newly introduced Git data in proposed PR range | 50 MiB | Entire range, including files added then deleted; counts unique newly introduced blobs |
| Current manifest | 1 MiB | Compactness target together with combined metadata budget |
| Compact result | 256 KiB | Compactness target; preserve full required observations through references |
| Structured capture | 1 MiB | Format-specific compactness target |
| Scenario JSON | 10 MiB | Format-specific compactness target |

Unpublished remote objects consume physical-object allowance and are charged conservatively by encoded byte size until reconciled; reported verified unique-original bytes remain distinct from that unknown occupancy. Unknown packs never expire automatically. Gross generation and logical counts survive cleanup and deduplication. Retained occupancy can decrease only through reconciled deletion. Renaming scripts, new run directories or another chat cannot reset project/unit accounting. Exhaustion records truthful incomplete state and the responsible producer stops. A client without complete shared-client knowledge cannot prune remote evidence.

## Retention and cleanup

Default **local generated-artifact retention is 30 days**, measured from original run completion/sealing: day 29 is ineligible; day 30 is eligible. Copy, access, download and import do not refresh age. Managed-operation boundaries verify durable bytes before removing eligible registered originals or replaceable cache; permanent expiry remains explicit and requires complete claims. Eligibility is also evaluated by explicit cleanup, not by a default scheduler; no tool running means deletion is not guaranteed at an exact time.

Cache eviction removes replaceable local bytes after verified durable storage. Permanent expiry removes obsolete evidence only under selected retention policy and reference/protection checks. A selected local folder can contain the only durable copy and is not disposable cache. Unavailable remote storage prevents pretending a disposable copy has verified durable coverage.

Protect current/prerequisite acceptance, required approved-baseline material, approvals/authorization, unresolved failure evidence, explicitly retained material, and imported recovery collections until an explicit migration retention decision. Report expired-but-protected items with their reason. Routine obsolete diagnostics do not become permanent merely because they belong to a run.

Cleanup defaults to dry-run. Cache cleanup and permanent expiry are explicit separate modes:

```bash
python3 skills/to-sdd-pipeline/scripts/evidence_store.py cleanup --project /path/to/product
python3 skills/to-sdd-pipeline/scripts/evidence_store.py cleanup --project /path/to/product --apply
python3 skills/to-sdd-pipeline/scripts/evidence_store.py cleanup --project /path/to/product --expire --claims /external/current-claims.json
python3 skills/to-sdd-pipeline/scripts/evidence_store.py cleanup --project /path/to/product --expire --claims /external/current-claims.json --apply
```

Permanent expiry requires a complete current claim snapshot `{version:1, project_id:..., complete:true, evidence_refs:[artifact IDs]}` from the coordinator. Include current/prerequisite/baseline references and explicit protections; an incomplete snapshot cannot authorize pruning. Cleanup journals intent, reconciles interruption, checks actual absence and reports partial failures. Inspect pending registered deletion intents, then resume them explicitly:

```bash
python3 skills/to-sdd-pipeline/scripts/evidence_store.py reconcile --project /path/to/product
python3 skills/to-sdd-pipeline/scripts/evidence_store.py reconcile --project /path/to/product --apply
```

`reconcile` defaults to dry-run. It resumes only individually recorded archive/pruning deletion intents. Archive-copy removal revalidates durable evidence; pruning resumes catalogued retirement under its coordinator checks. It does not discover arbitrary disposable paths or waive changed-byte/ownership protections. It also reconciles a stale catalog lock only after verifying that its recorded process has exited on the same host and belongs to this coordinator. Live, foreign-host, unknown-owner or otherwise unverifiable locks remain intact with a precise limitation; no unrelated process is stopped. Explicit reconciliation may release a dead local working reservation only after charging actual staged usage, without deleting those files. Dead-owner cloud reservations remain held when transfer-helper exit is unknown; inspect/recover the named helper operation before release. An exited coordinator alone does not prove a cloud transfer ended. It targets registered verified objects/paths only, never account-wide trash or broad unregistered files. Temporary task-owned browser contexts/processes/profiles also require the applicable AGENTS.md cleanup; preserve other tasks' profiles and deliverable captures.

GitHub Actions artifacts and logs default to **30 days** separately. Relevant uploads use `retention-days: 30`; no upload is added solely to demonstrate retention. Repository artifact/log retention uses the repository Actions setting or the applicable REST endpoint `GET`/`PUT /repos/{owner}/{repo}/actions/permissions/artifact-and-log-retention` with `days: 30`. Verify the returned setting; report exact permission or organization-policy limits and remaining action. Workflow YAML does not configure log retention. Preserve required artifacts in the selected durable store before GitHub expiry; local flags cannot stop GitHub deleting them. [Official retention guidance](https://docs.github.com/en/actions/tutorials/store-and-share-data).

Drive retention is explicit during setup and never inherits local cache expiry. Imported collections remain protected until the user explicitly accepts their migration retention policy. Review/select the applicable local or Drive retention days first, then acknowledge individual imported artifact IDs:

```bash
python3 skills/to-sdd-pipeline/scripts/evidence_store.py retention-policy --project /path/to/product --artifact imported-report-1
```

Repeat `--artifact` for each chosen imported record. This command records an administrative catalog decision to use the selected portable policy and releases only the pending-import protection. The decision remains separate from immutable evidence references: original sealing times, provenance, bindings and payloads stay intact, with no new execution or refreshed verification time. Legacy Boolean retention flags remain compatibility metadata and cannot authorize pruning. The command uploads no payload and does not immediately delete content. Current claims, dependencies and other protections still prevent permanent expiry; actual expiry requires the explicit cleanup mode with a complete claim snapshot.

## Adopt existing archives and recover

Prepare a project-provided neutral declarative mapping of existing stable object IDs, archive hash/size, member identities and provenance. Import accepts whole-file members or ordered split segments with offsets/lengths/hashes plus original whole-file size/hash. Original catalogs remain preserved; payloads are registered without modification or reupload. Accepted root layouts are `version:1` plus `objects`/`files` with `parts`, or already normalized `refs`/`packs`. Optional `active_artifact_ids` lists the imported records that currently support claims and must be independently verified during adoption. Omission defaults to every imported reference; an explicit subset avoids retrieving superseded payloads while preserving their catalogs/references. A historical index alone remains unverified payload evidence, and incomplete current-claim selection must never justify acceptance or expiry. A minimal object-table mapping looks like this; replace illustrative paths/identities, sizes, hashes and times with values from the original catalog:

```json
{
  "version": 1,
  "objects": {
    "archive-a": {
      "sha256": "ARCHIVE_SHA256",
      "size": 1234,
      "locator": {"object_id": "existing-stable-object-id", "key": "existing/archive.zip", "size": 1234},
      "members": [{"member": "old/report.json", "sha256": "ORIGINAL_SHA256", "size": 42}]
    }
  },
  "files": [{
    "artifact_id": "imported-report-1",
    "sha256": "ORIGINAL_SHA256",
    "size": 42,
    "kind": "recovery-attachment",
    "schema": "archive-attachment-v1",
    "original_path": "old/report.json",
    "provenance": {"run_id": "ORIGINAL_RUN_ID", "unit_id": "ORIGINAL_UNIT_ID"},
    "bindings": {},
    "retention": {"class": "recovery", "sealed_at": "ORIGINAL_TIME_WITH_TIMEZONE"},
    "parts": [{"object": "archive-a", "member": "old/report.json", "offset": 0, "length": 42}]
  }]
}
```

Historical packs must fit explicitly measured decompression bounds: their complete original-member byte total is checked against `archive_pack_stop_bytes`, and member count against `migration_batch_stop_files`. Packs above the default 128 MiB original-byte bound or 10,000 members require justified `configure --limit` overrides plus local/cache capacity for the full encoded pack, every extracted member and selected reassembled originals. These overrides do not waive content verification or reset generation accounting; keep archive and migration aggregate limits distinct. Actual SHA-256 values must be 64 lowercase hexadecimal characters. For split files, add ordered parts covering every contiguous whole-file offset, each referencing its archive/member and exact length; member hashes validate parts while the file hash validates reconstruction. Optional `verified_at` preserves an original historical verification timestamp. Import does not accept a timestamp as payload proof. Alternative layouts require explicit mappings rather than private recovery scripts or guessed filenames.

Import and cold recovery use the same resolver:

```bash
python3 skills/to-sdd-pipeline/scripts/evidence_store.py import --project /path/to/product --mapping /external/import-mapping.json --output /external/imported-refs.json
python3 skills/to-sdd-pipeline/scripts/evidence_store.py prepare --project /path/to/product --refs /external/imported-refs.json
python3 skills/to-sdd-pipeline/scripts/evidence_store.py recover --config /private/storage-binding.json --project-id PROJECT_UUID --destination /external/recovery
```

Cold recovery needs stable project/store identity and the authenticated storage binding, without the original checkout or local database. New remote catalogs retain the original portable policy; recovery adopts and validates it before applying resource bounds instead of substituting default limits. Legacy catalogs without that policy require an explicitly supplied `--policy /external/original-policy.json`; missing policy is a clear recovery limitation. An imported index alone does not prove payload integrity. Independently retrieve/verify active referenced bytes through the resolver before relying on them. Retain old verification timestamps as historical provenance; import never invents executions. Treat an existing Git recovery bundle as an opaque attachment with its restoration metadata, not as authority for general disk/Git backup behavior.

Recover using the durable remote catalog and credentials even when the checkout/local database is absent. Restore only verified safe members within bounded local reservations. Original paths describe provenance, never permission to extract arbitrary destinations. Repeated remote transfers reconcile existing immutable IDs instead of blindly uploading again.

Moving tracked product evidence and cleaning old Git history are separate consuming-project migrations. Classify actual files before changing ignore rules; never blanket-ignore `forge/` or `output/`, which may contain canonical records, approved inputs, authored fixtures or required references. This feature does not require another product's migration to release.
