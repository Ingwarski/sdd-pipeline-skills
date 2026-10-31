# Maintaining the skillset

This guide defines current maintenance and verification procedures. Keep all 13
invocation names, artifact owners, source authority and approval boundaries stable.
Use the [specification quality rules](specification-quality.md) when changing
construction, acceptance, recovery or evidence behavior.

## Keep reusable instructions generic

Derive product users, roles, interfaces, capabilities, platforms, data handling,
components and delivery requirements from project sources. Check each mandatory
rule against different supported scopes: visual and nonvisual interfaces, native
and web platforms, local and shared services, persistent and transient data.
A feature or input mode must not become mandatory merely because a test uses it.
Preserve applicable security, accessibility, recovery and acceptance duties.

Keep supported toolchain requirements, optional adapters, standard catalogs and
installation compatibility identifiers explicit. Their scope is the skillset or
selected integration, not every product. Concrete executable fixtures belong in
isolated test inputs and do not define product requirements.

Store test-project details, authoring decisions, audit findings, run logs,
measurements and historical results in separate reports outside reusable
instructions. Do not add them to the README, owner skills or shared contracts.
Before removing historical material, preserve its original bytes and source
revision in the report archive. Keep current rules and procedures in this guide;
record outcomes from running them in the separate report.

## Preserve execution authority

Project `AGENTS.md` owns execution behavior; the bundled project policy contains
six permitted pause reasons and concrete coordination, verification and recovery
rules. Keep that policy intact during maintenance. Guardrails owns project-specific
authority, DoD owns completion predicates, QA owns checks/results and the plan owns
unit scope/dependencies. Do not duplicate the pause policy into those documents.

Initial implementation still requires a validated plan, the recorded pause and a
later explicit implementation prompt. Only the verified approved-decision
correction contract can preserve existing permission across an eligible correction;
new or uncertain scope requires current authority. Completion applicability,
plan validity and permission remain separate. The checker does not prove authentic
human approval, host instruction loading or actual product execution.

## Review a change

1. Verify repository identity, branch, revision and working-tree changes.
2. Inspect affected owners, shared contracts, schemas, callers and tests.
3. Preserve one owner per artifact. Reconcile dependencies and source usage.
4. Check source-defined applicability across the supported product scopes.
5. For changed executable behavior, add focused regression cases that demonstrate
   the defect and preserve related acceptance and authorization requirements.
6. Run the applicable checks below and inspect their actual results. Record
   unavailable environments, skipped tests and remaining limits separately.
7. Use independent semantic review for changes to cross-owner or applicability
   rules. Behavioral exercises follow the [evaluation protocol](agent-evaluations.md).

Do not use the personal installer to test authoring changes. Installer tests use
isolated temporary roots; default retirement cleanup permanently removes named
skills. Do not install dependencies without user authorization.

## Verification

Use a supported Python version from [runtime policy](../runtime-policy.json).
Run the complete regression suite for runtime or shared-contract changes:

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
bash tests/test-install.sh
bash tests/test-retirement.sh
bash tests/test-update.sh
```

On Windows:

```powershell
python -B -m unittest discover -s tests -p 'test_*.py' -v
.\tests\test-install.ps1
.\tests\test-retirement.ps1
.\tests\test-update.ps1
```

Ownership, packaged resources and skill frontmatter have a focused check:

```bash
python3 -B -m unittest discover -s tests -p 'test_skill_contracts.py' -v
```

The content CI job installs the pinned test-only dependencies in
[requirements.txt](../tests/requirements.txt). Without the optional YAML parser,
its parser check is skipped locally. Report that skip. Syntax and links alone do
not establish that an instruction is semantically correct.

CI covers Linux, macOS and Windows with Python 3.12 and 3.14. The tested `stable`
channel advances only after the current `main` passes its required jobs. A passing
local suite does not establish another platform's result. Report CI outcomes for
the exact reviewed commit; do not carry results forward from an earlier revision.

## Reproducible instruction budget

In an authorized isolated development environment with the pinned dependencies:

```bash
python3 -m venv .venv-token-check
.venv-token-check/bin/python -m pip install -r tests/requirements.txt
.venv-token-check/bin/python scripts/measure_tokens.py --summary --check
```

On Windows use `.venv-token-check\Scripts\python.exe`. The tokenizer can download
its public vocabulary on first use; no project content is uploaded. Runtime
installation does not require these test dependencies.

The [budget policy](../tests/fixtures/instruction-budget.json) compares current
instruction loads with checksum-pinned numerical snapshots stored in
`tests/fixtures`. Snapshots retain tokenizer and method versions, the scenario
definitions checksum, per-resource token counts and hashes, and complete invocation
and retry accounting. They contain no historical source text and require no Git
history. CI enforces absolute ceilings and growth against the recent snapshot.

To propose a reviewed baseline, run
`python scripts/measure_tokens.py --record-baseline <new-file.json>`; recording
never updates policy. Review instruction changes, all scenario loads, measured
totals and budget rationale independently before changing snapshot references or
limits. Use `--summary --check` for verification. A snapshot refresh is not
permission to weaken a check. Keep all [scenario inputs](../tests/fixtures/token-scenarios.json),
seeds, invocation sequences, conditional resources and retries; do not remove
loads to make a change pass.

Run without `--summary` to inspect counted files. Static instruction counts do not
measure generated documents, tool output, live retry frequency, model quality,
cache billing or total cost. Preserve detailed measurements in the separate report.

## Verification performance

Add `--performance` to a normal `sdd_check.py` invocation to include bounded,
fixed-label timing and counters for history, hashing, JSON parsing and path checks.
These diagnostics do not change acceptance. Nested timing reports inclusive and
exclusive durations; do not sum overlapping inclusive phases.

`python tests/benchmark_history.py --depths 0 1 3 --repeats 3` measures isolated
synthetic attempt histories. `python tests/benchmark_legacy_payloads.py --files 500
--repeats 3` compares the narrow legacy-payload integrity modes. Keep fixture,
runtime and host conditions matched, record setup separately, and retain results
outside the repository. Synthetic timings do not establish product-run savings.

## Evidence and compatibility checks

Follow the [evidence contract](../skills/to-sdd-pipeline/references/evidence-storage-contract.md)
for accounting, reservations, immutable archives, byte retrieval and cleanup.
The storage manager can write network/cache state; the checker verifies prepared
bytes without those writes. Mock transport checks do not prove a live connector.
An authorized live transport check must retain independent original-byte retrieval,
hash verification, recovery observations and task-owned cleanup results.

New work uses the latest tested `stable` release and checker/unit contracts 3/3.
Existing 2/2 stays conservative until owner-reviewed adoption of per-check inputs
and reuse. Opt-in 4/4 adds reviewed acceptance of sufficiently evidenced original
observations. Read version 1 only for import/audit, then migrate and assess genuine
legacy evidence on authorized resume; execute unresolved or fresh-only checks.
Do not ask users to choose a contract version.
Read-only requests remain read-only. Preserve code, documents, exact original
observations, source and approval bindings, and existing permission scope. Missing
history or stale permission blocks the affected action rather than authorizing a
rebuild or inventing approval. Installation itself never scans or migrates projects.
A successful migration or metadata repair does not execute product checks. Use
[manifest guidance](../skills/to-sdd-pipeline/references/manifest-contract.md) and
[acceptance rules](../skills/to-sdd-pipeline/references/unit-execution-contract.md)
for owner review and revalidation.

For browser tasks, close task-created sessions and helpers. Verify ownership and
lack of active use before deleting each task-created temporary profile. Preserve
unrelated browser state and requested evidence.

## Report results

Record the source revision and hashes, files reviewed, confirmed findings,
changes, commands, outcomes, skips and unresolved limits. Preserve failed first
outputs and corrected versions. Distinguish deterministic fixtures, independent
source review, agent authoring exercises and actual product execution. None can
be reported as a different evidence class.
