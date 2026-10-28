# Preserved producer gaps and scoped accounting

Read before quarantining unknown producer history or issuing scoped accounting. Ordinary complete-history storage uses the parent contract unchanged.

An interrupted producer can lose sampled write history even after its surviving
files and helpers are preserved. Never infer missing gross generation from final
file sizes, a reservation or later cleanup. Original failed runs, uncertainty,
full pending holds, known charges and retry ordinals remain unchanged.

The supported explicit producer-quarantine operation can isolate such a gap only
with the original intact ledger and recovery journal, exact inactive producer
identities, verified current output and resource disposition, and an immutable
descriptor bound to the original attempt, reservation, run, policy and intent.
External helper disposition requires a named, hash-bound operator assertion;
the engine does not authenticate facts outside its managed ownership records.
Missing/corrupt history, changed bindings, active/unknown ownership and unrelated
recovery causes still block generation. Quarantine is not historical accounting
recovery, a successful run, a budget refund or acceptance. Cold catalog recovery
retains the gap and full holds but cannot grant fresh generation authority.

After verified isolation, fresh distinct runs may use the unchanged cumulative
limits: admission adds all known charges and full historical pending holds.
Those sums remain lower bounds; neither admission nor quarantine proves a
physical upper bound on missing historical writes. Version 2 accounting receipts
(`kind: scoped-known-generation`) disclose `accounting_complete: false`,
`incomplete: true`, `history_complete: false`, `totals_are_lower_bounds: true`,
the preserved quarantine descriptors and unsettled intents. Their explicitly
complete selected scope contains only independently complete known runs, with
zero pending reservations or unreconciled outputs. All currently required
references and prerequisites must belong to that scope and retain their original
bindings. A failed quarantined run cannot support acceptance. Version 1 explicit
incomplete receipts remain rejected; old checkers reject version 2. This scope
does not alter product QA, DoD, execution permission or release gates.

## Explicit device current custody

An already quarantined output can require a distinct, explicit current-custody
operation when its device number changes. This does not satisfy the original
device identity predicate. Matching recorded inodes, paths and hashes across
devices does not prove the same volume, original physical object, uninterrupted
custody, historical ownership, or historical absence of empty directories.
All those historical unknowns remain. The original descriptor and failed run
remain unchanged, incomplete and unusable for acceptance.

`Manager.revalidate_quarantine_device(attempt_id, assertion_ref,
operation_id=UUID, dry_run=True)` requires the designated original coordinator,
intact original ledger/session/journal/checkpoints, the independently published
original descriptor and exact unresolved intent. `assertion_ref` contains the
absolute `path` and original-byte `sha256` of a named assertion JSON file. The
CLI is `revalidate-quarantine-device --attempt-id ID --assertion PATH
--assertion-sha256 SHA --operation-id UUID [--apply]`. It never runs automatically
from setup, installation, recovery or generation. Dry run writes no witness,
historical checkpoint or publication; normal existing SDK constructor and
reconciliation metadata writes can still occur.

This operation is POSIX only. Current output must be the original absolute
session path, with the recorded root inode and exactly the recorded flat regular
file entries, inodes, names, sizes and SHA-256 values. Only one uniform device
substitution is allowed. Root mode must be `0700`; each file must have mode
`0600`, one hard link and current OS user ownership. Links, linked parents,
directories including empty ones, mount roots and special files reject. Stable
open handles, pre/post metadata, complete inventory and repeated original owner,
group, registered-resource and observed-writer disposition checks are required.
The explicit assertion and OS observations retain authentication and final
check/use race limits; they do not exclude arbitrary external writers.

Assertion schema version 1 has kind
`quarantine-device-current-custody-assertion`: operation, project, store, ledger,
attempt, reservation and intent IDs; original descriptor/record/policy digests;
current policy and coordinator-authority digests; original root path;
`old_view`, `new_view`, named `verifier`, timezone-aware `observed_at`, explicit
`limitations`, and purpose `retain-quarantined-gap-for-fresh-distinct-runs`.
`old_view` contains the exact descriptor root identity, inventory and inventory
digest. `new_view.root` contains identity, UID, permission bits and nanosecond
mtime/ctime; `new_view.files` is the sorted complete inventory with identity,
size, SHA-256, UID, permission bits, link count and nanosecond mtime/ctime.
Unknown fields, bool amounts, nonfinite values and rebinding reject. The witness
embeds the assertion payload, original-byte reference, and a separate canonical
payload SHA-256; whitespace changes to the named file therefore remain detectable.
Pure validators consume the caller's already validated normalized policy and
declared bytes only. They never authenticate the operator or inspect live paths.

Apply freezes the first persisted witness timestamp and digest. It writes one
immutable no-clobber recovery sidecar before a dedicated insert-only
`producer_quarantine_device_witnesses` row, then independently publishes and
reloads `generation_quarantine_device_witnesses`. Normal capacity reservations
cover cumulative assertion, witness, SQL/WAL, staging, catalog/index/root and
readback peaks within unchanged limits. Durable occupancy and interrupted files
remain charged; original generation charges and pending holds never decrease.
Same-operation retries must use the exact frozen assertion/candidate. Sidecar-only
retry can complete that candidate; missing/corrupt sidecars, published-only state,
conflicts and forks block. Unknown publication outcomes reload the independent
catalog first. An already complete repeated operation adds no catalog sequence.
Only one direct original-to-current witness exists: no replacements, chains or
second device are supported. Cold recovery exports audit bytes but never creates
authoritative local witness state or producer authority from a catalog witness.

Once any local or published witness exists, exact row/sidecar/published equality
and fresh native validation are mandatory even if the original device returns.
To establish whether a remote witness exists, **any quarantined history now
requires fresh Manager coverage for native admission/completion and global
readiness**. A raw Accounting object or direct producer without that source cannot
grant readiness. Pass `manager=manager` and the original `intent_id` to
`run_producer`; ordinary no-quarantine calls retain their interface and behavior.
Manager recovery obtains its own fresh coverage. Guardian launch and completion
request separate bounded checks over an anonymous parent channel; EOF,
cancellation, mismatch, replay and deadline expiration reject. The Manager's
short catalog check has one finite total deadline, capped by the remaining
producer budget; it requires POSIX main-thread execution and rejects an existing
alarm without replacing it. No catalog lock spans producer execution or shutdown.
Quarantined native generation currently fails closed on non-POSIX even for
ordinary strict quarantines without a device witness. Ordinary no-quarantine
generation and portable receipt versions 1/2 are unaffected; this does not claim
Windows qualification of the new current-custody or guardian publication path.
Network coverage precedes SQLite write transactions; inside each transaction the
same response and current local/native bindings are checked again.

Witness-dependent accounting uses version 3,
`kind: scoped-known-generation-with-device-custody`, with every used witness and
its root key, sequence, immutable segment SHA-256 and witness digest. All version
2 known-scope, reference and prerequisite rules and honest incomplete/lower-bound
flags remain mandatory. Version 1/2 schemas and meanings are unchanged. Manager
holds current catalog authority through receipt assembly and caller emission via
`with manager.accounting_receipt_snapshot(policy_sha256) as receipt:`. The CLI
emits within that context and returns success only for a complete selected scope.
Old checkers reject version 3. Portable validation checks declared closure, never
live custody, exclusive writers, authenticated human approval or product QA.

