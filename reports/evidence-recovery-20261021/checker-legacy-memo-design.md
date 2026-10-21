# Checker-only legacy snapshot validation memo

Baseline: `86ee7763935ce016a9c03b655d2dea2f4d1e3f80`. This change is confined to
development sources and isolated tests. Installed v5/v6 and active product work
remain immutable. Included usage was verified at 67%, ordinary usage allowed;
the requested inherited sol/high settings are not independently verified.

## Contract

A private context manager used only by `Checker.run` opens the existing
`snapshot_hash_scope(audit=True)`. It creates a context-local lease bound to that
checker and owner, invalidates the lease in `finally`, and restores the parent
lease for nested checkers. A copied context cannot revive an expired lease.
Generic scopes, standalone validators and advisory helpers receive no lease.

Only `HistoryView.resolve` may reuse legacy frozen-file validation. Every visit
still freshly reads and hashes the exact legacy reference, checks its event,
version and nonaccepting status, and freshly reads/validates its original manifest
reference. Reuse binds canonical project namespace, exact reference path/hash,
the complete semantic record digest and the original registered snapshot entries.
An altered record or missing/changed registration requires full validation.

The first visit runs unchanged `validate_files`, registering every frozen file.
Reuse still checks every current logical path through `physical`; these guards
are distinct from the frozen paths registered in the hash owner. Existing
checker-return and outer-scope audits continue to freshly inspect the entire
frozen-file union, including unused files and exceptions. Memo entries are cleared
with all other owner state at outer exit. No persistent cache is created.

## Writing and public-flow boundaries

Generic `validate_files`, `read_ref` and migration `validate_transition` remain
unchanged. In particular, transition validation cannot turn a missing snapshot
into a tolerated blocked migration report, even when stage/activation is called
inside an existing owner scope. Capture continuation audits preflight before
hardlink writes; capture context/completion/attempt retain their checker audit
before snapshot writes and fresh post-write validation. Standalone context,
attempt/completion and historical checker reads keep existing audit scopes.

The memo changes only redundant frozen validation within audited Checker bodies.
It does not remove current containment guards, reference SHA checks, direct
transition errors, per-child or outer audits, hash comparisons, Windows descriptor
guards, acceptance requirements, or write-phase cache invalidation.

## Planned verification

Use synthetic legacy records/local fixture projects only: repeated/nested checker
visits reduce full validation; root invocations stay fresh; arbitrary audit-false
scopes and expired/copied leases cannot reuse; record/namespace/ref/manifest drift,
current logical links and frozen-file mutation reject; child and error exits audit
all files; nested outer-scope stage/activation still throw before writes; existing
hardlink and standalone/history cache tests remain intact. Root owns independent
review, consolidated suites, release and any future install. No live performance
or product acceptance follows from isolated tests.
