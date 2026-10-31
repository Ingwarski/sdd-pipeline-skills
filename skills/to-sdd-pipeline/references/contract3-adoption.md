# Adopting checker/unit contract 3

Use only when reconciling an existing 2/2 project on authorized resume. Installation
does not migrate projects. Use Python 3.12+ and `scripts/sdd_history.py --project
PROJECT`; put optional `--manifest candidate.json` and `--evidence-cache PATH`
before the command. Reference arguments contain returned references, not envelopes.

1. Retain the active manifest and its exact SHA-256. Prepare a separate candidate
   setting **both** contract versions to 3. Preserve identities, obligations,
   source/history references, findings and authority. QA reviews dependency closure
   and reuse policy; no review means whole-unit inputs. A version-only adoption
   need not change existing acceptance definitions.
2. Handle actual execution state:

   | State | Candidate preparation |
   |---|---|
   | Pending, never started | Keep checks unrun. Review per-check inputs through QA and reconcile its canonical sources. Replace any unused context with a fresh candidate context; retain old bytes without inventing an attempt. |
   | Running/interrupted | Capture the exact original 2/2 attempt first. Keep its definitions unchanged; observe fresh runtime and inventory, then use the 3/3 candidate with `capture-continuation --unit ID --attempt-ref REF --run-id NEW_ID --inventory REVIEW`. Save the returned manifest as the candidate. Old unsealed results become `not_run`; never create retrospective seals. If definitions must change, use owner reconciliation; do not disguise the change as continuation. |
   | Completed | For each original completion use the candidate with `assess --completion-ref REF --inventory REVIEW --pending-map MAP`; index the returned applicability reference. Unchanged whole-unit inputs can remain applicable. New dependency reviews, definitions or inputs can require revalidation. Preserve original completion references/bytes; follow [completion preservation](completion-preservation.md) for explicit revalidation. |

3. Reconcile current progress, then `stage --candidate candidate.json
   --expected-manifest-hash SHA [--pending-map MAP]`. Inspect the report and retain
   the returned reference. `activate --candidate-ref REF --expected-manifest-hash
   SHA` requires unchanged active/source/evidence bytes; drift requires fresh review
   and staging. `adopt-legacy` handles 1→2, not this transition.
4. Verify current applicability and implementation authority after activation.
   Plan validation may pass while old completion needs revalidation. Capture new
   contexts where required, pass the checker's `--start-unit ID`, and execute missing/stale
   checks before completion. Adoption itself provides no execution evidence.
