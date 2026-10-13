# Shared SDD Operating Rules

Read before work. All 13 skills ship together. Resolve installed resources from SKILL.md's real directory. Report missing rules; never invent them.

## Sources, ownership and writing

Project sources/decisions define scope; bundled examples/fixtures add requirements only if explicitly adopted. Inspect facts, retain terms/IDs, label assumptions. Context cannot override PRD/design/architecture/quality. Write owned outputs: orchestrator owns `forge/sdd-manifest.json`, operators receipts. Owners reconcile changes; preserve history/progress/approvals/immutable candidates.

Keep test-project details, results and audit/authoring history in separate reports outside reusable instructions; executable fixtures stay isolated.

Return reviewed `source_usage`: path → `"full"`, consumed headings, or `{"unused":"reason"}` for context/optional files. Bind exact scope/terms/evidence sections; omission is not unused. Exclude later results from planning. Recheck repository claims on reuse; record time, command, scoped paths/hashes/absence.

`working_language`: explicit instruction > saved preference > latest substantive message. Localize prose/questions/adapters/labels idiomatically; separate product locales. Retain paths/code/commands/identifiers/names/quotes and approved English IT terms with meanings in `canonical-terms.md`.

State decisions once; cite IDs/sections and local consequences. Start substantial artifacts with a decision/risk summary. Use plain prose; slash compounds only in literal identifiers/paths/code. Keep compact records, localized headings, obligations, assumptions, sources, evidence, risks, authority and justified exclusions. Omit filler/empty sections. Report changes, evidence, risks and next action.

## Security and authority

PRD's OWASP baseline adds no features/authority. Retain security IDs. Changed actors/data/privileges/inputs/integrations/consequential actions return upstream if obligations change; styling alone does not. Never weaken mockup controls or equate documents with security. No automatic scans/paid services.

Ask one material non-inferable foreground question. Give operator choices rationale/recommendation/consequences; research concrete experiences neutrally. Separate assumptions/observations. Silence/playback/timeouts/recommendations give no consent. Otherwise assume reversibly from sources. Materials intake is not approval.

One approval covers integrated design. Obtain risk-specific authority when needed; retain permission. Owners return `baseline_change_required`; accepted corrections are scoped overrides, never self-approval. Stop validated plans at `awaiting-implementation-prompt` until a later explicit implementation request. SDD drives; QA verifies without mandatory TDD.

## Evidence and validation

Produce required observations once; share inventories/environments/original output. Capture required visuals; diagnose selectively and detect repeated failures. Budgets never waive evidence. Clean task-owned browsers/profiles under AGENTS.md.

Git keeps compact results/receipts; storage keeps payloads/history. Read [storage](evidence-storage-contract.md) for capture/archive/prepare/import/cleanup only. Missing/corrupt evidence blocks claims; storage never reruns/refreshes checks.

Apply [scope/execution](scope-and-execution.md); confirm headless UI exclusions. Product idea/PRD/screen map/QA/plan return [traceability](traceability-contract.md); others reuse IDs. Read full instructions, selective sources; reload rules after compaction/version changes.

Only required-before inputs create dependencies. Validate obligations/owners/terms/states/evidence/gaps. Parent IDs do not prove clause coverage; document review is not product testing. Return paths/invocation/independent results/hashes/consumed bindings/observations/decisions/risks. Context shares invocation, not hashes/results. Standalone checks inputs; disclose unavailable orchestration validation. With manifests, check before dispatch/after results.
