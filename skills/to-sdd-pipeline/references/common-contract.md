# Shared SDD Operating Rules

Read this reference before an SDD owner runs. Resolve links from the **real directory of the loaded SKILL.md**, following its installed directory link first, never from the project working directory. All 13 skills ship together. If a required reference is missing, report its resolved path and repair the installation before continuing; do not invent replacement rules.

## Sources and ownership

- Sources and explicit user decisions establish product truth; AI recommendations do not. Inspect discoverable facts before asking. Preserve canonical terms and stable IDs.
- Write only the owner's declared artifact(s). The orchestrator alone writes `forge/sdd-manifest.json`; runtime adapters own their operational receipts. Return provenance to the caller instead of writing another owner's file.
- Context clarifies requirements; it cannot override PRD behavior, design, architecture, or quality rules. Read only relevant confirmed sections. Label reversible assumptions and unresolved questions; never present them as facts.
- Record each consumed source path/hash, or exact Markdown heading/hash for consumed sections, including context and QA definitions. Do not copy source prose. Snapshot a whole file only when all of it affects the result; later run results are not planning inputs.
- For repository claims, record the observation date, command, exact paths and hashes. Recheck those paths on reuse; name the command behind an absence claim. Never use one whole-repository fingerprint.
- Preserve existing useful content, decision history, saved progress, approvals, and immutable candidates. Reconcile changed facts through their owner; do not silently rewrite history.

## Language and concise writing

Use `working_language`: explicit instruction > current recorded preference > latest substantive user message. Pass it through intake, owners, adapters, questions, displayed statuses, reports, and artifact prose. English headings in skill templates describe meaning, not mandatory output text. Product UI/content locales are separate.

For Ukrainian (`uk`), use idiomatic Ukrainian, not literal calques. Keep English only in filenames/paths, code/commands, machine keys/enums, API identifiers, proper names, quotations, and accepted IT terms such as `SDD Pipeline`. `to-project-context` records preserved IT terms and their Ukrainian meanings in `canonical-terms.md`.

For every SDD document and report:

- State each decision once, in its owner's document; elsewhere cite its ID/section and explain only the local consequence.
- Use direct sentences, short labels, compact tables for repeated records, and brief explanations of unfamiliar terms. Avoid filler, repeated summaries, ceremonial sections, and decorative prose.
- Preserve every distinct requirement, assumption, source, obligation, risk, evidence reference, owner, and authorization boundary. Token savings never justify dropping necessary detail.
- Keep required semantic sections; equivalent existing/localized headings are valid. Omit empty optional sections. Use `Not applicable: <source-backed reason>` only where justified.
- Reuse check IDs and shared scope records rather than repeating route/state/viewport metadata. Every linked field must remain resolvable; concision is not ambiguity.
- For revisions, report changes, evidence, open risks, and next action; do not restate the whole artifact. Return omitted optional sections only when that matters to coverage.

## Questions and autonomy

Ask only about a genuinely non-inferable decision that materially changes product scope or a high-risk boundary. Walk one relevant decision branch at a time. Ask one question with a recommended answer, rationale, source basis (or explicit absence), and downstream consequences. After the answer, briefly confirm the decision and consequences.

In pipeline mode return a typed `ProductIntentQuestion` to the foreground intake adapter; do not hide it in logs. Standalone, ask in the conversation. Silence, timeouts, and recommendations are not consent. For non-material gaps, record the smallest reversible source-grounded assumption and continue. Playback is not approval.

There is one normal approval: the complete integrated design. Do not add document, screen, heuristic-finding, or transition approvals. Risk-specific authorization stays just in time. If work would change an approved baseline, return `baseline_change_required`; the owner cannot approve its own change. A source-backed scoped operator correction is an override, not a reason to ask the same question twice.

Production implementation remains outside SDD authoring. After the development plan validates, stop at `awaiting-implementation-prompt`; only a later explicit implementation prompt can release it. SDD determines what to build; QA supplies verification, not a mandatory TDD process.

## Inputs, validation, and return

Each skill distinguishes **required before starting**, **optional grounding**, and **consulted later**. Only required-before inputs create scheduling dependencies. A later QA lookup of development destinations does not make the plan a prerequisite of QA.

Before declaring an artifact valid, check source/requirement coverage at the level of distinct observable obligations, ownership, terminology, applicable states, evidence limits, and unresolved material questions. A parent requirement ID alone is not clause coverage. Validation of a document does not mean the product has been tested.

Return the artifact path(s), owner-invocation ID, independent content hashes and validation results, consumed source/fragment hashes, scoped repository observations, changed decisions, and unresolved risks. The caller records these in the manifest. For the context bundle, both outputs share one invocation but have separate hashes/results.

In standalone use, check the skill's required inputs directly. Do not require a manifest merely to write one artifact, create one yourself, dispatch other owners, or imply full-pipeline readiness. Report which downstream artifacts need revalidation. With a manifest, the caller runs the stage-aware checker before dispatch and after recording the owner result. Without it, the caller performs equivalent checks and discloses that automatic orchestration checks were unavailable.
