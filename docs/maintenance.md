# Reliability, Audit Remediation and Maintenance

The September 2026 audit remediation builds on the earlier seven-point update. The 13 names, document owners, Jobs To Be Done, use cases, H1–H10, error recovery and approved-design model remain intact. Private next-version planning is not part of this release.

## What changed

1. **Trustworthy release records (F1, F4).** Gate/check membership works both ways. Excluded checks cannot cover required clauses or applicable heuristics. Promotion receipts verify actual Git ancestry, scoped patches, source/destination bytes and evidence—not just filenames.
2. **Frozen design inputs (F2).** Shared CSS, fonts, scripts and other rendering inputs join the baseline hash. Static dependency checks supplement actual browser/network inspection; they do not prove dynamic completeness.
3. **Proportional scope (F3, F9).** Confirmed headless projects skip UI documents/approval; existing changes reuse valid artifacts and reconcile affected owners. Full UI projects retain three candidates. Bounded early exploration remains non-production.
4. **Typed traceability (F5).** Existing owner documents define job, use-case, requirement/clause, surface/state, QA and unit IDs. A compact index checks types, references and stage-appropriate coverage; later mappings are not earlier dependencies.
5. **Clear design and portable execution (F7–F8).** Separate neutral behavioral research from operator decisions; apply measurable accessibility before house-style defaults. Direct hosts can run owners inline, persist intake, reject stale returns and honor an explicitly selected visible browser.
6. **Lifecycle and behavior evaluation (F10–F11).** Existing owners cover applicable delivery, rollback/restore, operations, maintenance, performance/cost and outcome measurement. Raw agent-evaluation scenarios and an evidence rubric are provided; cases start **not run**, separate from deterministic tests.
7. **Supported installation (F6, F12).** Maintained Python boundaries, exact installed-target/resource checks, old-clone bootstrap, no-op ordering and a CI-tested `stable` channel. Agents resolve declared legacy names before checking availability; a known rename needs no extra approval. Scoped retirement and unrelated-work protections remain unchanged.
8. **Measured instruction costs (F13).** Shared rules are shorter; unchanged rules/sources are reused when available. `--snapshot NODE` proposes hashes without claiming validation. Recent-version growth and absolute ceilings now prevent regressions hidden by an older benchmark.

SDD still determines what to build; QA verifies it. A validated plan still ends at `awaiting-implementation-prompt` until a later explicit user request authorizes production implementation.

## Sequential unit acceptance

The [unit execution contract](../skills/to-sdd-pipeline/references/unit-execution-contract.md) adds independently completable units without changing artifact owners, names, source authority or approval boundaries. Construction dependencies and acceptance prerequisites form one execution graph; check prerequisites also have their own acyclic graph. Forward prerequisites block a strict sequential plan. Source-backed splits/merges/reordering must retain every obligation and check, with required real-consumer integration acceptance owned by appropriately sequenced units.

The checker validates canonical plan/QA projections, complete ownership and traceability, actual run bindings, fresh evidence and scoped user sequencing exceptions. `--start-unit ID` checks authorization and predecessor completion; `--complete-unit ID` checks all required acceptance and blocking findings. Recorded completion is revalidated on later checks. Release additionally requires all units and existing release gates. A component contribution is not a full requirement pass.

Legacy plans require owner-reviewed `unit_contract_version: 1` records; missing records cannot pass plan completion, implementation or release validation. Preserve valid documents/IDs/history and reconcile affected architecture, DoD, QA and plan allocations. Changed plans invalidate old implementation authorization and require a fresh prompt after the plan pause. Neither record migration nor a sequencing exception waives acceptance.

No production execution runner is present here. The host must enforce start/completion exit codes and continue/resume the active unit until validated completion or a genuine blocker/input boundary. Tests exercise declared records, not the authenticity of user events, completeness of source inventories or host turn continuation.

The 2026-10-02 full-skillset review found that continuation was stated at the host boundary but not explicitly required in generated plan prose. The plan owner now embeds the mandatory full-unit execution rule in `docs/development-plan.md`; the orchestrator returns plans missing it to that owner. It forbids routine partial handoffs, requires safe investigation/fixes before declaring a blocker, and specifies pause/resume reporting. User stop/change and authorization boundaries still take precedence. Existing product plans are not silently rewritten; reconcile them through their owner and preserve the fresh-prompt requirement when plan bytes change. No new skill, approval, runtime record or checker schema is added.

`tests/test_unit_execution.py` uses isolated synthetic fixtures for the earlier-unit/later-acceptance conflicts, mixed dependency cycles, ownership, stale/failed/deferred evidence, blockers, exceptions, migration, localization and valid component-to-integration sequencing. The Windows updater test's Git delegate preserves native exit codes in the caller scope; a module closure previously masked nonzero ancestry results after the installer set a local exit code. Production updater code is unchanged.

Full-unit regressions additionally cover resuming saved partial progress without advancement, blocked runs with passing checks, and one passed check not completing a multi-check unit. That clarification passed 172 local Python 3.12 tests with no skips, plus Unix installer, retirement and updater suites. These are record/transition tests, not an independent agent-continuation evaluation.

### Numeric-order correction — 2026-10-02

The earlier graph validator accepted a list ordered 09 → 08 when its edges matched that list. It now requires one numbered-ID namespace, unique integer suffixes and increasing numeric execution order, in addition to the existing combined-graph checks. Thus lower-numbered units cannot depend on higher-numbered units through construction, acceptance or prerequisite-check owners. Zero, gaps and padding remain valid; labels like 08a and duplicate numeric aliases do not. This strengthens version 1 validation without adding a competing schema; invalid legacy plans return to their owner for reconciliation.

The plan owner walks through complete acceptance with all later units absent, records source-backed dependency reasons, resolves cycles and only then numbers units. QA owns precise test/fixture/consumer scope; the plan owner owns allocation; the orchestrator rejects missing walkthroughs and failed checker results. Broad system checks remain required under integration owners, not copied into every early component check. Existing plans retain old IDs/results/receipts in history with an explicit old-to-new mapping when renumbering is necessary; no historical completion or authorization is rebound.

CLI reports now fingerprint actual checker and skillset bytes, including local edits and excluding generated Python/Finder caches. Preserve reports, rerun after toolchain changes and freeze sources for evaluations. These fingerprints identify the source version without Git but do not prove that the agent disclosed every semantic dependency. The new `numbered-unit-planning` scenario tests that reasoning separately from graph regressions. Product plans are not automatically migrated by a skills update.

Verification: 182 local Python 3.12 tests passed without skips, all 13 skills validated, and isolated Unix installer/retirement/updater suites passed. A fresh-agent standalone planning smoke test on frozen synthetic sources produced five increasing-number units and preserved all six required checks, with full release/security acceptance last and no higher-numbered prerequisites. Seven input files remained unchanged; no product code or manifest was written. The author reviewed the result and checked its graph/source hashes; this is not an independent reviewer score, full-pipeline evaluation or product acceptance. The later provenance-helper scoping refinement changed no tested authoring instructions. Evaluation artifacts remain outside Git.

## OWASP security integration

The existing PRD owner now applies a [reviewed OWASP procedure](../skills/to-sdd-prd/references/security-authoring.md), using the bundled, version-pinned ASVS 5.0.0 catalog. Architecture, DoD, QA and the development plan preserve the same security requirement IDs through their existing documents. UX/design owners route security-relevant changes upstream; visual-only changes can retain unaffected requirements. No new skill, document, approval stage, paid service or automatic security scan is added.

The [security contract](../skills/to-sdd-pipeline/references/security-contract.md) defines owner-return metadata and the required `product_security_requirements` gate. The read-only checker verifies catalog integrity, real control IDs, owned references, downstream coverage and implementation-level evidence. Missing legacy assessments need owner review, not invented history. Documentation completeness is not product security verification or ASVS certification.

Keep the catalog, its license and attribution together. To update the standard, review the official release, applicability and procedure mappings; update the pins in the reader and checker, attribution, migration guidance and regression tests together. Do not fetch a moving catalog during normal authoring. Preserve the catalog's bytes on Windows as specified by `.gitattributes`.

## Requirements and adoption

Install **Python 3.12+** for installer/checker execution; **3.14** is the current recommended stable series. Python has maintenance phases, not an LTS designation: [official support table](https://devguide.python.org/versions/), [official downloads](https://www.python.org/downloads/). The dated [runtime policy](../runtime-policy.json) requires another review before 2026-11-01. No student Node or third-party Python package is added. Keep helper files with the complete collection.

For older projects, preserve documents, IDs, approved versions and history. Add only metadata verified from current sources and original receipts; revalidate affected owner outputs. Do not manufacture evidence, rewrite valid documents just for concision, or repeat approval to populate fields. Follow the [manifest migration contract](../skills/to-sdd-pipeline/references/manifest-contract.md).

Artifact `source_usage` records owner-reviewed consumption, including shared sections referenced by QA definitions, or an explicit reason for unused context. Missing legacy declarations require owner review; do not infer them from existing hashes. `--snapshot NODE` leaves context as `review_required`; `--consume` and `--unused` resolve actual choices without writing or validating the manifest. This adds no scheduling dependency or approval. The checker verifies declared coverage and byte changes, not whether the agent disclosed every source it used. Intake must display interpretation and gaps alongside its one question, not merely save them.

For example, `--consume 'docs/qa-checklist.md### Check definitions'` selects the literal heading `## Check definitions`: the first `#` separates the path from the heading. Repeat for every consumed shared section, or use the path alone for the full file. Keep execution results outside planning sections to avoid invalidation when only later results change.

Checker JSON escapes non-ASCII characters for Windows output pipes; JSON decoding restores exact localized paths/headings. Source documents remain UTF-8. Regression tests exercise non-UTF-8 pipe encoding explicitly.

Direct Codex/Claude Code authoring needs no external runner. Production execution is a separate host integration; any external runner must enforce the checker itself. The checker validates records and integrity, not complete prose semantics, authentic human research or actions outside its control.

## Verification

Run from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tests/test-install.sh
bash tests/test-retirement.sh
bash tests/test-update.sh
```

Windows uses `python` and the PowerShell suites:

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
.\tests\test-install.ps1
.\tests\test-retirement.ps1
.\tests\test-update.ps1
```

Tests use isolated temporary projects and installation roots. **Do not run the default personal installer merely to test skill-authoring changes:** its retirement cleanup is permanent.

Coverage includes first entry, owner stages, approved-design reconciliation, resume/migration, real cycles versus later lookups, changed source fragments, language changes, stale baseline/evidence, candidate revisions, browser/source-access receipts, separate authorization, promotion mappings, malformed/reformatted JSON, missing dependencies, relocation/repair, idempotence and existing cleanup/update behavior. Synthetic receipts are explicitly fixtures, not real user research or product-test results.

Security regressions also cover the offline catalog and exact IDs, adapted/non-web scopes, missing or stale assessments, supplemental requirements, coverage across all four downstream owners, mandatory gates, negative checks, and rejection of mockup-only or not-applicable substitutes. Run the complete suite after changing security instructions or records; it does not audit a product or run vulnerability scanners.

CI runs runtime/installer suites on Linux, macOS and Windows with Python **3.12 and 3.14**. The content job uses 3.14 and pinned test-only YAML/token tools. Without PyYAML, its optional local parser test is skipped. Pinned supported Actions supply their own runtime; no student Node installation is needed. CI advances `stable` only after all required jobs pass for current `main`; it never force-pushes or updates student machines.

See [agent evaluations](agent-evaluations.md) for fresh-context runs and review. Do not present these fixtures, deterministic receipts or the authoring agent's own review as completed independent model/user validation.

## Reproducible instruction budget

In an isolated development environment:

```bash
python3 -m venv .venv-token-check
.venv-token-check/bin/python -m pip install -r tests/requirements.txt
.venv-token-check/bin/python scripts/measure_tokens.py --summary --check
```

On Windows use `.venv-token-check\Scripts\python.exe`. The encoder may download its public vocabulary on first use; no project content is uploaded. Runtime installation never needs this dependency or download.

Baseline: `e5d6ab9df4502cf6babc76e273602ecbd66881f0`; tokenizer: `tiktoken 0.14.0`, `o200k_base`. [Fixed fixtures](../tests/fixtures/token-scenarios.json) use identical seeds and invocation sequences for old/new instructions. Every invocation includes its complete applicable shared/conditional references, the machine contract where consulted, and listed retries. No caching discount is assumed.

The historical baseline remains available for comparison. The earlier audit used `f0923e2` and the following measured loads, including its shared/conditional contracts:

| Scenario | Audited revision | After remediation | Increase |
|---|---:|---:|---:|
| First setup, including one retry; 18 invocations | 92,271 | 103,522 | 12.19% |
| Approved-design revision, including one retry; 7 invocations | 47,691 | 54,855 | 15.02% |
| Interrupted Claude resume, including one retry; 7 invocations | 57,200 | 64,522 | 12.80% |

That pre-unit-correction revision had 15,592 entrypoint tokens versus 14,881 at the audit, and README 3,698 versus 3,093. Source-tracking and intake-display fixes fit its then-current ceilings. These figures are historical, not a new savings claim.

The 2026-09-15 unit-contract review advances the recent comparison to pre-change revision `1272cdd`, while retaining the earlier audit table above. The new contract is counted in full for QA, planning and orchestration, including repeated invocations. Runtime record fields are necessary for the execution handoff; putting them in a shared conditional reference avoids repeating the schema in skill entrypoints but does not imply free cached reads.

| Measured scope | Before unit correction | After correction | Full-unit clarification (Oct 2) | Absolute ceiling | Allowed growth from 1272cdd |
|---|---:|---:|---:|---:|---:|
| Entrypoints | 15,592 | 15,855 | 15,883 | 15,900 | 300 |
| README | 3,698 | 3,807 | 3,827 | 3,850 | 150 |
| First setup, including one retry | 103,522 | 112,501 | 112,817 | 113,000 | 9,500 |
| Approved-design revision, including one retry | 54,855 | 62,993 | 63,309 | 63,500 | 8,500 |
| Interrupted Claude resume, including one retry | 64,522 | 72,894 | 73,210 | 73,500 | 8,800 |

Those historical ceilings accepted the measured correctness cost for dependency/ownership validation, evidence-backed completion, migration and host boundaries. The [current reviewed policy](../tests/fixtures/instruction-budget.json) compares the numeric-order correction against `8bad1f6`:

| Scope | Before numeric-order correction | After | Absolute ceiling | Allowed growth |
|---|---:|---:|---:|---:|
| Entrypoints | 15,883 | 15,945 | 16,000 | 120 |
| README | 3,827 | 3,910 | 3,950 | 150 |
| First setup, including one retry | 112,817 | 114,295 | 114,500 | 1,700 |
| Approved-design revision, including one retry | 63,309 | 64,787 | 65,000 | 1,700 |
| Interrupted Claude resume, including one retry | 73,210 | 74,797 | 75,000 | 1,800 |

The added walkthrough, numeric rules, migration and provenance increase cold scenario loads 1.31–2.33%. Both absolute ceilings and growth limits retain bounded headroom. Run without `--summary` for counted files. `--check` fails above either limit; further growth needs another explicit policy/table review. Instruction reuse is encouraged but receives no assumed discount.

These are deterministic **instruction-load budgets**, not live-agent benchmarks. They do not measure generated-document savings, actual retry frequency, tool output, model quality, cached-token billing or total end-to-end cost. Concise document rules are enforced as authoring guidance; real project runs are still needed to measure their practical effect.

At the September unit-contract release, the complete Python 3.14 suite with pinned test dependencies passed 167 tests with no skips. Python 3.12 and isolated Windows installer, retirement and updater suites also passed. The October clarification fits the unchanged token ceilings/growth limits above. These checks validate code and records; they do not establish production-host continuation or constitute real product acceptance evidence.

Security procedure and record instructions are counted for their consumers. Selected ASVS controls returned by the offline reader are tool output and therefore add tokens outside this static budget. Only the PRD owner reads applicable controls; downstream owners reuse requirement IDs and their local consequences. Offline does not mean token-free, but this integration starts no deep scans or paid security service.

## Future edits

Keep names, artifact paths, owners and authorization boundaries stable. Change required-before edges only in the machine artifact map; reconciliation nodes inherit them. Update shared rules at their owner, resolve every linked reference, rerun applicable tests and token scenarios, then review semantic coverage—not only word counts. Update this measurement table when counted instructions change. Keep historical version notes historical.

## Evidence storage implementation — 2026-10-11

Storage version 1 preserves the 13 owners, source authority, approved-design and original authorization receipts, required security/real-consumer acceptance and the separate implementation prompt. QA definitions and compact current interpretations stay canonical; verified references preserve detailed observations and superseded history. All evidence consumers retain their original JSON semantics and bindings. Legacy contained records remain supported; missing evidence and unsupported/incomplete migration fail rather than manufacture a pass.

The storage manager performs network/cache writes; the checker only verifies prepared original bytes and reference closure outside the checkout. Shared content-addressed inventories expand identical contained source maps. Stable project/unit IDs join generation/reservation charges across workers, retries, sessions and worktrees. Deduplication affects retained occupancy without refunding gross production. One coordinator controls catalog mutation/pruning; incomplete knowledge of shared clients prevents remote pruning. Managed tools enforce managed operations, while external writers require registered-output reconciliation before completion.

[Versioned defaults and rationale](evidence-storage.md#defaults-and-sizing) specify run/unit/project bytes/counts, retained content/physical objects, combined metadata/index size, local capture/cache/staging/readback/restoration, retry limits, reserve and separate migration batches. The 250/500 MiB run warning/stop starter profile accepts a synthetic 40 MiB/200-capture workload, warns at 300 MiB/60 diagnostics, then blocks another 201 MiB in the same run. Concurrent 6-byte reservations against a shared 10-byte unit allow exactly one worker. Three bounded 8-byte migration batches remain possible against a 10-byte normal retained limit with a legacy 1,000-byte object, without charging new generation. These deterministic boundary/retry/split/reservation workloads justify the starter arithmetic, not product performance. Required observations always take precedence over compactness targets. Tests deliberately use synthetic data and isolated directories, not private recovery archives or product migrations.

Local generation retention is 30 days from original sealing; replaceable cache eviction differs from durable expiry. Current acceptance/prerequisites, baseline, approval/authorization, unresolved failures, explicit retention and imported recovery material remain protected. Drive expiry requires an explicit choice. GitHub artifact upload retention and repository artifact/log settings are separate; current workflows need no artifact uploads, so none are added. Repository-setting verification and real Drive smoke-test evidence are reported independently of mocked transport regressions. Required GitHub evidence must reach durable storage before its external expiry.

No personal skill installation or product migration is part of authoring validation. Run the full Python and applicable Unix/Windows installation/update suites, resource/ownership checks and unchanged instruction budgets. `tests/test_evidence_contracts.py` checks cross-owner history/storage/source boundaries, all supported evidence consumers, conditional resource accounting and workflow/log-retention distinctions. Detailed storage procedures load only for production/resolution/import/cleanup; scenario fixtures explicitly declare which invocations consume them. QA fixture invocations author/reconcile definitions and do not load payload procedures. Reuse original raw observations rather than redundant reformatted bulk copies; record failed/incomplete work honestly and clean task-owned browser profiles.


The 2026-10-11 storage guidance passes the **unchanged** instruction ceilings and recent-growth allowances, using `tiktoken 0.14.0` / `o200k_base` with complete shared references, conditionally declared storage consumers and listed retries. Repetition was shortened; no budget was raised:

| Measured load | Recent baseline `8bad1f6` | Current | Change |
|---|---:|---:|---:|
| 13 entrypoints | 15,883 | 15,813 | -70 |
| README | 3,827 | 2,952 | -875 |
| First setup with retry | 112,817 | 110,178 | -2,639 |
| Approved-design revision | 63,309 | 64,052 | +743 |
| Interrupted Claude resume | 73,210 | 74,918 | +1,708 |

The revision/resume increase is the verified external-evidence contract's static cost. Against the much older `e5d6ab9` benchmark, total scenario loads remain 13.65–29.39% higher while entrypoints/README are smaller; do not present that as overall scenario savings. These counts exclude runtime tool outputs and do not establish research quality, producer efficiency or model billing.

A fresh-context delegated local CLI smoke also exercised a frozen 93-file generic source snapshot (`59173f6087520465a0780d3015126475fee504980c26b128d87e5c12d2b6739d`). Saved setup retained IDs/defaults and 30-day retention; an actual managed producer generated 1,234 bytes across two files. Archive, prepare and restore preserved exact original bytes without double charging. Eight checker invocations verified prepared evidence, blocked absent/corrupt/stale-source/stale-plan evidence and unauthorized implementation, and left inspected project/cache bytes unchanged. The snapshot's checker digest was `8388334ddd86a4da88b664a081c78fba37cee1a4625ff421f5836bcf3cc5dad9`, skillset digest `f6793324e37f8da66e13b420ca831d47ec8c3ae1daffdec4f119abc210815a50`. Full original outputs remain external to Git.

This is synthetic frozen-snapshot behavior evidence, not latest-HEAD acceptance, real Drive verification, product acceptance or a full independent pipeline/user evaluation. The earlier live-source smoke recorded changing fingerprints and possible ignored Python bytecode-cache writes; the frozen rerun excluded caches, suppressed bytecode and verified stable source bytes. Its concrete usability findings covered existing-empty-output-directory requirements, macOS temporary-path aliases, and the setup status command hint; these must be reconciled with current documentation/tooling rather than concealed by the passing lifecycle.

The earlier real connected Drive smoke exercised `JsonCommandAdapter` through 117 real subprocess bridge calls, including bounded stdin handling and helper/input-writer cleanup. Its frozen functional snapshot of all 11 runtime files included the I/O, accounting and transport fixes; subsequent imported-retention administration, fingerprint and capacity-read SQLite cleanup changes require separate regression and native-CI verification. It archived 114,688 synthetic original bytes (SHA-256 `8c341a8868d334c998e078bc82b954913b89b0efca287fdf1b7be40c18052041`) into a 114,950-byte pack (SHA-256 `32290406eb8957b343375fa2d5e2b9f4c736c00ba9906d872b36cc5bc2b87b20`), independently retrieved them, prepared them again from a warm store, then recovered the fresh remote catalog and restored exact bytes without the original checkout or local database. Gross generation stayed 114,688 bytes / one logical file; verified retained content stayed 114,688 bytes / one pack. Metadata was 5,261 bytes across two objects, with zero unpublished packs. The cold client remained read-only for coordinator mutation. All three test objects and their empty folder were individually deleted and their absence verified by 404 responses; helpers and input writers stopped, and the task's local temporary directory was confirmed absent. Full original outputs and the snapshot report remain outside Git. This verifies real transport/storage behavior for synthetic data on that frozen runtime, separately from latest-HEAD acceptance, mocked connector/rclone regressions, the earlier local CLI snapshot, product acceptance and independent user/pipeline evaluation. The repository's applicable GitHub Actions artifact/log setting was separately read back as 30 days; no unnecessary artifact uploads were added. Complete suite/runtime/CI results remain a separate validation record.


Earlier local validation after cross-platform, raw archive-name, compact inventory, immutable-retention, Windows read-sharing, capture-failure and transport cleanup fixes: **482 tests in 39.601 seconds, all applicable tests passed**, with four native-Windows-only skips, on Python **3.12.14** and pinned test-only dependencies in an isolated environment. Unix installer, retirement and updater suites passed; shell syntax and whitespace/diff checks passed. Instruction measurements are 15,813 entrypoint tokens, 2,930 README tokens, and scenario loads 110,178 / 64,052 / 74,918 under unchanged ceilings. Native Linux/macOS/Windows × Python 3.12/3.14 results, including Windows PowerShell installers, are tracked in [PR #6's required checks](https://github.com/Ingwarski/sdd-pipeline-skills/pull/6/checks). Local PowerShell and native rclone were unavailable; subprocess rclone regressions remain separate from real connected Drive verification. No browser or temporary Chromium profile was created by the authoring coordinator or delegated smoke.

The README Google Drive prerequisite clarification was checked against official Codex plugin and Claude Code connector instructions. Its focused ownership/resource/YAML and evidence-contract checks passed (10 tests); instruction budgets remain unchanged, with README at 2,930 tokens. This documentation-only follow-up does not claim to add a reusable host bridge or change the archive runtime.

### Requirements-audit corrections — 2026-10-11

The subsequent requirements audit found defects that the earlier passing suite did not cover. Compact local JSON receipts now validate nested evidence closure, and active imported JSON is resolved before publication. Generation requires the project's designated coordinator; shared-run publications merge total snapshots without double charging. Observed log rewrites count toward gross generation, and retired members remain charged while their shared pack is retained. Durable generation intents, settled snapshots and local recovery journals preserve failed attempts; missing authoritative history blocks new generation and completion while allowing bounded payload recovery. Renamed or missing output roots settle as incomplete. Parallel producers use deferred completion, followed by coordinator completion after every worker settles.

Setup forwards custom evidence homes, detects missing configuration on first managed use, and preserves pending project/store identities across interrupted verification. Safe missing-upload acknowledgement works both for configured projects and unpublished setup attempts, with owned-checkpoint and fresh-absence checks. Cloud checkpoint metadata and atomic replacement peaks have their own bounded reservations. Coordinator creation and catalog access are serialized. A permanent operating-system guard makes catalog lock acquisition, publication, release and stale-lock recovery atomic across processes, preventing a recovery command from removing a new live lock; actual catalog work runs outside this short lifecycle guard. Windows sharing conflicts have bounded retries, and unsafe paths and foreign owners remain rejected. These corrections have focused regression coverage, including four actual concurrent CLI producers and loss of both SQLite and its recovery journal.

The supplied foreground connected-host adapter now uses the installed authenticated Drive plugin directly. Connected mode is the default Drive selection; README and storage-choice descriptions state the Codex plugin and Claude Code connector prerequisites. No user-written bridge or rclone installation is required for compatible connected tools. The documented bounded folder listing supports at most 999 direct items and refuses incomplete listings. XZ adoption verifies original `.tar.xz` members with bounded decoder memory, expanded bytes and header counts, without manual repacking or payload reupload.

The real installed-plugin flow passed setup, managed production, archiving and cold recovery of **22,555 original bytes across two files**, with the original checkout, capture directory and warm project state unavailable during recovery. Both restored SHA-256 hashes matched; archiving left warm generation totals at 22,555 bytes/two files. The pack was 23,057 bytes, SHA-256 `95bdb8d28501fb43a11d6308941480f8f9b62fad4bf2916dbb2b2e99910db1bd`. All 13 synthetic Drive objects and their folder were individually removed and absence verified; the private host session and temporary response file were removed. Cold accounting status was not requested in that live test; dedicated regressions verify recovered accounting behavior. This real flow preceded the final generic checkpoint and Windows cleanup refinements, which have separate regression coverage. At that stage, the optional rclone route had subprocess coverage without a live account test.

### Installed rclone verification — 2026-10-11

The official macOS ARM64 rclone 1.75.2 executable was installed after verifying its published SHA-256. Actual streamed transfers exposed two failures missed by the simulated subprocess tests: command-line size values could round down (1,048,577 bytes became 1,048,576), and single-file copies could replace existing bytes despite `--immutable`. Payload operations now use numeric per-call limits through foreground `rc --loopback`, retaining the exact HARD cutoff without starting a server. Uploads skip existing objects and independently retrieve their original bytes; a conflicting object remains unchanged and its pending checkpoint is retained.

The full Python suite passed **599 tests in 74.738 seconds**, with five native-Windows-only skips. Two subsequently added optional native tests passed against the installed executable; they exercise production transfer commands with local HTTP fixtures, exact limits, one-byte-over-limit rejection and existing-file preservation. They clearly skip when rclone is absent. Instruction budgets passed unchanged. An external local rehearsal also passed setup, managed production, archive retry, adoption, warm/cold byte restoration and scoped cleanup, using real rclone with synthetic Drive identity mapping. These checks do not constitute a live Google Drive account test. After losing the original accounting database, recovery correctly reports exact known generation totals as lower bounds, an incomplete accounting receipt and an unauthorized coordinator.

Final local validation: **595 tests in 69.370 seconds, all applicable tests passed**, with five native-Windows-only skips, using Python 3.12.14 and approved isolated test dependencies. Unix installer, retirement and updater suites passed. Ownership/resource/YAML checks and unchanged instruction budgets passed: 15,813 entrypoint tokens, 2,952 README tokens, and scenario loads 110,178 / 64,052 / 74,918. Native Linux/macOS/Windows × Python 3.12/3.14 results are reported by [PR #6's required checks](https://github.com/Ingwarski/sdd-pipeline-skills/pull/6/checks). No browser profiles, personal skill installation, private product migration, merge or release were part of this verification.
