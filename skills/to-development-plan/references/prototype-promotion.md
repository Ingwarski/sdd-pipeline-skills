# Traced Prototype Promotion

Read only when an implementation unit reuses prototype presentation code. A mockup is an optional frontend seed, not a production implementation or proof of auth, persistence, backend/API, integrations, security or exhaustive edge cases.

The plan must freeze the approved candidate/version, normalized prototype source root/tree hash and algorithm, production base commit, allowed adaptations, and every missing production capability. Map each selected source path to an explicit production destination and strategy: `copy | adapt | reimplement`. Reuse is bounded by that map, not a blanket copy permission.

For each reuse unit record: source references, Baseline ID/target hash, source root/tree hash, path map, strategy, base commit, permitted variance/adaptations, missing production capabilities, QA check IDs and required receipt path `forge/runs/{unit_id}/{run_id}/prototype-promotion.json`.

Only the separately authorized Phase 3 runner derives the actual Git diff and writes the `PrototypePromotionReceipt`. The plan owner, orchestrator and implementation agent's free-form report cannot fabricate it.

The receipt includes: schema version; promotion/unit/run IDs; development-plan reference/hash; Baseline ID/target hash; candidate/version; prototype source root/tree hash; source/destination mappings and hashes; base/head commits; changed paths/patch hash; adaptations/variances; QA IDs; visual evidence; verification status; timestamp.

Machine fields: `schema_version: 1`, `promotion_id`, `unit_id`, `run_id`, `development_plan_ref: docs/development-plan.md`, `development_plan_hash`, `baseline_id`, `visual_target_hash`, `candidate_id`, `version`, `prototype_source_root`, `prototype_tree_hash`, `base_commit`, `head_commit`, `changed_paths`, `patch_hash`, `adaptations`, `variances`, `qa_ids`, `visual_evidence`, `verification_status`, `completed_at`. Each path mapping enumerates regular files with `source`, `destination`, `strategy`, `source_hash`, `destination_hash`; expand directories into files. Sources must belong to the frozen render bundle. Record empty adaptations/variances explicitly.

The operational index also preserves the plan's `base_commit` and actual `started_at`. Use full Git commit IDs. The checker requires base → promoted head → current HEAD ancestry, current source/destination bytes matching their hashes, destination bytes matching the promoted commit, real QA IDs, and readable visual evidence. Release requires passing promotion verification and referenced checks. Unrelated later commits are allowed.

Compute `patch_hash` from bytes of `git --literal-pathspecs diff --binary --no-ext-diff --no-textconv BASE HEAD -- DESTINATIONS`, sorting exact destination paths. `changed_paths` is the corresponding scoped `--name-only -z --no-renames` set. This is a promotion-scoped diff, not an assertion that nothing else changed in the repository. Missing Git history or original evidence blocks the provenance claim; never reconstruct it as a historical success.

After implementation begins, a declared production destination without its receipt, or a receipt strategy that differs from the plan, blocks the applicable fidelity gate. Record the finding for QA/DoD; never reconstruct historical evidence. Existing unrelated files alone are not proof that promotion ran: inspect the unit's declared destinations, source basis and runner state. This later lookup does not make the development plan a prerequisite for preparing QA or DoD.
