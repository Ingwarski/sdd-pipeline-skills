# Shared SDD Operating Rules

Read before work. All 13 skills ship together. Resolve installed resources from SKILL.md's real directory. Report missing rules; never invent them.

## Sources, ownership and writing

Keep coding behaviour in project `AGENTS.md`; keep project-specific authority in guardrails, completion conditions in DoD, check procedures/results in QA, and unit work/dependencies in the plan. Follow the [ownership map](project-instructions.md#one-source-for-each-rule). Do not copy the continuation or pause policy into SDD documents. Missing project instructions do not block standalone document authoring; effective setup and recoverable execution records are required before implementation; use the setup contract for host verification and code-enforcement limits.

Project sources and explicit decisions define scope; bundled examples or fixtures add requirements only when explicitly adopted. Inspect discoverable facts, retain terms and IDs, and label assumptions. Context cannot override PRD, design, architecture or quality. Write only owner outputs: the orchestrator owns `forge/sdd-manifest.json`, narrow project instruction setup and current history indexing/staging under [completion preservation](completion-preservation.md); tool operators own actual receipts. Route changed facts through owners and preserve decisions, progress, approvals, history and immutable candidates.

Keep test-project details, results and audit/authoring history in separate reports outside reusable instructions; executable fixtures stay isolated.

Return reviewed `source_usage`: path → `"full"`, consumed headings, or `{"unused":"reason"}` for context/optional files. Bind exact scope/terms/evidence sections; omission is not unused. Exclude later results from planning. Recheck repository claims on reuse; record time, command, scoped paths/hashes/absence.

`working_language`: explicit instruction > saved preference > latest substantive message. Localize prose/questions/adapters/labels idiomatically; separate product locales. Retain paths/code/commands/identifiers/names/quotes and approved English IT terms with meanings in `canonical-terms.md`.

State decisions once; cite IDs/sections and local consequences. Start substantial artifacts with a decision/risk summary. Use plain prose; slash compounds only in literal identifiers/paths/code. Keep compact records, localized headings, obligations, assumptions, sources, evidence, risks, authority and justified exclusions. Omit filler/empty sections. Report changes, evidence, risks and next action.

## Security and authority

PRD's OWASP baseline adds no features/authority. Retain security IDs. Changed actors/data/privileges/inputs/integrations/consequential actions return upstream if obligations change; styling alone does not. Never weaken mockup controls or equate documents with security. No automatic scans/paid services.

Ask one material non-inferable foreground question. Give operator choices rationale/recommendation/consequences; research concrete experiences neutrally. Separate assumptions/observations. Silence/playback/timeouts/recommendations give no consent. Otherwise assume reversibly from sources. Materials intake is not approval.

One approval covers integrated design. Obtain risk-specific authority when needed; retain permission. Owners return `baseline_change_required`; accepted corrections are scoped overrides, never self-approval. Initial production implementation requires plan validation, the `awaiting-implementation-prompt` pause and a later explicit implementation prompt. For already-authorized documentation corrections, apply the [verified correction exception](authorization-corrections.md); other plan changes require a fresh prompt. SDD determines what to build; QA verifies without mandatory TDD.

## Evidence and validation

Produce required observations once; share inventories/environments/original output. Capture required visuals; diagnose selectively and detect repeated failures. Budgets never waive evidence. Clean task-owned browsers/profiles under AGENTS.md.

Git keeps compact results/receipts; storage keeps payloads/history. Read [storage](evidence-storage-contract.md) for capture/archive/prepare/import/cleanup only. Missing/corrupt evidence blocks claims; storage never reruns/refreshes checks.

## Inputs, validation, and return

Apply [scope/execution](scope-and-execution.md) for profile selection, intake/resume or host changes. Omit UI-only prerequisites only for confirmed headless scope, including standalone work; missing UI files are not an exclusion.

Product-idea, PRD, screen-map, QA and plan return [typed traceability](traceability-contract.md); other owners reuse IDs. Reuse unchanged instructions in context; reload after compaction/version changes. Read required instructions fully, product sources selectively; do not resummarize unchanged documents.

Only **required-before** inputs create dependencies, not optional grounding or later lookups. QA's later development-destination lookup never makes the plan a QA prerequisite.

Validate distinct observable obligations, owner, terminology, applicable states, evidence limits and material gaps. A parent requirement ID is not clause coverage; document validation is not product testing.

Return paths, invocation ID, independent content hashes/results, consumed hashes, scoped observations, changed decisions and risks. The caller records them; the two context outputs share an invocation, not hashes/results.

Standalone owners check canonical inputs directly: do not require/create a manifest, dispatch others or claim pipeline readiness. Report affected downstream artifacts. With a manifest, the caller runs the checker before dispatch and after recording results; without one, perform equivalent checks and disclose unavailable automatic orchestration validation.

Follow applicable project instructions for task-owned browser/profile cleanup.
