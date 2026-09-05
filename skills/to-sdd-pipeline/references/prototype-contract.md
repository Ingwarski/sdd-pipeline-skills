# Prototype Candidates and Design Adapters

Use the [selected review surface](scope-and-execution.md): external default unless the user chooses `in_app` or `external_named`. All require visible interactive review and matching receipts. Headless scope skips this stage; early exploration is not a formal candidate.

After pre-design SDD validates, resolve the executor. Codex creates, validates and shows three local candidates. For Claude Design, follow [the handoff contract](claude-design-handoff.md): complete source inventory, Codex access preflight and Claude read receipt. Missing required access pauses at `awaiting_design_source_access`. Then send the frozen-input prompt in `working_language`; Claude compares three candidates and exports the selected version; Codex imports, validates and shows it before approval. Use authorized transfer fallbacks; never silently change executors.

Both modes must present exactly three meaningfully distinct, equivalent-scope, interaction-simulated Prototype Mockup Candidates at the comparison stage. `Whole-product` means coverage of the required product screens, flows, states, representative data, and viewports; it never means that Phase 2 implements the whole application. Candidate interactions are design simulations only and must not implement or claim production backend, auth, persistence, provider calls, repository mutations, Feature Unit execution, integrations, or other application runtime behavior. In Claude Design mode, preserve the three tool-native candidate references and the operator's selected reference in the handoff record; only the selected export becomes a normalized repository candidate. Do not fabricate local source hashes or browser receipts for the two candidates that were not exported.

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

Candidate comparison must preserve the applicable H1-H10 heuristic coverage and the representative-user validation plan. Internal visual-QA evidence and browser receipts may prove visual or runtime observations within their scope, but they do not replace `heuristic_usability_review` evidence or representative-user task validation.

For regulated, accessibility-critical, safety-sensitive, or otherwise high-risk flows, the candidate review must surface whether representative-user task validation was run before whole-design approval. If it was not feasible, preserve the explicit assumption/open risk and validation timing in the design brief; this does not create a second approval gate, but it prevents the pipeline from claiming that the design is user-validated.

Apply the [freeze contract](freeze-contract.md) to all candidate inputs, including shared rendering assets. Recompute its hashes on reuse.

Codex opens A, B and C as separate live pages on the selected review surface. They may share a server but need independent stable routes; static images/headless captures are insufficient. Claude Design compares three native candidates; after export, Codex opens and verifies only the normalized selected candidate before approval.

The system may rank and recommend with rationale but must not auto-select. A selection made inside Claude Design selects the export only; it creates no approval receipt. `Request revision` creates no approval receipt. After Codex validates and opens the candidate, `Approve design baseline` selects the exact normalized candidate/version and records the only normal design approval.

Every revision creates a new candidate version, immutable target reference, and content hash. Never overwrite a candidate or approved target in place; retain prior versions and supersede them explicitly.

Treat vendor Work Mode, `terminal.local`, Sites, cloud-browser, or in-app-browser requirements as adapter transport. Persist internal `VisualQAEvidence` separately from the operator-visible browser receipt. Apply DAS Forge release-effect policy to imported findings; a vendor P2 is not automatically blocking.

Visual-QA and browser receipts do not prove heuristic usability coverage or that representative users can complete a critical task. Preserve the applicable H1-H10 review record and `heuristic_usability_review` result separately from any `representative_user_task_validation` plan/result, with their `JOB-*`, `UC-*`, journey, screen/state/route/viewport, evidence, findings, severity, and release effect. Do not synthesize heuristic or user evidence from an AI review or a prototype interaction.

Normalize `VisualQAEvidence` with adapter/environment, candidate or Baseline ID, target reference/hash, canonical preview URL, route/state/viewport/theme/content fixture, source and implementation capture IDs, interactions checked, console result, QA result, findings with severity and release effect, and timestamp. Retain raw provider reports only as attachments.

Treat image-to-code output as a Phase 2 interactive frontend mockup preview, not an application implementation. It may simulate product states for design review but does not implement or prove production auth, persistence, backend/API, provider execution, integrations, security boundaries, repository effects, or exhaustive edge cases. Presentation-layer mockup code may optionally seed production work only through the traced promote/diff contract in `docs/development-plan.md`. The Phase 3 runner, not this orchestrator, the planning skill, or implementation-agent prose, owns the resulting `forge/runs/{unit_id}/{run_id}/prototype-promotion.json` receipt derived from the actual Git diff.

For literal URL cloning only, require an authorized `SourceCaptureBundle` before coding. Validate the correct page and reject login/error/blocked/loading/install/promo/redirect captures; record complete small-step desktop scrolling, lazy-loaded and sticky changes, the required mobile viewport, DOM/style/layout evidence, responsive behavior, every visible control and state, and all required images, icons, fonts, videos, SVGs, stylesheets, and other assets. Treat an incomplete bundle as a typed clone blocker. Do not impose exhaustive clone capture on redesign, improvement, or inspiration routes.
