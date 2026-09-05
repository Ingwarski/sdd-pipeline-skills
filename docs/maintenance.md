# Reliability, Audit Remediation and Maintenance

The September 2026 audit remediation builds on the earlier seven-point update. The 13 names, document owners, Jobs To Be Done, use cases, H1–H10, error recovery and approved-design model remain intact. Private next-version planning is not part of this release.

## What changed

1. **Trustworthy release records (F1, F4).** Gate/check membership works both ways. Excluded checks cannot cover required clauses or applicable heuristics. Promotion receipts verify actual Git ancestry, scoped patches, source/destination bytes and evidence—not just filenames.
2. **Frozen design inputs (F2).** Shared CSS, fonts, scripts and other rendering inputs join the baseline hash. Static dependency checks supplement actual browser/network inspection; they do not prove dynamic completeness.
3. **Proportional scope (F3, F9).** Confirmed headless projects skip UI documents/approval; existing changes reuse valid artifacts and reconcile affected owners. Full UI projects retain three candidates. Bounded early exploration remains non-production.
4. **Typed traceability (F5).** Existing owner documents define job, use-case, requirement/clause, surface/state, QA and unit IDs. A compact index checks types, references and stage-appropriate coverage; later mappings are not earlier dependencies.
5. **Clear design and portable execution (F7–F8).** Separate neutral behavioral research from operator decisions; apply measurable accessibility before house-style defaults. Direct hosts can run owners inline, persist intake, reject stale returns and honor an explicitly selected visible browser.
6. **Lifecycle and behavior evaluation (F10–F11).** Existing owners cover applicable delivery, rollback/restore, operations, maintenance, performance/cost and outcome measurement. Ten raw agent-evaluation scenarios and an evidence rubric are provided; they are explicitly **not run**, separate from deterministic tests.
7. **Supported installation (F6, F12).** Maintained Python boundaries, exact installed-target/resource checks, old-clone bootstrap, no-op ordering and a CI-tested `stable` channel. Scoped retirement and unrelated-work protections remain unchanged.
8. **Measured instruction costs (F13).** Shared rules are shorter; unchanged rules/sources are reused when available. `--snapshot NODE` proposes hashes without claiming validation. Recent-version growth and absolute ceilings now prevent regressions hidden by an older benchmark.

SDD still determines what to build; QA verifies it. A validated plan still ends at `awaiting-implementation-prompt` until a later explicit user request authorizes production implementation.

## OWASP security integration

The existing PRD owner now applies a [reviewed OWASP procedure](../skills/to-sdd-prd/references/security-authoring.md), using the bundled, version-pinned ASVS 5.0.0 catalog. Architecture, DoD, QA and the development plan preserve the same security requirement IDs through their existing documents. UX/design owners route security-relevant changes upstream; visual-only changes can retain unaffected requirements. No new skill, document, approval stage, paid service or automatic security scan is added.

The [security contract](../skills/to-sdd-pipeline/references/security-contract.md) defines owner-return metadata and the required `product_security_requirements` gate. The read-only checker verifies catalog integrity, real control IDs, owned references, downstream coverage and implementation-level evidence. Missing legacy assessments need owner review, not invented history. Documentation completeness is not product security verification or ASVS certification.

Keep the catalog, its license and attribution together. To update the standard, review the official release, applicability and procedure mappings; update the pins in the reader and checker, attribution, migration guidance and regression tests together. Do not fetch a moving catalog during normal authoring. Preserve the catalog's bytes on Windows as specified by `.gitattributes`.

## Requirements and adoption

Install **Python 3.12+** for installer/checker execution; **3.14** is the current recommended stable series. Python has maintenance phases, not an LTS designation: [official support table](https://devguide.python.org/versions/), [official downloads](https://www.python.org/downloads/). The dated [runtime policy](../runtime-policy.json) requires another review before 2026-11-01. No student Node or third-party Python package is added. Keep helper files with the complete collection.

For older projects, preserve documents, IDs, approved versions and history. Add only metadata verified from current sources and original receipts; revalidate affected owner outputs. Do not manufacture evidence, rewrite valid documents just for concision, or repeat approval to populate fields. Follow the [manifest migration contract](../skills/to-sdd-pipeline/references/manifest-contract.md).

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

The historical baseline remains available for comparison. Enforcement now uses the immediately preceding audited revision `f0923e2` plus [reviewed absolute ceilings](../tests/fixtures/instruction-budget.json). Measurements include the new shared/conditional contracts; actual needed correctness instructions increased cold-load costs:

| Scenario | Audited revision | After remediation | Increase |
|---|---:|---:|---:|
| First setup, including one retry; 18 invocations | 92,271 | 103,326 | 11.98% |
| Approved-design revision, including one retry; 7 invocations | 47,691 | 54,659 | 14.61% |
| Interrupted Claude resume, including one retry; 7 invocations | 57,200 | 64,131 | 12.12% |

Entrypoints are 15,515 tokens versus 14,881 at the audited revision; README is 3,665 versus 3,093. These remain below the much older baseline but are **not a new savings claim**. Run without `--summary` for counted files. `--check` fails above either an absolute ceiling or the reviewed recent-growth allowance. Further contract growth needs an explicit policy/table review, not silent budget inflation. Reuse of instructions still present in context is encouraged but receives no assumed discount here.

These are deterministic **instruction-load budgets**, not live-agent benchmarks. They do not measure generated-document savings, actual retry frequency, tool output, model quality, cached-token billing or total end-to-end cost. Concise document rules are enforced as authoring guidance; real project runs are still needed to measure their practical effect.

Security procedure and record instructions are counted for their consumers. Selected ASVS controls returned by the offline reader are tool output and therefore add tokens outside this static budget. Only the PRD owner reads applicable controls; downstream owners reuse requirement IDs and their local consequences. Offline does not mean token-free, but this integration starts no deep scans or paid security service.

## Future edits

Keep names, artifact paths, owners and authorization boundaries stable. Change required-before edges only in the machine artifact map; reconciliation nodes inherit them. Update shared rules at their owner, resolve every linked reference, rerun applicable tests and token scenarios, then review semantic coverage—not only word counts. Update this measurement table when counted instructions change. Keep historical version notes historical.
