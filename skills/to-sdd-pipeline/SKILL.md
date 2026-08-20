---
name: to-sdd-pipeline
description: Orchestrate a design-first SDD pipeline from a rough product description, saved Product Idea Intake, or optional existing docs/product-idea.md through validated product-intent handoff, PRD, the project-context/canonical-terms bundle, the coherent pre-design SDD baseline, exactly three interactive prototype mockup candidates, one whole-design approval, post-approval reconciliation, and docs/development-plan.md. After the plan validates, pause at awaiting-implementation-prompt and never dispatch production implementation without a separate explicit implementation prompt. Use when the user wants the full SDD set generated or reconciled autonomously rather than invoking one artifact skill at a time.
---
# to-sdd-pipeline

## Mission

Run the SDD workflow as one autonomous dependency graph while preserving exclusive artifact ownership. The process exists to reduce an engineer's coordination work. Do not add file-by-file, screen-by-screen, or step-by-step approval gates.

Treat Product Idea Intake as the visible Phase 0 immediately upstream of this graph. Never silently invent or generate missing product intent. When `docs/product-idea.md` is absent or materially incomplete, dispatch or resume `to-product-idea` through the DAS Forge foreground intake adapter and return `awaiting-product-idea-intake`; do not continue into PRD generation.

## Entry Inputs And Node Prerequisites

A pre-existing `docs/product-idea.md` is optional and must never be an onboarding or pipeline-entry prerequisite. Accept any of these entry sources:

- a short or rough product description, with no product-idea file yet;
- an imported or repository-existing `docs/product-idea.md` selected by the operator;
- saved Product Idea Intake state or a current validated handoff;
- any compatible combination of those sources plus explicit operator corrections.

For the no-file path, dispatch or resume `to-product-idea` and remain at `awaiting-product-idea-intake` until the foreground intake materializes the file. For the existing-file path, validate the selected file as candidate product intent: if it is coherent and complete, create the handoff without a redundant full interview; if it has a material gap or contradiction, preserve it as the starting source and ask only the focused questions needed to resolve that gap. Record a repository-existing file as `source_mode: existing-file` and an externally supplied file as `source_mode: imported`.

Only the downstream `to-prd` node requires a validated current `docs/product-idea.md`. In DAS Forge it also requires a current `ProductIdeaHandoffReceipt` whose recorded content hash matches that file. These are preconditions for `to-prd`, not prerequisites for starting the Product Creation Run or invoking this orchestrator. In a direct non-DAS invocation, a validated existing file may serve as the handoff source without a runtime receipt, while its source mode and content hash still remain explicit in the manifest.

The artifact-owner skills listed below must be available before their nodes run. A project-supported mockup producer or Product Design adapter is required only before the prototype-mockup node runs. Phase 2 accepts `design_executor: codex | claude_design`; if it is unset, present the choice as `Input needed` with `codex` recommended. This is an executor choice, not an approval.

Read existing SDD artifacts and `forge/sdd-manifest.json` when present. Inspect the codebase for source-backed architecture, design-system, runtime, and verification facts instead of asking for discoverable information.

## Output And Ownership

This orchestrator directly creates or updates exactly one file:
- `forge/sdd-manifest.json`

It must never directly create or edit a domain artifact. Invoke or re-invoke the owning skill:

| Artifact | Owner |
|---|---|
| `docs/product-idea.md` | `to-product-idea` (foreground Phase 0; invoked for no-file intake, incomplete intent, imported or existing-file validation/handoff, missing or stale handoff, or an explicit upstream change) |
| `docs/prd.md` | `to-prd` |
| `docs/project-context.md` | `to-project-context` |
| `docs/canonical-terms.md` | `to-project-context` |
| `docs/guardrails.md` | `to-guardrails` |
| `docs/user-journey.md` | `to-user-journey` |
| `docs/screen-map.md` | `to-screen-map` |
| `docs/wireframes.md` | `to-wireframes` |
| `docs/design-brief.md` | `to-design-brief` |
| `docs/architecture.md` | `to-architecture` |
| `docs/dod-evals.md` | `to-dod-evals` |
| `docs/qa-checklist.md` | `to-qa-checklist` |
| `docs/development-plan.md` | `to-development-plan` |

An owner invocation may change only its declared artifact path or declared cohesive output set. `to-project-context` is one coupled two-output owner invocation: both files are required, validated and hashed separately, and recorded with the same owner-invocation ID. A missing, stale, or invalid member makes `project-context-bundle` incomplete and re-invokes that owner for the whole bundle. Every artifact still has exactly one owner. The orchestrator validates owner output, records its hash and provenance, then dispatches every newly ready SDD node through `docs/development-plan.md` without asking the user to continue. Once that final artifact validates, the implementation execution gate below takes control; no Phase 3 runner or implementation agent may be dispatched automatically.

The mockup producer is a runtime adapter, not an SDD artifact owner. In `codex` mode it may write candidate-specific design code/assets only under `forge/design/candidates/{candidate_id}/{version}/`, optional shared mockup-preview infrastructure only under the versioned `forge/design/candidate-sets/{candidate_set_id}/{set_version}/shared/` workspace, and normalized evidence under `forge/design/evidence/`. In `claude_design` mode, Claude Design may read the frozen handoff inputs and, after the operator selects one exact version there, write only that selected export under `forge/design/inbox/{handoff_id}/selected-export/`; the Codex import adapter alone normalizes it into candidate/evidence paths. Shared preview reuse resolves to that candidate-set version and cannot hide mutable source elsewhere. No design adapter may write production application source directories, production application logic, domain SDD artifacts, or the orchestration manifest. Every write records adapter, origin, handoff when applicable, candidate/version or candidate-set version, target hash, and changed paths. Phase 3 implementation agents own production-code writes under the bounds of the approved development plan.

## Dependency Graph

Use this acyclic graph:

```text
product-idea-intake
-> product-idea
-> prd
-> project-context-bundle
   |- project-context
   `- canonical-terms
-> guardrails
-> user-journey
-> screen-map
-> wireframes
-> design-brief
-> architecture
-> dod-evals
-> qa-checklist-proposed
-> coherent-pre-design-sdd
-> design-executor-choice
-> prototype-candidates
-> awaiting-design-approval
-> approved-visual-baseline
-> qa-checklist-approved
-> development-plan
-> awaiting-implementation-prompt
```

In pipeline mode, `to-project-context` reads only the product idea, PRD, explicit user decisions, README/CODEX, and independent project evidence; it never reads downstream SDD artifacts back into the context bundle. `docs/guardrails.md` depends only on the PRD, the validated context bundle, and explicitly authoritative upstream intent; it never reads downstream artifacts back into itself. `docs/wireframes.md` never depends on `docs/design-brief.md`. `docs/development-plan.md` never belongs to the pre-design baseline because it requires the Approved Visual Baseline. `awaiting-implementation-prompt` is the terminal state of this SDD artifact graph; Phase 3 implementation is outside the graph and requires the separate execution prompt.

Run independent ready nodes in parallel when their owner skills and workspace safety allow it. Serialize nodes that share a source file being updated.

## Product Idea Intake Handoff Contract

Product Idea Intake is a Product Creation Run, not a Feature Unit. It must appear in Mission Control as a dedicated foreground workspace with one current question, its recommended answer and rationale, custom-answer controls, live draft preview, and decision coverage. A question may never exist only in terminal output or a hidden agent log.

Use `to-product-idea` as the sole owner of `docs/product-idea.md`. The DAS Forge `ProductIdeaIntake` runtime adapter owns durable session/draft state and the handoff receipt under `forge/intake/`. It must:

- emit and persist one typed `ProductIntentQuestion` at a time;
- project an unanswered material question as `Input needed`, not `Blocked` or an approval;
- ensure each question walks one relevant decision branch, includes a recommended answer and rationale, cites the source basis or states no source confirms it, and names the downstream artifacts or boundaries affected by a different answer;
- after the answer, play back the confirmed decision and consequences through the owning skill before resuming dependent nodes;
- route the operator's external default browser to the exact pending intake request when the intake surface is not active;
- restore the current question, answers, draft version, assumptions, and decision branch after restart;
- resume automatically after each answer without a separate continuation command;
- never convert a timeout, silence, recommendation, or non-response into consent for material product intent;
- after `Create product idea and start SDD`, atomically create or version `docs/product-idea.md` only when absent or confirmed intent changed, otherwise preserve the validated existing file byte-for-byte, then hash the final file;
- write `forge/intake/product-idea-handoff.json` with at least intake/session ID, source mode, artifact path, content hash, answered decision IDs, assumptions, unresolved non-blocking questions, submission event, and timestamp.

`Create product idea and start SDD` is the initial execution command, not an approval receipt. Draft playback, answering questions, editing prior answers, resuming intake, and submitting intent do not add approval gates. The only normal product-creation approval remains approval of the complete integrated design baseline.

If a downstream owner discovers missing material product intent, suspend only the affected dependency branch, route one scoped question through the same intake UI, persist the answer, re-invoke `to-product-idea`, and invalidate only transitive dependents of the changed idea hash. Unrelated safe work may continue when ownership and dependencies remain unambiguous.

## Project Context Bundle Contract

Immediately after `docs/prd.md` validates, invoke `to-project-context` once to produce:

- `docs/project-context.md`
- `docs/canonical-terms.md`

Both outputs must validate from the same current PRD/product-intent source set and owner-invocation ID before `guardrails` or any later node becomes ready. Their assumptions and non-blocking open questions remain visible but do not create approval gates.

Pass both validated files to every downstream artifact owner as candidate upstream sources. Owners must use only relevant confirmed context and exact canonical vocabulary:

- `project-context.md` may supply users, platforms, localization, boundaries, constraints, dependencies, operational risks, and other confirmed context, but cannot add or override product behavior, architecture, guardrails, design, DoD, or QA truth;
- `canonical-terms.md` governs downstream naming and aliases only; it cannot redefine PRD behavior or silently rename established technical identifiers;
- assumptions remain assumptions, and descriptive or irrelevant content must not be copied merely to prove the files were read.

For each downstream artifact, record only the exact context sections or canonical-term entries it consumed in that artifact's manifest provenance. Hash those consumed fragments independently so an unrelated prose edit does not invalidate the whole pipeline. A change to a consumed context fact or term invalidates only its transitive dependents. A PRD or authoritative product-intent change invalidates both bundle members together. If the bundle exposes an upstream contradiction, re-invoke the upstream owner first and then regenerate the bundle; never patch the PRD from `to-project-context` or create a dependency cycle.

## Autonomy And Stop Rules

Resolve non-material uncertainty from source files, codebase evidence, or the smallest reversible source-grounded default. Record the decision and continue.

Pause only for:
1. Product Idea Intake or a later genuinely non-inferable decision that materially changes product scope, surfaced through a foreground `Input needed` request;
2. the engineer's one approval of the complete integrated prototype, which also selects the candidate and creates the Approved Visual Baseline;
3. just-in-time authorization before an irreversible, destructive, financial, legal, public, privileged, security-sensitive, privacy-sensitive, or external side effect;
4. the separate implementation execution prompt after the current `docs/development-plan.md` validates. This is a command gate, not an additional design approval or a product-intent question.

Artifact playback, validation, preview visibility, candidate recommendation, advisory P2/P3 findings, and ordinary reversible changes are not approval gates.

An owner result of `baseline_change_required` is not a question gate. Invalidate the affected design dependents, generate a revised candidate whole from current sources, and pause only at `awaiting-design-approval` for approval of that revised integrated baseline. If the current source already contains an explicit scoped operator correction and acceptance, persist it as an operator override and reconcile the affected baseline scope without asking the operator to approve the same correction again.

## Prototype Mockup Candidate Contract

After the coherent pre-design SDD baseline validates, resolve the Phase 2 executor and invoke its adapter. In `codex` mode, use the normal local flow: Codex creates exactly three candidates in the candidate workspace, validates them, and opens all three external-browser pages before the one whole-design approval. In `claude_design` mode, follow [Claude Design Handoff Contract](references/claude-design-handoff.md): Codex generates the frozen-input prompt with resolved project paths; Claude Design creates exactly three candidates, the operator selects one exact version there, Claude Design directly exports only that selection to the handoff inbox when available, and Codex validates/imports/opens it before whole-design approval. The documented transfer fallbacks may be used when direct export is unavailable, including manual transfer as the last viable option. Never silently substitute Codex design generation for a selected Claude Design mode.

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
- internal visual-QA evidence
- external-default-browser open result

Compute every source-tree hash as `sdd-tree-sha256-v1`: SHA-256 over the concatenation of `"<relative-path>\n<sha256-hex-of-file-bytes>\n"` for every file under the root, sorted byte-wise by relative path, excluding nothing. Record the algorithm ID alongside every candidate and active-baseline hash so later runs can recompute it. A hash whose algorithm is absent or unknown is not evidence.

In Codex mode, open Candidate A, Candidate B, and Candidate C as three separate live pages in the operating system's external default browser. They may share one preview server, but each must have an independently addressable stable route; embedded previews, static images, and headless captures do not satisfy this mode. In Claude Design mode, comparison occurs across the three tool-native candidates there; after selected-export import, Codex opens and verifies the one normalized selected candidate in the external default browser before approval.

The system may rank and recommend with rationale but must not auto-select. A selection made inside Claude Design selects the export only; it creates no approval receipt. `Request revision` creates no approval receipt. After Codex validates and opens the candidate, `Approve design baseline` selects the exact normalized candidate/version and records the only normal design approval.

Every revision creates a new candidate version, immutable target reference, and content hash. Never overwrite a candidate or approved target in place; retain prior versions and supersede them explicitly.

Treat vendor Work Mode, `terminal.local`, Sites, cloud-browser, or in-app-browser requirements as adapter transport. Persist internal `VisualQAEvidence` separately from the operator-visible browser receipt. Apply DAS Forge release-effect policy to imported findings; a vendor P2 is not automatically blocking.

Normalize `VisualQAEvidence` with adapter/environment, candidate or Baseline ID, target reference/hash, canonical preview URL, route/state/viewport/theme/content fixture, source and implementation capture IDs, interactions checked, console result, QA result, findings with severity and release effect, and timestamp. Retain raw provider reports only as attachments.

Treat image-to-code output as a Phase 2 interactive frontend mockup preview, not an application implementation. It may simulate product states for design review but does not implement or prove production auth, persistence, backend/API, provider execution, integrations, security boundaries, repository effects, or exhaustive edge cases. Presentation-layer mockup code may optionally seed production work only through the traced promote/diff contract in `docs/development-plan.md`. The Phase 3 runner, not this orchestrator, the planning skill, or implementation-agent prose, owns the resulting `forge/runs/{unit_id}/{run_id}/prototype-promotion.json` receipt derived from the actual Git diff.

For literal URL cloning only, require an authorized `SourceCaptureBundle` before coding. Validate the correct page and reject login/error/blocked/loading/install/promo/redirect captures; record complete small-step desktop scrolling, lazy-loaded and sticky changes, the required mobile viewport, DOM/style/layout evidence, responsive behavior, every visible control and state, and all required images, icons, fonts, videos, SVGs, stylesheets, and other assets. Treat an incomplete bundle as a typed clone blocker. Do not impose exhaustive clone capture on redesign, improvement, or inspiration routes.

## Baseline And Invalidation

The `Approved Visual Baseline` section of `docs/design-brief.md` is the single canonical baseline manifest and the visual Definition of Done for user-visible frontend implementation. After approval:
0. Recompute the approved candidate source-tree hash with its recorded algorithm and compare it to the recorded value. On mismatch, set `active_baseline.integrity.status` to `violated`, record the observed and recorded hashes, invalidate dependent visual artifacts, and surface the violation in the Final Report. A recorded hash is a claim to re-verify on every run, never a fact to trust. This verification is not an approval gate.
1. re-invoke `to-design-brief` to set `Status: approved`, Baseline ID, candidate/version, immutable target reference/hash, frozen prototype source root/tree hash and algorithm, prototype references, origin/handoff when applicable, coverage, receipt, visual-DoD scope, permitted variance, and supersession;
2. re-invoke `to-qa-checklist` so concrete visual checks reference the Baseline ID;
3. invoke `to-development-plan` only after both updates validate.

If a source hash changes, invalidate only transitive dependents. Keep the current approved baseline active and immutable while a revision is merely proposed. Atomically switch the active Baseline ID only when the operator approves a revised integrated whole or explicitly directs and accepts a scoped baseline correction; record the latter as an operator override without a redundant approval prompt. When a later baseline supersedes the prior one, re-invoke the QA and development-plan owners automatically, invalidate `implementation_gate`, and mark affected production Feature Units `execution_invalidated` in the manifest/runtime projection. This skill does not own production implementation agents; the DAS Forge Phase 3 runner may dispatch them only after the current plan validates and a later explicit implementation prompt releases the gate. An implementation agent cannot create an override or make its own drift authoritative.

## Implementation Execution Gate

When `docs/development-plan.md` is created or updated by `to-development-plan` and validates against the current Approved Visual Baseline, the orchestrator must:

1. recompute and record the final development-plan content hash, the active Baseline ID, and the source version used for the plan;
2. set the top-level pipeline `state` to `awaiting-implementation-prompt` and `implementation_gate.state` to `awaiting_implementation_prompt`;
3. return control with `Next Executable Action: send a separate explicit implementation prompt`;
4. dispatch no Phase 3 runner, implementation agent, code-generation tool, production source write, or prototype promotion at this point.

A valid release requires a new user message received after this gate is reached that explicitly asks to start production implementation from the current validated development plan, for example: `Start Phase 3 production implementation from the current validated docs/development-plan.md.` A prior pipeline prompt, design approval, owner result, automatic resume, generic `continue`, or `implement it` without an explicit implementation intent does not satisfy this gate.

On that later resume, re-read and revalidate `docs/development-plan.md`, `docs/design-brief.md`, `docs/qa-checklist.md`, the active Baseline ID, and the recorded plan hash. If any required source changed, keep the gate paused, invalidate the affected plan, and regenerate it through its owner before accepting a new implementation prompt. Only after these checks pass may the orchestrator record the prompt receipt, set `implementation_gate.state` to `authorized_for_phase3`, and hand off to the Phase 3 runner. The prompt authorizes execution of the current plan; it does not change product scope, architecture, guardrails, design, or implementation-unit boundaries.

## Manifest Contract

Store at least:

Store `project-context` and `canonical-terms` as two separate entries in `artifacts`. Both entries use `owner_skill: to-project-context`, the same non-null `owner_invocation_id`, and the same two-member `declared_output_set`; their content hashes and validation results remain independent.

```json
{
  "pipeline_version": "string",
  "state": "string",
  "product_idea_intake": {
    "status": "not_started|awaiting_answer|ready_to_submit|handed_off|superseded",
    "intake_id": "string|null",
    "source_mode": "seed|interview|imported|existing-file|null",
    "handoff_receipt_path": "string|null",
    "product_idea_hash": "string|null",
    "current_request_id": "string|null"
  },
  "artifacts": {
    "artifact_id": {
      "path": "string",
      "owner_skill": "string",
      "owner_invocation_id": "string|null",
      "declared_output_set": [],
      "status": "missing|input_needed|ready|running|validated|invalidated|blocked",
      "mission_control_status": "Pending|Input needed|Running|Ready|Needs attention|Approved design|Blocked|Done",
      "source_version": "string|null",
      "source_hashes": {},
      "consumed_source_fragments": {},
      "repository_observation_id": "string|null",
      "dependencies": [],
      "dependency_status": {},
      "content_hash": "string|null",
      "validation": {},
      "open_questions": [],
      "supersedes": "string|null"
    }
  },
  "repository_observations": {
    "observation_id": {
      "paths": {},
      "commit": "string|null",
      "working_tree_state": "clean|dirty|unavailable",
      "commands": [],
      "observed_at": "string"
    }
  },
  "design_execution": {
    "mode": "codex|claude_design|null",
    "handoff_id": "string|null",
    "state": "not_started|awaiting_executor_choice|generating_candidates|awaiting_claude_design_selection|awaiting_claude_design_export|awaiting_export_transfer|validating_import|awaiting_design_approval|approved_visual_baseline",
    "inbox_path": "string|null",
    "transport": "direct_export|codex_assisted_import|manual_transfer|authorized_url_capture|null",
    "claude_candidate_references": [],
    "selected_candidate_version": "string|null",
    "selection_receipt": "object|null"
  },
  "prototype_candidates": [],
  "prototype_promotions": [],
  "implementation_gate": {
    "state": "not_reached|awaiting_implementation_prompt|authorized_for_phase3|invalidated",
    "development_plan_hash": "string|null",
    "approved_baseline_id": "string|null",
    "prompt_id": "string|null",
    "prompt_received_at": "string|null",
    "released_at": "string|null",
    "reason": "string|null"
  },
  "approved_baseline_id": "string|null",
  "active_baseline": {
    "baseline_id": "string|null",
    "visual_target_hash": "string|null",
    "prototype_tree_hash": "string|null",
    "hash_algorithm": "sdd-tree-sha256-v1|null",
    "integrity": {
      "status": "unverified|verified|violated",
      "recorded_hash": "string|null",
      "observed_hash": "string|null",
      "checked_at": "string|null"
    },
    "operator_overrides": [],
    "supersedes": "string|null"
  },
  "affected_feature_units": [],
  "input_requests": [],
  "pause_reason": "string|null",
  "last_resume_event": "object|null",
  "next_ready_nodes": []
}
```

Artifact `status` is orchestration state, while `mission_control_status` is its operator-facing projection. Map an unanswered material question to internal `input_needed` and operator-facing `Input needed`; it is neither a failure nor an approval. Map `validated` to `Done`, `invalidated` to `Needs attention` until it becomes ready again, and `blocked` to `Blocked`; `ready` means machine-ready for dispatch and is never an approval. `Approved design` is reserved for the active whole-design baseline state, not ordinary artifact completion. Keep `source_version`, `source_hashes`, `dependencies`, and `dependency_status` explicit for every artifact so readiness and invalidation do not have to be inferred from prose or filesystem order.

The implementation gate is separate from artifact readiness and design approval. `awaiting_implementation_prompt` means the SDD set, including the current development plan, is complete but production execution is intentionally paused. `authorized_for_phase3` is valid only when the prompt receipt matches the current plan hash and Approved Baseline ID. A generic continuation event must never advance this gate.

When an owner inspects the repository, create a scoped repository observation containing only the exact paths and commands that support its claims, then record its ID on that artifact. Re-observe those paths on the next invocation; a changed observed path invalidates the dependent claim exactly as a changed source fragment does. Never use one whole-repository fingerprint that makes unrelated code changes invalidate every artifact, and treat an unobserved repository assertion as invalidated.

When the development plan declares traced prototype reuse, register the required promotion-receipt path and strategy in `prototype_promotions`. The Phase 3 runner moves its status from `required` to `written` to `validated` from the actual Git diff, but it may do so only after `implementation_gate` is `authorized_for_phase3`. If a declared production destination exists while the receipt is absent or its `copy | adapt | reimplement` strategy differs from the plan, keep the applicable fidelity gate blocked; never fabricate a historical receipt in this orchestrator.

Do not store secrets. Use stable IDs and content hashes so resume and invalidation are deterministic.

## Workflow

1. Load or initialize the manifest from actual files; never trust stale manifest state over filesystem evidence.
2. Resolve the optional entry source. With no pre-existing `docs/product-idea.md`, set `awaiting-product-idea-intake`, dispatch or resume `to-product-idea` from the rough description or saved intake, persist any typed request, and return control without launching downstream owners. With an existing/imported file, validate it first; hand it off without redundant questions when coherent, or dispatch only the focused material questions needed when incomplete, stale, contradictory, or explicitly corrected.
3. When `Create product idea and start SDD` supplies a valid matching handoff receipt, clear the intake pause and continue automatically. Do not request another confirmation.
4. When resuming from a later product-scope answer, design-approval receipt, or risk-authorization receipt, validate and persist the response, clear `pause_reason`, recompute hashes and ready nodes, and continue automatically in the same pipeline run. Do not require a separate resume confirmation.
5. Validate `docs/product-idea.md` and its current handoff hash, dispatch `to-prd` if required, then invoke `to-project-context` once for the two-file bundle. Validate both members separately, verify their shared owner-invocation ID and current source hashes, and do not make `guardrails` ready until both pass.
6. Compute ready nodes from the dependency graph and dispatch their owner skills with the validated context bundle available as relevance-scoped upstream sources.
7. After each result, validate the owner boundary, source traceability, required structure, open questions, and content hash. Convert a material non-inferable product-intent question into a typed `Input needed` request instead of leaving it in background logs.
8. Reconcile terminology against `docs/canonical-terms.md` and cross-artifact conflicts by re-invoking owners; never patch their artifacts directly. Record only consumed context/term fragments so unrelated bundle edits do not trigger broad invalidation.
9. Continue until the coherent pre-design SDD baseline validates.
10. Resolve `design_executor`. For `codex`, run the normal three-local-candidate flow, validate it, and open all three pages. For `claude_design`, generate the handoff/return prompt, persist the handoff state through selection/export/transfer/import, validate the selected normalized import, and open it. Pause at `awaiting_design_approval` only after the applicable path is ready for whole-design approval.
11. Persist the Approved Visual Baseline through its owner, update QA through its owner, and create the development plan through its owner.
12. After the validated development plan is written, record its hash and enter `awaiting-implementation-prompt`. Return control without dispatching Phase 3 or any production-code creator.
13. On a later resume with a separate explicit implementation prompt, revalidate the current plan and baseline hashes, record the prompt receipt, set `implementation_gate.state` to `authorized_for_phase3`, and hand off to the Phase 3 runner. Do not infer this prompt from a generic resume or a previous pipeline command.
14. Return the pipeline state, evidence, approved Baseline ID, implementation gate, invalidations, and next executable action.

## Final Report

Return:
- `Result`
- `Pipeline State`
- `Manifest`
- `Product Idea Intake And Handoff`
- `Validated Artifacts`
- `Prototype Mockup Candidates And Browser Receipts`
- `Approved Baseline ID`, when approved
- `Baseline Integrity`, when a baseline exists
- `Design Executor Handoff And Import`, when Claude Design was selected
- `Implementation Execution Gate`
- `Implementation Prompt Receipt`, when Phase 3 has been explicitly released
- `Invalidated Or Regenerated Artifacts`
- `Blocking Decision Or Authorization`, only when paused
- `Input Needed`, only when awaiting an operator answer
- `Next Executable Action`
