# Reliability and Concision Update

The seven-point update keeps the same 13 skills and document owners. Jobs To Be Done, use cases, H1–H10, error recovery, representative-user validation and the approved-design model remain in place.

## What changed

1. **Correct continuation after approval.** Record the baseline, recheck affected architecture, completion rules and QA, then create the development plan. Reuse valid documents; no extra approval procedure.
2. **Prepared is not tested.** Check definitions, actual execution and release readiness have separate statuses. A pass needs appropriate, current evidence; unresolved required checks cannot support release.
3. **Reliable shared rules.** Skills resolve references from their installed real directory, including links, not from the product folder. Moving the clone is covered by repair tests.
4. **Executable consistency checks.** A read-only checker validates prerequisites, owners, source hashes, context-bundle integrity, baseline/candidate evidence and separate implementation authorization. Later references are not scheduling dependencies.
5. **Consistent installation.** Both installers use one strict JSON/source validator and detect Python before mutation. Existing scoped cleanup, unrelated-skill protection and safe-update behavior remain intact.
6. **Clearer documentation.** README is the entry point; installation and maintenance details are linked separately. Shared rules have one home. Standalone owners and orchestrator responsibilities are explicit; the audit prompt and single install-or-update prompt are current.
7. **Less repetition.** All skill instructions and generated-document rules use direct language, brief term explanations and references to decisions already defined elsewhere. Token checks include shared instructions and repeated loads, not just short entrypoints.

SDD still determines what to build; QA verifies it. A validated plan still ends at `awaiting-implementation-prompt` until a later explicit user request authorizes production implementation.

## OWASP security integration

The existing PRD owner now applies a [reviewed OWASP procedure](../skills/to-sdd-prd/references/security-authoring.md), using the bundled, version-pinned ASVS 5.0.0 catalog. Architecture, DoD, QA and the development plan preserve the same security requirement IDs through their existing documents. UX/design owners route security-relevant changes upstream; visual-only changes can retain unaffected requirements. No new skill, document, approval stage, paid service or automatic security scan is added.

The [security contract](../skills/to-sdd-pipeline/references/security-contract.md) defines owner-return metadata and the required `product_security_requirements` gate. The read-only checker verifies catalog integrity, real control IDs, owned references, downstream coverage and implementation-level evidence. Missing legacy assessments need owner review, not invented history. Documentation completeness is not product security verification or ASVS certification.

Keep the catalog, its license and attribution together. To update the standard, review the official release, applicability and procedure mappings; update the pins in the reader and checker, attribution, migration guidance and regression tests together. Do not fetch a moving catalog during normal authoring. Preserve the catalog's bytes on Windows as specified by `.gitattributes`.

## Requirements and adoption

Install **Python 3.9+** before updating. Installers and the checker use only the standard library; students do not need the test-only packages below. Keep runtime helper files with the complete skill collection.

For older projects, preserve documents, IDs, approved versions and history. Add only metadata verified from current sources and original receipts; revalidate affected owner outputs. Do not manufacture evidence, rewrite valid documents just for concision, or repeat approval to populate fields. Follow the [manifest migration contract](../skills/to-sdd-pipeline/references/manifest-contract.md).

The external DAS Forge runner is **not part of this repository**. Skills require the checker, but hard runtime enforcement requires that runner to invoke it before/after dispatch and obey its exit code. The checker validates recorded evidence and integrity; it cannot prove research authenticity or all document semantics.

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

CI runs the runtime/installer suites on Linux, macOS and Windows with Python 3.9. A separate content job uses Python 3.11 plus pinned test-only dependencies for YAML and instruction-budget validation. Without PyYAML, only that optional local YAML-parser test is skipped; CI runs it with the dependency installed.

## Reproducible instruction budget

In an isolated development environment:

```bash
python3 -m venv .venv-token-check
.venv-token-check/bin/python -m pip install -r tests/requirements.txt
.venv-token-check/bin/python scripts/measure_tokens.py --summary --check
```

On Windows use `.venv-token-check\Scripts\python.exe`. The encoder may download its public vocabulary on first use; no project content is uploaded. Runtime installation never needs this dependency or download.

Baseline: `e5d6ab9df4502cf6babc76e273602ecbd66881f0`; tokenizer: `tiktoken 0.14.0`, `o200k_base`. [Fixed fixtures](../tests/fixtures/token-scenarios.json) use identical seeds and invocation sequences for old/new instructions. Every invocation includes its complete applicable shared/conditional references, the machine contract where consulted, and listed retries. No caching discount is assumed.

Current measurements include design-materials intake and the OWASP procedure, security records and downstream instructions.

| Scenario | Before | After | Reduction |
|---|---:|---:|---:|
| First setup, including one retry; 18 invocations | 96,945 | 92,271 | 4.82% |
| Approved-design revision, including one retry; 7 invocations | 49,810 | 47,691 | 4.25% |
| Interrupted Claude resume, including one retry; 7 invocations | 57,903 | 57,200 | 1.21% |

The 13 entrypoint files alone shrink from 44,084 to 14,881 tokens (66.24%), but **the smaller whole-scenario percentages are the meaningful comparison** because shared text still costs tokens when loaded. Run without `--summary` to inspect every counted file. `--check` fails if any measured budget ceases to improve on the recorded baseline.

These are deterministic **instruction-load budgets**, not live-agent benchmarks. They do not measure generated-document savings, actual retry frequency, tool output, model quality, cached-token billing or total end-to-end cost. Concise document rules are enforced as authoring guidance; real project runs are still needed to measure their practical effect.

Security procedure and record instructions are counted for their consumers. Selected ASVS controls returned by the offline reader are tool output and therefore add tokens outside this static budget. Only the PRD owner reads applicable controls; downstream owners reuse requirement IDs and their local consequences. Offline does not mean token-free, but this integration starts no deep scans or paid security service.

## Future edits

Keep names, artifact paths, owners and authorization boundaries stable. Change required-before edges only in the machine artifact map; reconciliation nodes inherit them. Update shared rules at their owner, resolve every linked reference, rerun applicable tests and token scenarios, then review semantic coverage—not only word counts. Update this measurement table when counted instructions change. Keep historical version notes historical.
