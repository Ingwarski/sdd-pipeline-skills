# Begin-generation catalog reuse

The development baseline is `3f38fc87ba15999bed13fe9e8e03ad16b5f1824c` on
`codex/fix-evidence-recovery`. Installed v5 and the active product runtime are
outside this change. Included usage was verified at 67%, with ordinary usage
allowed. The requested sol/high profile is inherited, not independently verified.

## Scope and lock order

The existing `begin_generation` first calls `assert_generation_authority`, which
loads the catalog before recovery and again after recovery. Begin then loads the
same catalog a third time under its publication lock. A real isolated fixture
measured three `_catalog` calls before this edit.

Extract a private `_generation_catalog` context manager. Keep the initial catalog,
fresh authority read, local producer recovery, and any automatic intent settlement
outside its final catalog lock. After those steps, acquire the existing catalog
lock, load the final catalog, reconcile the ledger, validate generation readiness
and unresolved intents, and yield that catalog while retaining the lock. Begin
publishes the yielded value directly. The public authority method consumes the
same context and preserves its existing result shape.

This removes only the third catalog pass. It does not hold a new catalog lock
across producer shutdown. The final lock follows existing catalog-to-accounting
order, also used by settlement/publication. The reentrant thread lock and existing
process coordinator lock remain the only catalog locks.

## Preserved checks

No persistent cache or new trust in provider object ID/size is introduced. Both
remaining full catalog loads still enumerate complete membership, stat original
objects for admission, independently retrieve and hash authority/root/index JSON,
validate every segment and quarantine, and count retained roots/indexes/packs.
Readiness, unknown producer/intents, full holds/floors, policy/capacity limits,
immutable upload checkpoints/readback and `_publish`'s fresh root-key concurrency
check remain intact. Recovered publications are seen by the mandatory final load.
No catalog value is returned for reuse outside the context's lock lifetime.

For a healthy connected-host topology with nine roots, nine indexes, nine latest
root segments, one authority and one registered pack, with complete one-page
listings and no recovery settlements/retries, the source-derived estimate drops
from 297 to 210 native Drive calls per begin. This is not a live measurement.
Constructor capabilities are separate. Authority and metadata are deliberately
not further memoized in this bounded change.

## Verification plan and limits

Use isolated real local stores to measure two catalog loads and verify publication
occurs inside the same lock as final readiness. Exercise a second begin for fresh
validation, changed roots before publication, changed original index bytes,
recovery publication visibility, authority rejection, unknown recovery/intent
preservation and capacity rejection. Retain existing producer-manager tests and
run the adjacent manager/quarantine/accounting families. Root owns independent
review, consolidated suites, Git, installation and later live verification.

No live Drive, private ledger, product/browser runtime or installed-source writes
are authorized or performed by this change.
