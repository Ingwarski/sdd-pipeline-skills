# Shared SDD Operating Rules

Read before owner work. Resolve resources from the loaded SKILL.md's **real directory**, following installed links, never from the product directory. All 13 skills ship together. Missing reference: report its resolved path and repair; never invent replacement rules.

## Sources and ownership

- Product truth comes from sources and explicit user decisions, not AI recommendations. Inspect discoverable facts; preserve terms/IDs and label assumptions or unresolved questions.
- Write only declared owner outputs. Only the orchestrator writes `forge/sdd-manifest.json`; tool operators/adapters own receipts. Return provenance to the caller.
- Context clarifies; it cannot override PRD, design, architecture or quality rules. Read relevant confirmed sections without copying them.
- Record consumed path/hash or exact heading/section hash, including context and QA definitions. Snapshot whole files only when fully relevant; later results are not planning inputs.
- Repository claims need observation date, command, exact paths/hashes, including the command supporting absence. Recheck scoped inputs on reuse, not a whole-repository fingerprint.
- Preserve useful content, decisions, progress, approvals and immutable candidates. Route changed facts to their owner; retain history.

## Language and concise writing

Use `working_language`: explicit instruction > recorded preference > latest substantive user message. Apply it to intake, owners, adapters, questions, displayed statuses, reports and artifact prose. Template headings describe meaning; localize them. Product UI/content locales remain separate.

For Ukrainian (`uk`), use idiomatic language. Retain English only for paths, code, commands, machine values, API identifiers, proper names, quotes and accepted IT terms. `to-project-context` records those terms and Ukrainian meanings in `canonical-terms.md`.

State decisions once at their owner; elsewhere cite the ID/section and local consequence. Use direct sentences, short labels, compact repeated records and brief term explanations. No filler, repeated summaries or empty optional sections. Preserve every distinct obligation, assumption, source, risk, evidence, owner and authorization boundary. Required semantic sections may use existing/localized headings; exclusions need source-backed reasons. Share resolvable scope records rather than repeat route/state/viewport fields. Revision reports cover changes, evidence, risks and next action, not the entire artifact.

## Product security

The PRD's OWASP baseline adds protection within confirmed scope, not new features or authority. Downstream owners preserve security IDs and add local consequences. Changed actors, data, privileges, inputs, integrations or consequential actions return to PRD when obligations change; styling alone does not. Never weaken controls for a mockup or equate document validation with security. No automatic scan or paid service is authorized.

## Questions and autonomy

Ask one question only for a material, non-inferable decision. Operator decisions get a recommendation, source-based rationale and consequences. Behavioral research gets neutral questions about concrete experiences, without suggested answers or assumed feature needs. Distinguish hypotheses from observations; briefly confirm the answer's meaning.

The one-time design-materials request is source intake, not approval.

Use a foreground adapter or active conversation, never logs alone. Silence, timeouts, recommendations and playback are not consent. For non-material gaps, record a minimal reversible source-grounded assumption and continue.

One normal approval covers the integrated design; none is added per document, screen, finding or transition. Request risk-specific authority just in time. Approved-design changes return `baseline_change_required`; owners cannot approve their own changes. An explicit scoped operator correction is an override, not a repeated question.

Production implementation is separate. After plan validation stop at `awaiting-implementation-prompt`; only a later explicit implementation prompt releases it. SDD determines what to build; QA verifies, without mandatory TDD.

## Inputs, validation, and return

Apply [scope/execution](scope-and-execution.md) for profile selection, intake/resume or host changes. Omit UI-only prerequisites only for confirmed headless scope, including standalone work; missing UI files are not an exclusion.

Product-idea, PRD, screen-map, QA and plan return [typed traceability](traceability-contract.md); other owners reuse IDs. Reuse unchanged rules already in context; reload after compaction/version changes. Read required instruction files fully, but only relevant product-source sections. Do not repeatedly summarize unchanged documents.

Only **required-before** inputs create dependencies, not optional grounding or later lookups. QA's later development-destination lookup never makes the plan a QA prerequisite.

Validate distinct observable obligations, owner, terminology, applicable states, evidence limits and material gaps. A parent requirement ID is not clause coverage; document validation is not product testing.

Return paths, invocation ID, independent content hashes/results, consumed hashes, scoped observations, changed decisions and risks. The caller records them; the two context outputs share an invocation, not hashes/results.

Standalone owners check canonical inputs directly: do not require/create a manifest, dispatch others or claim pipeline readiness. Report affected downstream artifacts. With a manifest, the caller runs the checker before dispatch and after recording results; without one, perform equivalent checks and disclose unavailable automatic orchestration validation.
