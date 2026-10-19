# Manifest and Checker Contract

Only the orchestrator writes `forge/sdd-manifest.json`, tracking provenance/progress rather than product decisions. Preserve keys, IDs, history, adapter data and original receipts. Never store secrets.

## Stable records

Keep these existing fields; add verified checker metadata without replacing the manifest:

| Record | Fields |
|---|---|
| Pipeline | `pipeline_version`, `state`, `approved_baseline_id`, `affected_feature_units`, `input_requests`, `pause_reason`, `last_resume_event`, `next_ready_nodes` |
| Language | `working_language`, `selection_source: explicit \| recorded-preference \| latest-user-message`, `artifact_language`, `product_content_locales`, `preserved_english_terms` |
| Product-idea intake | `status: not_started \| awaiting_answer \| ready_to_submit \| handed_off \| superseded`, `intake_id`, `source_mode: seed \| interview \| imported \| existing-file`, `handoff_receipt_path`, `product_idea_hash`, `current_request_id` |
| Artifact | `path`, `owner_skill`, `owner_invocation_id`, `declared_output_set`, `status`, `mission_control_status`, `source_version`, `source_usage`, `source_hashes`, `consumed_source_fragments`, `repository_observation_id`, `dependencies`, `dependency_status`, `content_hash`, `validation`, `open_questions`, `supersedes` |
| Scoped repository observation | `paths`, `commit`, `working_tree_state: clean \| dirty \| unavailable`, `commands`, `observed_at` |
| Design execution | `mode: codex \| claude_design`, `handoff_id`, `state`, `inbox_path`, `transport`, source-manifest and two access/read receipt paths/hashes, three required-source counts, `unresolved_required_source_ids`, `claude_candidate_references`, `selected_candidate_version`, `selection_receipt` |
| Design artifacts | `prototype_candidates`, `prototype_promotions`, `active_baseline` |
| Active baseline | `baseline_id`, target/tree hashes, `hash_algorithm`, `integrity: {status, recorded_hash, observed_hash, checked_at}`, `operator_overrides`, `supersedes` |
| Implementation gate | `state: not_reached \| awaiting_implementation_prompt \| authorized_for_phase3 \| invalidated`, `development_plan_hash`, `approved_baseline_id`, `prompt_id`, `prompt_received_at`, `released_at`, `reason` |

Unset optional values may remain null. Artifact status is `missing | input_needed | ready | running | validated | invalidated | blocked`. Operator projections are `Pending | Input needed | Running | Ready | Needs attention | Approved design | Blocked | Done`: validated maps to Done, invalidated to Needs attention until ready, and blocked to Blocked. An unanswered question is Input needed, not failure or approval; ready means dispatchable. Reserve Approved design for the active whole-design baseline.

Keep machine values; apply shared language rules to displayed labels/prose. Artifact language equals working language; product locales stay independent.

Design states remain `not_started | awaiting_executor_choice | preflighting_source_access | awaiting_design_source_access | generating_candidates | awaiting_claude_design_selection | awaiting_claude_design_export | awaiting_export_transfer | validating_import | awaiting_design_approval | approved_visual_baseline`. Transport is `direct_export | codex_assisted_import | manual_transfer | authorized_url_capture`; follow the handoff reference.

## Current checker metadata

New manifests use `checker_contract_version: 2` and `unit_contract_version: 2`. Version 1 is readable for audit/import, then migrated on authorized resume under [completion preservation](completion-preservation.md); it is not an alternate execution mode. Mixed pairs and version-2 history hidden in version 1 are rejected. [pipeline-contract.json](pipeline-contract.json) defines artifact paths, owners and required-before edges once. Each artifact ID is also an owner node; named reconciliation nodes inherit through `owner_artifact`. Aggregate nodes specify their own inputs. `consulted_later` never creates a scheduling edge.

Also use `traceability_version: 1` and the [typed owner indexes](traceability-contract.md). The [scope/execution contract](scope-and-execution.md) defines source-bound `product_scope`, headless exclusions and direct-host intake persistence. Optional `dispatches` maps owner artifact IDs to `{invocation_id, outputs, source_hashes, consumed_source_fragments}`; returned invocation/output identities and consumed bytes must still match. A stale return is rejected, not silently integrated.

A validated artifact needs:

- canonical path/owner, nonempty owner-invocation ID, `status: validated`, current SHA-256 `content_hash`;
- `dependencies`: required-before artifact IDs; the context-bundle node can expand to both members;
- `validation.result: passed` and `validation.working_language`: a **document** validation, not product test success;
- owner-reviewed `source_usage`: path → `"full"`, nonempty list of exact consumed headings, or `{"unused":"reason"}`. Resolve every required input, including unused context/terms; non-context prerequisites cannot be waived. Include additional consumed files and shared scope/evidence/terminology sections, not only check IDs. The checker verifies declared coverage, not unreported reading;
- `source_hashes`: repository-relative POSIX file paths → SHA-256 for consumed full sources; optional `source_inventory_ref` expands the identical contained map/fragments, rejecting conflicting inline values;
- optional `consumed_source_fragments`: path → list of `{heading, content_hash}`. Use the exact unique Markdown ATX heading and hash its section through the next equal/higher heading; do not also snapshot that whole file;
- after approval, architecture/DoD/QA/plan also need `validated_baseline_id`. No-change revalidation updates metadata without rewriting valid document bytes.

Context artifacts share one invocation/two-path `declared_output_set`, with independent hashes/results. Used sources require full hashes or all declared fragments and a usage decision. Unused context needs a reason, no binding; both artifacts remain current. Consumption adds no scheduling edges.

Repository observations cover only inspected paths and commands. `paths` maps files to hashes, or `null` for observed absence; include commands and timezone-aware observation time. Recheck those paths on reuse. Unobserved claims are invalid; unrelated files never justify a whole-repository invalidation.

Hashes may be raw SHA-256 or `sha256:<hex>`. Project-source paths, including resolved links, stay inside the project. Generated evidence may instead use version 1 [storage references](evidence-storage-contract.md); URLs or arbitrary external source paths never replace hashes. Missing/ambiguous headings and unknown algorithms fail closed. Compute with `--hash PATH [--heading '## Exact heading']`; directories use `sdd-tree-sha256-v1`, include every regular file and reject symlinks/reparse points in or leading to the frozen source root.

## Baseline

`active_baseline` is a projection of the canonical design-brief section, not another approval. Add:

```json
{
  "baseline_id": "B-1",
  "canonical_ref": {"path": "docs/design-brief.md", "heading": "## Approved Visual Baseline"},
  "prototype_source_root": "forge/design/candidates/a/v1",
  "prototype_tree_hash": "actual SHA-256",
  "hash_algorithm": "sdd-tree-sha256-v1",
  "visual_target_path": "forge/design/evidence/target.png",
  "visual_target_hash": "actual SHA-256",
  "approval_receipt": {"path": "actual runtime receipt path", "content_hash": "actual SHA-256"}
}
```

The canonical section references the ID, hashes and receipt identity. `visual_target_ref` replaces the path, retaining `visual_target_hash`; approval receipts accept a direct evidence reference or wrapper. Original semantic/binding checks still apply. The receipt records the original operator event (`approve_design_baseline` or `accepted_scoped_baseline_override`), actor, Baseline ID, target/tree hashes and timezone-aware `approved_at`. Normalize an existing receipt only from its retained original provenance; never invent approval or request it again just to fill metadata.

Recompute frozen hashes; recorded `integrity.status` is not proof. Preserve older versions and supersede explicitly. A changed baseline invalidates affected bindings, production units and prior implementation authorization.

Retain `candidate_id` and `version`. Shared resources use `render_dependencies` and `sdd-render-sha256-v2` under the [freeze algorithm](freeze-contract.md); its aggregate hash binds the declared render bundle to this same approval.

## Candidate and source-access evidence

Follow [candidate requirements](prototype-contract.md) and, for Claude, [handoff requirements](claude-design-handoff.md). Their fuller scope/source/locale/adapter fields remain required.

The active candidate index adds `candidate_id`, `version`, source root/tree hash/algorithm, target path/hash, `preview_url`, `route`, input `source_hashes`, and hash-bound `browser_receipt` / `visual_qa_evidence`. Superseded entries stay in history. If multiple sets exist, record `design_execution.active_candidate_set_id` and each entry's `candidate_set_id`.

Browser/visual receipts bind candidate ID/version, target/tree hashes and preview URL, timezone-aware `observed_at`, actual `result` and findings. `browser_kind` matches `design_execution.review_surface` (default `external_default`). Headless capture is not visible review. Failed observations/open blockers prevent readiness; normalization retains original evidence, never creates execution.

Codex requires three current candidates. Claude requires three unique tool-native reference strings, `selected_candidate_version` matching one, and one normalized candidate with that exact `origin_reference`. No local hashes/receipts are invented for unexported alternatives.

For Claude, normalize the actual records as follows:

- `source_manifest_path/hash`: inventory JSON with the current `language` record and `materials: [{material_id, required, content_hash or capture_id, ...}]`.
- `codex_access_receipt_path/hash` and `claude_source_read_receipt_path/hash`: JSON with `manifest_hash`, one `results` entry per inventory ID, and any `unresolved_material_ids`. Required entries must report `accessible` and `read`, respectively, with the matching content hash/capture ID.
- `required_source_count`, `codex_accessible_required_source_count` and `claude_read_required_source_count` must equal the actual required-ID count; `unresolved_required_source_ids` must be empty.

External payloads use `source_manifest_ref`, `codex_access_receipt_ref` and `claude_source_read_receipt_ref` instead of their path/hash pairs. Browser/visual, promotion, prompt and sequencing receipts accept evidence references too. Before generation, the checker validates these individual records, not just totals. Optional unavailable sources stay explicitly marked; required missing sources block. The design owner/reviewer still verifies that the inventory represents every required source, not a convenient subset.

## Verification index

At plan validation and implementation handoff, use current [unit execution records](unit-execution-contract.md): `unit_contract_version: 2`, with [completion preservation](completion-preservation.md). These retain canonical `unit_plan`, QA check `acceptance`, actual `unit_runs` and optional user `unit_sequence_exceptions`. Missing records require owner-reviewed migration, never inferred completion. The checker enforces them after plan authoring, for implementation/release and plan audits; `--start-unit ID` / `--complete-unit ID` additionally validate transitions under current implementation authorization.

The [security traceability contract](security-contract.md) defines `artifacts.prd.security_review`, downstream `security_coverage`, and the required `product_security_requirements` gate/check mappings. Record only actual owner returns bound to current document hashes. Missing records require assessment/reconciliation through those owners, not a fabricated historical review or a new approval step.

`verification` is a compact projection from QA/DoD owner returns, bound by `source_hashes` to both current documents. Definitions and compact current results stay canonical there; verified references preserve detailed payloads and superseded history.

| Record | Checker fields |
|---|---|
| Verification | `definition_status: prepared`, `release_readiness: not_evaluated \| passed \| blocked`, `source_hashes`, `gates`, `checks` |
| Gate | `gate_id`, `definition_ref: {path, heading}` into DoD, `active`, `required`, `applicability: applicable \| not_applicable`, exclusion rationale, real `check_ids` once QA exists |
| Check | `check_id`, `gate_id`, `definition_ref` into QA, definition/execution statuses, `phase: prototype \| implementation \| both`, scope |
| UI scope | task, user group, route, state, viewport, applicable JOB/UC and heuristic IDs; actual `baseline_id` and `target_hash` after approval |
| Nonvisual interaction scope | Optional `interaction_scope: {kind: "nonvisual", context, rationale}`; apply the canonical [verification scope rules](verification-contract.md#record-shapes). |
| Executed check | executor, timezone-aware `executed_at`, `evidence: [legacy path/hash or version 1 evidence_ref]`, `evaluated_source_hashes` for implementation scope |

References contain declared IDs. H1–H10 combines applicable `heuristic_ids` and `not_applicable_heuristics: {Hn: reason}`, without overlap. All three [verification gates](verification-contract.md#separate-visual-and-interaction-gates) must be present with source-backed applicability, including headless exclusions. Evidence kinds remain `visual`, `heuristic` and `representative_user`; none substitutes for another.

Apply verification membership/coverage rules and retain required finding/evidence fields, including severity, release effect and status. New checks are prepared/not-run. Deferred/unrun required checks cannot permit release. Gate/check applicability agrees. Recheck saved release passes and open blockers; advisory failures remain failed. Superseded definitions/runs belong in history.

## Implementation and promotion

Add `awaiting_at` and hash-bound `prompt_receipt` to the implementation gate. The receipt preserves `event: implementation_prompt`, `role: user`, `intent: start_production_implementation`, original message/ID, received time, current plan hash and Baseline ID. Require `awaiting_at < prompt_received_at <= released_at`; generic continuation cannot release the gate. Natural explicit implementation requests need no magic wording. After a plan change retain old receipts but invalidate their authorization unless the [verified correction contract](authorization-corrections.md) preserves it through `correction_receipts`. Keep original prompt/timestamps; update the current plan binding only with that evidence.

For declared reuse, `prototype_promotions` indexes unit ID, planned `path_mappings: [{source, destination, strategy}]`, receipt path/hash and actual `started_at`. Strategy is `copy | adapt | reimplement`. At release, every planned destination must exist and the receipt must match the current unit/plan/baseline and exact mappings. Require it only once reuse starts or at release, never before initial planning. Retain the fuller [promotion receipt](../../to-development-plan/references/prototype-promotion.md) produced by the runner from the actual Git diff; the checker never reconstructs history.

## Migration and invocation

1. Verify the latest tested tooling, then run `--audit` on an older manifest; retain original documents, code, IDs, history and receipts. Authorized resume includes [record migration and revalidation](completion-preservation.md); a read-only audit does not. Stop active legacy workers before migration.
2. Re-read current sources/evidence. Missing `source_usage` returns to the owner for source review, not automatic conversion of old hashes or blanket unused reasons. Preserve valid document bytes, original receipts and history; only affected owners revalidate.
3. Archive legacy results and genuinely rerun required acceptance before reusing completed work. Missing evidence stays a named blocker. Old `covered` means planned coverage, not passed execution. Preserve exact existing permission; verify its current scope rather than infer or broaden it.
4. Run `--before NODE`; ordinary dispatch requires exit 0. A `migration_required` issue permits bounded owner metadata/source recovery for migration, after archiving originals; it never permits product implementation. Record owner results, then run `--after NODE`. Exit 1 means blocked/invalid input; exit 2 means legacy migration needed. Inspect all issues when migration and defects coexist; a helper's `migration_ready` result is format readiness only, not a passed project check.
5. Use `--before development-plan` after approved architecture/DoD/QA reconciliation; `--before implementation` after the separate prompt; `--before release` only for an actual release evaluation. Candidate evidence is checked after generation and before approval, not required before candidates exist.

Invalid node names list choices. `--audit` reads artifacts without dispatch/write/approval. `--snapshot NODE` proposes unvalidated metadata with context `{"review_required":true}`. Repeat `--consume 'PATH#EXACT HEADING'` for consumed/shared sections or `--consume PATH` for full files; `--unused 'PATH=reason'` records reviewed exclusions. These compute hashes/fragments only; resolve pending decisions through actual reading before owner acceptance. `--hash-render RECORD` hashes render inputs. `--evidence-cache PATH` reads externally prepared bytes; storage performs preparation. The checker needs Python 3.12+, standard library only, and performs no network/cache writes or product tests.

Validation reports include `toolchain`: checker SHA-256 and `sdd-toolchain-sha256-v1` skillset digest (byte-sorted skill-relative paths plus content hashes, each newline-delimited; excludes Python caches and `.DS_Store`). This identifies actual installed source bytes, including uncommitted edits, without requiring Git. Retain reports with source/plan bindings; rerun after toolchain changes. Hashes establish identity, not semantic correctness or independent review.

## External runner boundary

No production runner is supplied. External runners enforce installed-checker exits at node/unit boundaries, persisted completion, active-unit continuation and the implementation pause. Report capability/evidence/validation failures without extra approvals. Validation covers records/bindings/integrity, not semantics, inventory completeness, research authenticity or host compliance.
