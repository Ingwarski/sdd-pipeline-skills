---
name: to-sdd-pipeline
description: Run the design-first SDD workflow from product intake through three prototypes, one whole-design approval and a validated development plan; pause for a separate implementation prompt.
---
# to-sdd-pipeline

Read [shared operating rules](references/common-contract.md) before work. Resolve all resources from this SKILL.md's real directory, following its installed link, never from the open project. Preserve `working_language`, source truth and approval boundaries.

## Mission and entry

Apply the [scope and portable execution contract](references/scope-and-execution.md): default full workflow, affected-only existing changes, or source-confirmed headless scope. Direct Codex/Claude Code can run owner roles inline and persist intake in the manifest; external runtime adapters are optional.

Reduce coordination while preserving one owner per artifact. Accept a rough description, existing/imported product idea, saved intake or explicit corrections. A product-idea file is optional **at entry**, required only before PRD generation.

If intent is missing/materially incomplete, dispatch or resume `to-product-idea`, surface one foreground question, set `awaiting-product-idea-intake` and do not start PRD. Validate a coherent existing file without a redundant interview. In DAS Forge require its current matching `ProductIdeaHandoffReceipt`; direct use may record the validated file's source mode/hash without a runtime receipt.

At first entry, use `to-product-idea` for any unrecorded design-materials intake even with coherent existing intent. Reuse supplied materials and recorded responses; do not reopen intake merely on resume.

Resolve language before intake: explicit instruction > recorded preference > latest substantive message. Pass it to every owner/adapter; keep UI/content locales separate. Read [intake adapter](references/intake-adapter.md) only for DAS Forge Phase 0.

## Ownership

Directly create/update only `forge/sdd-manifest.json`. Domain owners write only their declared outputs:

| Owner | Artifact under `docs/` |
|---|---|
| `to-product-idea` | product-idea.md |
| `to-sdd-prd` | prd.md |
| `to-project-context` | project-context.md + canonical-terms.md |
| `to-guardrails` | guardrails.md |
| `to-user-journey` | user-journey.md |
| `to-screen-map` | screen-map.md |
| `to-wireframes` | wireframes.md |
| `to-design-brief` | design-brief.md |
| `to-architecture` | architecture.md |
| `to-dod-evals` | dod-evals.md |
| `to-qa-checklist` | qa-checklist.md |
| `to-development-plan` | development-plan.md |

The context bundle is one invocation with two independent hashes/results. Both must validate before downstream dispatch. No domain owner writes the manifest; return metadata to this orchestrator. Mirror owner-returned typed definitions/links under [traceability](references/traceability-contract.md), never author their meaning here.

Runtime adapters own operational receipts. Codex mockup writes are confined to versioned `forge/design/candidates/{candidate_id}/{version}/`, optional `forge/design/candidate-sets/{candidate_set_id}/{set_version}/shared/`, and `forge/design/evidence/`. Claude writes only the selected export under `forge/design/inbox/{handoff_id}/selected-export/` and its authorized receipt; Codex alone imports/normalizes it. Log adapter/origin/version/hash/changed paths. No adapter writes production source or domain SDD.

## Stage order

[The machine contract](references/pipeline-contract.json) is the checker’s prerequisite/owner map. Required-before edges are distinct from later references:

```text
product-idea intake → PRD → context bundle → guardrails
→ journey → screen map → wireframes → design brief
→ architecture → DoD definitions → proposed QA
→ coherent pre-design SDD → executor/source preflight
→ three prototype candidates → one whole-design approval
→ design brief records approved baseline
→ architecture-approved → dod-evals-approved → qa-checklist-approved
→ development plan → awaiting-implementation-prompt
```

Post-approval labels are reconciliation passes of existing owners, not new skills/documents/approvals. Reuse valid bytes; rerun only affected owners and record fresh source/baseline bindings. Never skip architecture/DoD reconciliation because they ran before approval.

`JOB-*` belongs to product idea; `UC-*` to PRD. Later owners reference them. Context/guardrails never consume downstream artifacts; wireframes never require the design brief. DoD binds concrete QA IDs at evaluation; QA consults development destinations only after implementation begins. Those later lookups do not form creation dependencies.

## Checker and provenance

Read the [security traceability contract](references/security-contract.md) when recording PRD or downstream owner results. Persist the PRD's `security_review`, each affected owner's `security_coverage`, and security requirement/check/gate bindings without authoring their content. Missing legacy assessment returns to the PRD owner; new roles, data exposure or trust-boundary changes return upstream before design reconciliation. Styling-only revisions preserve unaffected security obligations.

Read [manifest/checker contract](references/manifest-contract.md) when initializing, migrating or updating metadata. Use the installed `scripts/sdd_check.py` (Python 3.12+, no external packages):

```text
python3 /resolved/to-sdd-pipeline/scripts/sdd_check.py --project /project --before NODE
python3 /resolved/to-sdd-pipeline/scripts/sdd_check.py --project /project --after NODE
```

Use `python` on Windows when that is the detected Python 3 executable. Resolve real paths first.

Before **every** owner/node dispatch, run `--before`. After recording an owner's result, run `--after`. On nonzero exit, inspect issue codes, re-invoke only affected owners or surface the exact missing capability/evidence; do not advance or self-declare the check passed. The checker never writes files, approves design, runs product tests or authorizes implementation.

For older manifests, preserve all documents/history/IDs and add only metadata verified from current sources/receipts. Missing evidence is not reconstructed as success. Unavailable original evidence stays a named limitation; see migration instructions.

Record exact consumed source hashes/fragments and repository observations. An unrelated context paragraph or repository file must not invalidate unrelated work. A PRD/intent change revalidates the context bundle together. Language changes revalidate affected human-readable artifacts, not immutable identifiers or distinct product locales.

The skill requires the check; a separate DAS Forge runner must invoke the same checker and enforce its exit code for hard runtime enforcement. Updating this repository does not modify that external runner.

## Design and evidence

At prototype generation, read [candidate/adapter contract](references/prototype-contract.md). Choose `design_executor: codex | claude_design`; if unset, surface Input needed with Codex recommended. This is an executor choice, not approval.

- Codex: exactly three distinct, equivalent-scope interactive mockups; show all three as stable pages on the selected visible review surface (external default browser unless the user chooses another).
- Claude Design: first read [handoff contract](references/claude-design-handoff.md), validate the full source inventory and both access/read receipts. Missing required sources pause at `awaiting-design-source-access`. Compare three tool-native candidates; import/open only the selected exact version. Selection/export is not approval; never fabricate local hashes for unexported alternatives or silently switch executors.

Whole-product coverage means design simulations of required flows, screens, states, fixtures/locales and viewports—not backend/auth/persistence/integrations or production implementation. Recommend with rationale; never auto-select. Every revision is a new immutable version.

Read the [verification contract](references/verification-contract.md) and [H1-H10 reference](references/heuristic-usability-review.md) when reconciling design, QA or completion evidence. Visual/browser, heuristic, representative-user, accessibility and functional evidence remain separate. High-risk pre-approval user validation may be explicitly deferred with risk/timing/owner; it must not be claimed as performed.

The design brief is the sole canonical Approved Visual Baseline. Mirror only hash-bound operational metadata. Recompute every frozen source-tree/target hash on reuse; never trust a recorded integrity status alone. A mismatch marks integrity violated and affected work invalid, preserving the original frozen files.

## Approval, invalidation and resume

1. Validate and record the actual whole-design receipt or explicit accepted scoped override. Mere preview, recommendation, Claude selection or revision request is not approval.
2. Invoke `to-design-brief` to record the canonical baseline; validate it.
3. Recheck `architecture-approved`, then `dod-evals-approved`, then `qa-checklist-approved` through their owners/checker. Bind only existing QA IDs; prepared checks remain not-run.
4. Invoke `to-development-plan` only after the current requirements/design/architecture and verification mappings validate.
5. Keep an old approved baseline active while a revision is merely proposed. Switch atomically only for a new approved whole or accepted scoped override; preserve prior IDs, receipts and decisions.
6. A changed active baseline invalidates affected check/unit bindings, `implementation_gate` and affected production Feature Units (`execution_invalidated`). No implementation agent may bless its own drift.
7. Resume from actual files and receipts, not stale status. Persist answers/receipts, recompute readiness and continue safe SDD work without another “continue” question.

Parallelize ready, independent work only when available execution permissions and ownership allow it. Serialize shared-source changes.

## Implementation command gate

When the current plan validates, record its hash, active Baseline ID/source version and gate arrival time. Set pipeline `state: awaiting-implementation-prompt` and `implementation_gate.state: awaiting_implementation_prompt`; return control. Do not dispatch Phase 3, write production source, promote mockups or invoke code-generation tools.

Release requires a **new user message after that pause** explicitly starting production implementation from the current plan. Prior pipeline requests, design approval, generic “continue”, automatic resume or owner output do not suffice.

On that later message, revalidate sources, baseline and plan. If changed, reconcile through owners and wait for a new prompt for the new plan. Otherwise record the exact prompt receipt/hash, intent, IDs/timestamps and current plan/baseline binding; run `--before implementation`. Only success permits handoff to the separately authorized Phase 3 runner. No new scope/authority is implied.

## Stops and return

Pause only for material non-inferable intent, the one whole-design approval, required source access/capability/evidence, just-in-time high-risk authorization, or the separate implementation prompt. Advisory findings, playback and ordinary reversible work are not approval gates.

Return a concise state/evidence summary: changed/validated/invalidated artifacts, language/locales, candidate/browser or handoff/source-access evidence when relevant, Baseline ID/integrity, checker result, check execution versus definition status, implementation gate/prompt receipt, named blockers and next action. Localize displayed labels; keep machine enum values unchanged.
