# Browser evidence workflow

Use for source-defined browser checks; other platforms retain their adapters.
This adds no browser, timekeeping, background-recovery or visual requirements.
QA defines expected outcomes; probes preserve prerequisites/observations, granting neither
acceptance nor implementation permission.

## Prepare the actual run

1. Resolve project, real skill directory, scripts, executable and output to
   absolute paths. Read the producer CLI. `evidence_store.py run` executes argv
   **from the registered output directory**; producers must resolve assets from
   their known source root or accept absolute paths.
2. Configure storage; reserve measured capture/log/cache/staging/readback before
   writes. Create an empty, real external output directory. Keep profiles,
   sockets, locks, crash files and temporary runtime outside: inventories accept
   stable regular bytes, not runtime links or special files.
3. Record context-required browser/automation/OS/runtime identities. Query the
   **capture browser**, e.g. `browser.version()` or CDP `Browser.getVersion`, plus
   actual adapter/runtime and owned executable identity. Installed versions,
   launch requests and PATH do not identify the answering browser. Compare with
   captured context before evidence and after session replacement/reconnection.
4. Register owned producers/helpers through the existing managed producer
   contract. Ordinary children stay in its process group/Job; Python producers
   can use `evidence.producer_runtime.spawn_managed(argv)`. Keep the handle and
   wait for exit. Do not detach an unregistered browser/server to survive the
   producer. Record exact PID plus creation identity, task/run, profile path,
   resolved user temp root and every separately created IPC path as they appear.

On supported Darwin hosts, the optional SDK observed-writer adapter uses opt-in
version-2 sessions, a protected direct-child observer and pre-exec registration
of the exact native browser root. Kernel birth, unique-ID and parent/epoch
observations retain detached membership; process listings/caller witness JSON
cannot establish it. Observation grants no signaling authority. Missing ancestry,
lost acknowledgments/observer and unresolved candidates remain durable recovery
and finalization obligations. Retain separate working-capacity holds through
native process/handle checks, exact cleanup and final closed acknowledgment.
Pre-cleanup acknowledgment permits verified owned cleanup, not closure or
acceptance. Ordinary children/other hosts retain the process-group/Job contract.
Opt-in `observation_scope` widens candidate discovery only to the nearest `.app`
parent; `observe_pid` with `include_image:true` requires a fresh, durably recorded
native root image. Neither supplies missing ancestry or additional authority.
The worker's `--helper-metadata-version 3` enables bounded, deduplicated retries
and nonqualifying helper-image gaps. Check `metadata_version:3` in registration
ACK before GO. FULL graph admission, root-image proof and recovery stay strict;
default 2 and failed legacy records keep their meaning.

Reservations measure registered generation; plan and monitor profile/OS temporary
capacity separately. Sampled peaks measure neither total writes nor hard quotas;
the wrapper is not an OS sandbox. Capture allowance compliance does not cover
runtime writes. Exhaustion stops the affected producer, retaining an incomplete
attempt.

## Isolate fixtures and observe prerequisites

Keep deterministic fixture/emulated time in a separate browser **context** from
native-time checks. A new page in the same context is insufficient: Playwright's
[clock applies across that context](https://playwright.dev/docs/api/class-clock).
Record each context's role, fixture values and emulation settings. Create native
contexts fresh and never apply clock emulation there.

For actual-time claims, bracket each browser epoch sample with independent host
wall-time reads; demonstrate advancement across samples. Use the same clock
source/host or explicitly justify skew allowance; retain raw brackets/allowance.
Host-tracking emulation can pass this consistency check, so context isolation and
runtime provenance remain required. Intervals/skew are harness parameters, not
product performance thresholds.

For required hidden → visible recovery, attach a real `visibilitychange` observer
before triggering. Record initial visibility, browser event states/times/
`isTrusted`, hidden interval, restoration and first QA-required product response.
Establish hidden state before evaluating recovery; final content alone is
insufficient. Never dispatch synthetic events, override `document.visibilityState`
or infer success from action names/screenshots. Preserve this prerequisite/action/
outcome distinction for other source-defined transitions.

Automation may force focus. In the optional Chromium/CDP adapter below,
Playwright 1.60+ supports
[`connectOverCDP(..., {noDefaults: true})`](https://playwright.dev/docs/api/class-browsertype#browser-type-connect-over-cdp).
It avoids focus/media overrides on the existing default context; **new contexts
do not inherit this option**. Use a task-owned local browser and prove its actual
transition. Another CDP session's override call or `bringToFront()` returning is
not transition evidence. If the platform cannot produce the required state,
record that limitation and retain the missing check.

## Optional executable example

[`browser_evidence_example.mjs`](../scripts/browser_evidence_example.mjs) attaches
to an already owned local Chromium endpoint. Start that browser fresh for this
run; its default context must never have used time emulation. The example cannot
authenticate that launch history, so retain the owning producer's record.
It installs no dependencies and starts no browser. It uses an existing
Playwright 1.60+ package, creates a
separate fixed-time context, samples the native default context, and attempts
one real hidden/visible transition. The small
[`browser_evidence_probe.mjs`](../scripts/browser_evidence_probe.mjs) module also
accepts callbacks from other adapters without importing Playwright.

```bash
node /absolute/to-sdd-pipeline/scripts/browser_evidence_example.mjs --help
node /absolute/to-sdd-pipeline/scripts/browser_evidence_example.mjs \
  --playwright-entry /absolute/existing/playwright-core/index.mjs \
  --owned-endpoint http://127.0.0.1:9222 --runtime-only
```

Runtime stdout is JSON identifying the connected browser, actual adapter and Node.
Put the exact command under a stable `--probes` key, e.g. `browser_session`.
`observe-runtime` preserves stdout as that environment value; bind its returned
`runtime_observation_ref` and identical environment map in the reviewed inventory,
without guessed/reformatted versions. Parse the **original captured**
`browser_session` JSON object for `--expected`, preserving all three identities
outside the managed output directory. Fresh observations cannot replace it.

After native context/start gates pass, a producer can invoke the full example:

```bash
python3 /absolute/to-sdd-pipeline/scripts/evidence_store.py run \
  --project /absolute/product --run-id RUN-NEW --unit-id UNIT-ID \
  --output-dir /absolute/external/empty-capture \
  --reserve-bytes 8388608 --reserve-files 20 --timeout 60 --defer-run-completion \
  -- /absolute/node /absolute/to-sdd-pipeline/scripts/browser_evidence_example.mjs \
  --playwright-entry /absolute/existing/playwright-core/index.mjs \
  --owned-endpoint http://127.0.0.1:9222 --url http://127.0.0.1:8080/authorized-route \
  --expected /absolute/external/original-runtime.json \
  --output /absolute/external/empty-capture/probes.json
```

Paths, IDs, URLs and the illustrative 8 MiB/20-file allowance must match the real
authorized run. The browser/server must belong to this managed producer tree or
an active coordinated worker under `--defer-run-completion`; an arbitrary
pre-existing endpoint is not an owned helper. The example closes its own
pages/context and disconnects; its owning coordinator must close the underlying
browser/server and settle all workers before `complete-run`.

Example JSON is prerequisite evidence, not product checks, visual review, an SDD
runtime schema, browser coverage, layout, delivery, representative-user validation
or recovery. Run source-defined checks/review under the
[verification contract](verification-contract.md), preserving approved design,
exceptions and visual acceptance boundaries.

## Settle, preserve and approve

Use this order for formal candidate evidence:

1. Review live candidates on the selected surface for applicable interaction/
   visuals. Record **review observed**: candidate/version, URL, scope and time.
2. Finish captures/logs. In `finally`, close created contexts so their artifacts
   flush, disconnect/close owned browsers appropriately, stop owned servers and
   helpers, and wait for process exit. An attached
   [Playwright browser connection](https://playwright.dev/docs/api/class-browser#browser-close)
   can disconnect while the underlying process remains; verify the process.
3. Reconcile every producer output and close the coordinated evidence run.
   Archive stable bytes by copying the producer's returned `output_id` into the
   archive spec's `managed_output_id`; prepare the referenced bytes and
   dependencies into the external checker cache.
4. Validate candidates/original review receipts against prepared evidence.
   Preserve failures; fix their cause before retrying.
5. Only then request/record the later whole-design approval of the exact
   validated candidate/version. Live review and approval are different events.
   If another interactive review is needed, reopen the unchanged candidate on
   its stable route and record the new session. Do not describe closed pages as
   currently live or keep evidence unsettled while waiting for approval.

`evidence-json-v1` requires a top-level object. Store valid arrays unchanged as
`evidence-bytes-v1`; never rewrite originals for the schema. Required semantic
receipts still need their typed JSON schemas. Preserve failed originals,
hashes/times/bindings. Archive/prepare proves byte persistence/validation only.

## Failed attempts and runtime drift

A producer launcher failure means its tests did not execute. Keep its log,
incomplete storage run and original inputs; a non-active evidence run cannot
accept a new reservation. Use a new bounded evidence run ID under the same
project/unit budgets, retaining the old attempt rather than resetting it.
Storage `reconcile` handles recorded producer/storage recovery; it does not
record SDD qualification history or rerun tests.

For a failed/interrupted implementation attempt, follow
[native attempt recovery](unit-execution-contract.md): capture its actual
outcome with `sdd_history.py capture-attempt`, preserving original context and
results plus current reviewed owner status. Probe the runtime actually to be
used with `observe-runtime`; use `capture-continuation` with the old
`attempt_ref`, distinct new run ID and fresh reviewed inventory. Validate and
activate the returned continuation through the normal start gate **before**
new evidence executes. Keep historical records immutable. Do not call
`capture-completion` for unfinished work or use invented orchestration fields
as validated history.

Changed relevant acceptance definitions still require owner reconciliation and
genuine current qualification. Runtime drift requires a fresh bound continuation
context and a new attempt; never relabel old observations with the new version.
Preserving implemented files or prior permission does not make failed checks
pass. The history contract owns exact command arguments and authorization rules.

## Exact task-owned cleanup

Resolve the user's temp root from `$TMPDIR` or the OS temporary-directory API,
then resolve legitimate root aliases before creating paths (for example macOS
`/var` → `/private/var`). Record every exact task-created profile/runtime path
at creation, including `playwright_chromiumdev_profile-*`. While the browser is
alive, read link metadata without traversal and record separately created IPC
targets outside the profile; a later broken socket link does not reveal its
missing target. Do not discover arbitrary deletion targets by following links.

After graceful close, verify recorded process creation identities exited; stop/wait only
verified task-owned remaining helpers. Each profile must be a real, current-user-owned
directory directly inside resolved user temp, without process references/open
handles. Apply the same protections to runtime/IPC ownership and permitted parent.
Never traverse symlinks/mounts. Delete verified exact paths; verify absence.
Preserve unrelated/persistent profiles, browser binaries and deliverables.

Unknown ownership, an in-use path or a failed removal stays in place and is
reported with its exact path and reason. No wildcard deletion, broad temp
cleanup or stopping another task's processes. Storage cleanup does not replace
the applicable project/host browser cleanup rules.
