# Browser evidence workflow

Use when source-defined prototype or product checks need a browser. Other
platforms retain their own adapters and checks; this recipe adds no browser,
timekeeping, background-recovery or visual requirement to a project. QA defines
the expected outcomes; these probes establish prerequisites and preserve
observations. They do not grant acceptance or implementation permission.

## Prepare the actual run

1. Resolve the project, real skill directory, scripts, executable and output
   paths to absolute paths. Read the producer's CLI before launch. The managed
   `evidence_store.py run` executes its argv **from the registered output
   directory**, not the project or script directory. The producer must resolve
   assets relative to its own known source root or accept explicit absolute paths.
2. Configure storage and reserve the measured capture/log/cache/staging/readback
   allowance before writes. Create an empty, real external output directory.
   Keep the browser profile, sockets, locks, crash files and temporary runtime
   tree outside it. Runtime files can be links or special files; an evidence
   inventory accepts stable regular bytes.
3. Record the exact browser/automation/OS/runtime identities required by the
   execution context. Query the **running browser used for capture**, for example
   `browser.version()` or CDP `Browser.getVersion`, plus the actual adapter
   package/runtime and owned process executable identity. An installed bundle's
   version, launch request or browser executable found on PATH is not proof of
   which browser answered. Compare to the captured context before evidence
   execution and again when a session is replaced or reconnected.
4. Register owned producers/helpers through the existing managed producer
   contract. Ordinary children stay in its process group/Job; Python producers
   can use `evidence.producer_runtime.spawn_managed(argv)`. Keep the handle and
   wait for exit. Do not detach an unregistered browser/server to survive the
   producer. Record exact PID plus creation identity, task/run, profile path,
   resolved user temp root and every separately created IPC path as they appear.

On supported Darwin hosts, the SDK's optional observed-writer adapter uses an
opt-in version-2 producer session and a protected direct-child observer. A
pre-exec gate registers the exact native browser root before launch continues;
the observer retains kernel birth, unique-ID and original-parent observations
for detached helpers. Submitted process listings or caller-authored witness JSON
cannot establish membership. Detached observations confer no signaling authority.
Missing ancestry, lost acknowledgments, observer loss or unresolved candidates
remain durable obligations for finalization and recovery. Keep the separate
working-capacity hold active through native process/handle checks, exact cleanup
and the final closed acknowledgment. A pre-cleanup acknowledgment permits only
verified owned cleanup; it does not establish final closure or acceptance. The
adapter is optional and platform-specific; ordinary managed children and other
hosts retain their existing process-group/Job contract.

The evidence reservation measures registered generation. Browser-profile
occupancy and OS temporary writes require separate capacity planning and
monitoring. A sampled peak is neither total bytes written nor a hard disk quota;
the evidence wrapper is not an OS sandbox. Do not report runtime writes as
covered merely because the capture output stayed under its allowance. Budget
exhaustion stops the affected producer and preserves an incomplete attempt.

## Isolate fixtures and observe prerequisites

Keep deterministic fixture/emulated time in a separate browser **context** from
native-time checks. A new page in the same context is insufficient: Playwright's
[clock applies across that context](https://playwright.dev/docs/api/class-clock).
Record each context's role, fixture values and emulation settings. Create native
contexts fresh and never apply clock emulation there.

For actual-time claims, bracket each browser epoch sample with independent host
wall-time reads and demonstrate advancement over multiple samples. Keep host
and browser on the same clock source/host for this comparison, or define the
justified clock-skew allowance explicitly. Preserve the raw brackets and chosen
allowance. This is a consistency check: emulation tracking host time can satisfy
it, so context isolation and runtime provenance remain required. The sampling
interval and skew allowance are harness parameters, not product performance
thresholds.

For a required hidden → visible recovery check, attach a real
`visibilitychange` observer before the trigger. Record initial visibility,
browser-generated event states, times and `isTrusted`, the observed hidden
interval, restoration to visible, and the product's first required response
after restoration. Establish the hidden prerequisite before evaluating recovery.
Observe the response specified by QA; current final content alone does not prove
that recovery occurred. Do not dispatch synthetic events, override
`document.visibilityState`, or infer success from the action name or screenshot
filename. Apply the same prerequisite/action/outcome distinction to other
source-defined state transitions.

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

The runtime command returns the connected browser's version, actual adapter
version and Node version as JSON stdout. Include that exact command under a
stable key such as `browser_session` in the native history tool's `--probes`
file. `observe-runtime` preserves stdout as that key's environment value; put
its returned `runtime_observation_ref` and identical environment map in the
reviewed inventory. Do not replace it with a guessed or independently formatted
version string. For the example's `--expected` file, parse the **original
captured** `browser_session` JSON value into an object, preserving all three
browser/automation/Node identities; keep that file outside
the managed output directory. A fresh observation cannot silently replace the
expected original.

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

The example's JSON is prerequisite evidence, not product checks, a visual review
receipt or an SDD runtime schema. It does not establish supported-browser
coverage, layout conformity, delivery, representative-user validation or
successful product recovery. Run the source-defined checks and review under the
existing [verification contract](verification-contract.md); approved design
values, exceptions and visual acceptance boundaries remain unchanged.

## Settle, preserve and approve

Use this order for formal candidate evidence:

1. Show the live candidates on the selected review surface and perform the
   applicable interaction/visual review. Record **review observed** with the
   actual candidate/version, URL, scope and time.
2. Finish captures/logs. In `finally`, close created contexts so their artifacts
   flush, disconnect/close owned browsers appropriately, stop owned servers and
   helpers, and wait for process exit. An attached
   [Playwright browser connection](https://playwright.dev/docs/api/class-browser#browser-close)
   can disconnect while the underlying process remains; verify the process.
3. Reconcile every producer output and close the coordinated evidence run.
   Archive stable bytes by copying the producer's returned `output_id` into the
   archive spec's `managed_output_id`; prepare the referenced bytes and
   dependencies into the external checker cache.
4. Validate candidates and their original review receipts against the prepared
   evidence. Preserve failures and fix their actual cause before a new attempt.
5. Only then request/record the later whole-design approval of the exact
   validated candidate/version. Live review and approval are different events.
   If another interactive review is needed, reopen the unchanged candidate on
   its stable route and record the new session. Do not describe closed pages as
   currently live or keep evidence unsettled while waiting for approval.

For archive specs, `evidence-json-v1` requires a top-level JSON object. A valid
top-level array may be stored unchanged as `evidence-bytes-v1`; do not wrap or
rewrite original output just to satisfy an object schema. Choose required typed
schemas for semantic receipt payloads; bytes cannot replace required JSON
receipt semantics. Preserve original failed outputs, byte hashes, times and
bindings. Archive/prepare success proves byte persistence and validation, not
correct product behavior.

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

After graceful close, verify recorded process creation identities have exited;
stop only verified remaining task-owned helpers and wait for them. For each
individual temporary profile, require a real directory owned by the current
user directly inside the resolved user temp folder, with no running process
reference or open handle. Check runtime/IPC paths against their recorded
ownership and permitted parent with the same protections. Never traverse
symlinks or mounted directories during removal. Remove only verified exact
paths, then verify absence. Preserve unrelated profiles, retained persistent
profiles, downloaded browser binaries and requested deliverables.

Unknown ownership, an in-use path or a failed removal stays in place and is
reported with its exact path and reason. No wildcard deletion, broad temp
cleanup or stopping another task's processes. Storage cleanup does not replace
the applicable project/host browser cleanup rules.
