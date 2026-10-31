# Evidence lifecycle

Read before enabling automatic cleanup, classifying existing evidence, retiring
an evidence scope or relocating archive packs. Use this mechanism only within the
authorized consuming project. Installing/updating the skillset changes no project
policy, acceptance or storage; developing migration support is not permission to
migrate other projects.

## What remains available

Keep sufficient original proof in the selected durable store: actual results,
required inputs/runtime facts, approvals and necessary visual evidence. A hash or
summary indexes proof; it cannot replace deleted original bytes. Current acceptance,
prerequisites, interrupted work, unresolved findings and supported historical audits
keep their dependencies. Fresh/live duties still require fresh execution.

Generate optional diagnostics only when useful and keep them temporary. When an
investigation needs material, protect it and use the selected durable store if
necessary; local staging/cache must remain bounded. Finish the investigation and
preserve necessary failure/resolution proof before releasing that protection.
Unknown classification stays protected. A new test, elapsed time or an offline
client does not retire a historical audit obligation.

## Adopt without resetting acceptance

Use the bundled `evidence_store.py` lifecycle command help. Adoption requires a
named owner review of the exact project/store and automatic-cleanup scope. Preserve
the portable policy, identities, original records, dates, authority and accounting.
Record scope retirement explicitly; do not infer it from missing files or an old
checkout. No product tests are rerun merely to index or relocate existing evidence.

Register all participating branches/worktrees and producers. Initial discovery
reads current records, retained history and nested evidence references. A normal
gate's visited references alone are incomplete. The derived inventory records why
each item is needed and binds file identities, membership and catalog revisions.
Update affected dependencies after accepted changes; incomplete scope blocks
permanent deletion, not otherwise valid work.

Adoption publishes catalog version 2 so old storage clients cannot mutate/prune
the store. Portable policy version 1 remains unchanged. Do not downgrade after
adoption or discard original archives to make an older tool pass.

## Optional historical diagnostics

Original snapshot membership remains immutable. A separate owner review selects
exact optional members, binding the original record reference, logical path and
content hash with a rationale. `history_integrity.optional_diagnostics_ref` points
to that review. Even an empty review makes the changed contract explicit to old
checkers.

Before activating the selection, compare acceptance and full-audit results with
the selected bytes withheld. Bulk validation and prepared source views may omit
only those members. Direct reads of required proof, inputs or authority stay
strict, including inside full audits. Missing required material remains a blocker.
Report intentional optional omissions separately from bytes actually verified.
The existing `legacy_payloads: audit_only` setting alone permits no deletion.

## Checkpoints and deletion

After adoption, the coordinator computes cleanup candidates at supported managed
checkpoints. It retains required, unresolved, unknown, explicitly retained and
unpublished evidence. Caller-supplied keep-lists or `complete: true` cannot
authorize deletion. Offline participants retain their last dependencies until
explicit retirement; unaccounted scope blocks pruning.

Bind each deletion plan to the current records and catalog. Recheck before apply
and when resuming interrupted cleanup; changed state requires a new decision.
Delete only registered eligible objects in the selected store, verify absence and
record the reason and actual freed bytes. No account-wide trash, arbitrary path
scan or background scheduler. The checker itself remains read-only.

Separate new packs by retention needs. A surviving member keeps a shared pack
alive until verified relocation preserves every required original. Relocation
records new storage separately from immutable evidence identity, verifies new
archive/member bytes and retains old packs on failure. It cannot reset dates,
generation charges, reservations or failures. Report physical savings separately
from logical retirement.

Local cache/original-copy cleanup requires independently verified durable coverage
and no active use. A sole durable local store is not disposable cache. Provider
retention outside SDD remains independent; preserve required provider artifacts
before their expiry.
