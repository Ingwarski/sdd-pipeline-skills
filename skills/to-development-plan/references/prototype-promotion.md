# Traced Prototype Promotion

Read only when an implementation unit reuses prototype presentation code. A mockup is an optional frontend seed, not a production implementation or proof of auth, persistence, backend/API, integrations, security or exhaustive edge cases.

The plan must freeze the approved candidate/version, normalized prototype source root/tree hash and algorithm, production base commit, allowed adaptations, and every missing production capability. Map each selected source path to an explicit production destination and strategy: `copy | adapt | reimplement`. Reuse is bounded by that map, not a blanket copy permission.

For each reuse unit record: source references, Baseline ID/target hash, source root/tree hash, path map, strategy, base commit, permitted variance/adaptations, missing production capabilities, QA check IDs and required receipt path `forge/runs/{unit_id}/{run_id}/prototype-promotion.json`.

Only the separately authorized Phase 3 runner derives the actual Git diff and writes the `PrototypePromotionReceipt`. The plan owner, orchestrator and implementation agent's free-form report cannot fabricate it.

The receipt includes: schema version; promotion/unit/run IDs; development-plan reference/hash; Baseline ID/target hash; candidate/version; prototype source root/tree hash; source/destination mappings and hashes; base/head commits; changed paths/patch hash; adaptations/variances; QA IDs; visual evidence; verification status; timestamp.

After implementation begins, a declared production destination without its receipt, or a receipt strategy that differs from the plan, blocks the applicable fidelity gate. Record the finding for QA/DoD; never reconstruct historical evidence. Existing unrelated files alone are not proof that promotion ran: inspect the unit's declared destinations, source basis and runner state. This later lookup does not make the development plan a prerequisite for preparing QA or DoD.
