# Prototype Candidates and Design Adapters

Use the [selected review surface](scope-and-execution.md): external default unless the user chooses `in_app` or `external_named`. All require visible interactive review and matching receipts. Headless scope skips this stage; early exploration is not a formal candidate.

After pre-design SDD validates, resolve the executor. Codex creates, validates and shows three local candidates. For Claude Design, follow [the handoff contract](claude-design-handoff.md): complete source inventory, Codex access preflight and Claude read receipt. Missing required access pauses at `awaiting_design_source_access`. Then send the frozen-input prompt in `working_language`; Claude compares three candidates and exports the selected version; Codex imports, validates and shows it before approval. Use authorized transfer fallbacks; never silently change executors.

Compare exactly three distinct candidates with equivalent coverage of required screens, flows, states, data and viewports. Interactions are simulations: no production backend, auth, persistence, provider calls, repository mutations, Feature Units, integrations or application runtime. For Claude Design, retain all three native references and the operator's selection; normalize only the selected export. Never invent hashes or browser receipts for unexported candidates.

For every Codex candidate and the selected normalized Claude Design import require:
- candidate ID and version
- immutable visual-target reference: rendered artifact/result ID, mockup, screenshot, or frame
- frozen visual-target content hash
- frozen prototype source root and source-tree hash
- source-tree hash algorithm ID
- source artifact IDs/hashes
- stable live URL and route
- covered journey, screens, states, representative data, locale, and viewports
- working language used for review text and specification-facing explanations, distinct from product UI/content locales
- internal visual-QA evidence
- selected visible-browser open result

Retain applicable H1–H10 coverage and the representative-user validation plan. Visual QA and browser receipts support only their observed scope; neither replaces heuristic review or user validation.

Review critical action and recovery sequences through their specified controls or automatic/external triggers, not only selected state fixtures. Apply the [recovery walkthrough](heuristic-usability-review.md#error-and-recovery-contract) and applicable [focus checks](accessibility-policy.md). Record the observed state/transition accurately; a filename alone does not establish an outcome.

For regulated, accessibility-critical, safety-sensitive or other high-risk flows, state whether representative-user validation preceded approval. If infeasible, record the assumption, open risk and validation timing in the brief. Do not claim user validation or add an approval gate.

Apply the [freeze contract](freeze-contract.md) to all candidate inputs, including shared rendering assets. Recompute its hashes on reuse.

Codex opens A, B and C on separate stable live routes on the selected surface; a shared server is allowed. Images or headless captures are insufficient. For Claude Design, open and verify only the selected normalized export before approval.

Use the [browser evidence lifecycle](browser-evidence-workflow.md#settle-preserve-and-approve) when producing browser receipts: record live review, close and settle producers, archive/prepare evidence, validate, then record the later approval. Reopen unchanged candidates for further live review when needed.

Rank/recommend with rationale, never auto-select. Claude selection selects only the export; revision requests create no approval. After Codex validation/opening, whole-design approval binds the exact normalized candidate/version.

Each revision needs a new candidate version, immutable target and hash. Preserve and explicitly supersede prior versions; never overwrite them.

Vendor Work Mode, `terminal.local`, Sites and browser requirements are adapter transport, not the product's runtime platform. Keep `VisualQAEvidence` separate from visible-browser receipts. Apply [verification severity/release rules](verification-contract.md#severity-and-release-effect); vendor P2 does not automatically block.

Keep separate heuristic and user records with JOB/UC, journey, applicable visual or nonvisual scope from the verification contract, evidence, findings, severity and release effect. AI review and prototype interaction cannot manufacture either coverage or research.

Normalize `VisualQAEvidence` with adapter/environment, candidate or Baseline ID, target reference/hash, canonical preview URL, route/state/viewport/theme/content fixture, capture IDs labeled by actual role/stage, interactions checked, console result, QA result, findings with severity and release effect, and timestamp. Comparison/source or implementation captures are required only by the applicable review stage. Keep a compact canonical receipt and original provider attachment when one exists; avoid duplicate formatted reports. Required captures remain mandatory.

Image-to-code remains a Phase 2 simulation. Presentation reuse requires a traced promotion plan in `docs/development-plan.md`. Only the authorized Phase 3 runner derives the Git-diff receipt at `forge/runs/{unit_id}/{run_id}/prototype-promotion.json` or a verified reference; authoring and prose cannot supply it.

For literal URL cloning only, require an authorized `SourceCaptureBundle` before coding. Validate the requested page/state and reject unintended access barriers, interstitials or redirects; an intentionally requested login or error state remains in scope. Capture the required views and responsive sizes, complete small-step scrolling and lazy/sticky changes where present, DOM/style/layout evidence, every in-scope visible control/state and all required assets. Desktop/mobile coverage follows the authorized source scope. Treat an incomplete bundle as a typed clone blocker. Do not impose exhaustive clone capture on redesign, improvement, or inspiration routes.
