# Preserved producer gaps and scoped accounting

Read before quarantining unknown producer history or issuing version 2 scoped accounting. Ordinary complete-history storage uses the parent contract unchanged.

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

