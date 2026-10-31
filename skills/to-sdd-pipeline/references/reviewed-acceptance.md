# Reviewing preserved execution evidence

Reviewing legacy or contextless execution requires matched contract **4/4**.
New ordinary work stays 3/3; existing 2/2 and 3/3 history keeps its meaning. Owners
adopt the new semantics during authorized reconciliation; installation changes no
project. The [completion contract](completion-preservation.md) still governs normal
contexts, attempts, completions, authority, sequencing and release.

## Decision and evidence

A review creates a **current-time acceptance decision**. The helper records its
first `recorded_at`; gates use that time, retaining the owner's `reviewed_at`
separately. It preserves original
check outcomes, execution dates, run IDs, source bindings and any procedural gap.
It never creates a pre-start context, backdates permission or marks an interrupted
run completed. Report recorded run status separately from current acceptance.

QA reviews original actions, assertions, coverage, dependencies and evidence; DoD
reviews admissibility, freshness and required historical preconditions. Planning
reviews allocation and the complete relevant input inventory. Retain original
authority as recorded or unknown. Technical acceptance does not certify historical
workflow authorization; current permission independently controls new work.

Each reusable check needs:

- A genuine passed observation, executor, run identity, actual chronology and
  readable evidence of the required class. Components cannot satisfy integration.
- Original authored definitions and observed implementation/test/configuration
  inputs. File hashes can establish files; unknown tree membership cannot establish
  a tree. An inventory written today is not proof of earlier execution.
- Original runtime facts matching required identities, established by a preserved
  pipeline observation or equivalent native execution evidence. A reviewer's
  recollection or a new probe cannot supply an unknown historical environment.
- Current applicable definitions, inputs and prerequisite acceptance; original
  prerequisite facts must precede the consumer's actual observation. Shared inputs
  and uncertain dependencies retain conservative invalidation.
- Current owner-reviewed deterministic reuse eligibility, with no original or
  current fresh-only/live-provider obligation. A metadata review cannot change
  assertions or waive freshness.
- No unresolved blocking findings or later contradictory failure on the same
  claim. Keep failures and charges even when later valid evidence resolves them.
  An undated failure needs fresh proof after a trustworthy immutable known-by
  bound; its original execution date remains unknown.

Identify prose-only historical preconditions in `review.preconditions`, mapping
each reviewed check ID to a list (explicitly empty when none apply). Each item
records `source_ref`, `observation_ref`, `observed_at` and `status` (`established` or
`unknown`). Preserve the requirement and actual proof; unknown essential facts
leave that check unresolved. Use canonical QA prerequisite checks for executable
dependencies instead of duplicating them here. Hash/reference/time validation
establishes integrity and consistency, not authentic execution, reviewer identity,
semantic completeness or real consent. Those remain accountable owner judgments
based on retained evidence; confidence alone cannot fill missing facts.

Original checks retain `runtime_observation_ref`: a pipeline runtime receipt or an
immutable `external_runtime_observation` version 1 record with `unit_id`, `run_id`,
`environment`, `observed_at` and `evidence`. Its evidence references must belong to
the original check. At least one original JSON evidence payload, at its top level
or `runtime` object, must contain those exact runtime identity/time values. A new
envelope may describe retained native facts; it cannot manufacture them.
Precondition references use `{path, content_hash}` or supported managed evidence
references; their native JSON evidence must establish the stated `observed_at`,
no later than the original check. Unknown requirements/proof remain unresolved.

`review.reuse_eligibility` maps check IDs to `deterministic_isolated`. This can
establish eligibility where legacy/current definitions omitted reuse policy,
without changing their assertions. It cannot override explicit fresh/live policy.
Absent per-check dependency review retains whole-unit inputs; adopting 4/4 alone
does not require rewriting QA or narrowing its original selections.

## Records and procedure

Use Python 3.12+ and `scripts/sdd_history.py --project PROJECT`. Global
`--manifest candidate.json` and optional `--evidence-cache CACHE` precede commands.
Reference arguments are JSON files containing `{path, content_hash}`, not envelopes.

1. Stop/checkpoint relevant producers and retain actual records. Preserve failed
   attempts, accounting, charges and reservations. Read-only inspection permits no
   adoption. For version 1, first use existing `adopt-legacy`, inspect its conversion
   report and activate the retained archive; this grants no acceptance.
2. Prepare a separate 4/4 candidate, changing no original runs, checks, history,
   obligations or authority. Reconcile necessary QA policy through its owner.
   Use a retained `legacy_execution_archive` as `source_kind: legacy_archive`.
   Otherwise import supplied actual observation records as
   `source_kind: external_observations`; retain `imported_at` separately from
   execution dates. Never manufacture a passed source manifest or missing context.
   Use `import-observations --unit UNIT-01 --source-manifest observations.json`;
   save the returned source reference. The input retains original plan/definitions,
   run facts and observed checks, with references to actual supporting bytes.
3. Retain an immutable original prepared inventory established from preserved
   original bytes and facts. Review current inputs through the existing inventory
   schema. Missing original proof requires targeted execution, not substitution
   with current hashes or a narrower retrospective inventory.
   Use `prepare-original-inventory --unit UNIT-01 --source-kind legacy_archive
   --source-ref source-ref.json --inventory original-review.json` (choose
   `external_observations` for that source). It prepares retained bytes, not today's
   implementation, and returns `original_inventory_ref`; it grants no acceptance.
4. Capture a review with this request structure:

   ```json
   {
     "unit_id": "UNIT-01",
     "source_kind": "legacy_archive",
     "source_ref": {"path": "...", "content_hash": "..."},
     "original_inventory_ref": {"path": "...", "content_hash": "..."},
     "current_inventory": {},
     "review": {
       "complete": true, "reviewer": "concern owners",
       "reviewed_at": "actual current review time", "rationale": "source-backed review",
       "preconditions": {"QA-01": []},
       "reuse_eligibility": {"QA-01": "deterministic_isolated"}
     },
     "procedural_gaps": ["missing_registered_prestart_context"]
   }
   ```

   The helper computes decisions from actual evidence, never template labels. It stores a distinct
   `reviewed_unit_acceptance` version 1 record and retains authority-at-review for
   audit without interpreting it as original authorization.
   Run `--manifest candidate.json capture-review --request review.json` and save
   its returned reference. Preserve the request for identical retries.
5. Append the returned reference to `reviewed_acceptance[unit_id]` in the candidate.
   Retain every previous reference. Use standard `stage` and `activate` with the
   unchanged expected active manifest hash. Changed source/evidence/authority or a
   competing writer requires fresh staging/review. Interrupted activation uses the
   existing recovery journal; never delete another writer's lock.
   Run `stage --candidate candidate.json --expected-manifest-hash SHA`, then
   `activate --candidate-ref candidate-ref.json --expected-manifest-hash SHA`.
   Inspect both reports. `recover --journal-ref journal-ref.json` reads transaction
   state without overwriting a conflicting active manifest.
6. Recheck current acceptance and permission. Only the latest indexed review is
   active; no fallback to an older apparent pass. The common resolver closes
   prerequisite dependencies before prerequisites, progress, completion, security
   or release consume its result. Adequate partial results remain available while
   unresolved/fresh-only checks remain pending. Every required integration/release
   gate must still pass; sufficiently evidenced deterministic checks may qualify.

Keep the same request timestamp and input identities when retrying an identical
review. Imports/reviews share immutable snapshots and return the same verified
record; activation retry reports the transaction result, never a fresh acceptance
pass. Ordinary gates recompute current applicability, use prepared evidence and
emit bounded summaries with retained-record references. They neither download
archives nor write journals. Managed evidence retains original accounting and
dependency closure; inactive-history deferral cannot hide accepted dependencies.

For a partially reviewed contextless running/blocked attempt, retain its exact
original run and owned checks in the immutable source. Prepare a separate fresh
pending candidate retaining the review, original findings and all history. Use
`--manifest candidate.json capture-context --unit UNIT-01 --inventory fresh.json
--reviewed-prior-ref review-ref.json`, index the returned context, then stage and
activate. This narrow 4/4 transition requires an exact retained source match and
no existing original context/attempt/completion; normal interrupted runs use
`capture-continuation`. Record a distinct actual run ID after the normal start
gate. Neither route relabels the old attempt or clears accounting.

For subsequent execution, use current authorization, context capture and start
checks. Rerun only unresolved or affected checks where scoped dependency
proof supports it; broaden when relevance is unknown. A format upgrade alone
does not require code reconstruction or replay of adequately evidenced unchanged
checks. This pipeline change never completes a product unit by itself.
