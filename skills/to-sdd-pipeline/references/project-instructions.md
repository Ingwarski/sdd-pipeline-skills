# Project execution instruction setup

## Scope and ownership

The main pipeline agent performs setup during an authorized invocation of the pipeline that includes project setup/authoring. Advice, review or a plan request alone does not authorize changing a product project's instructions. Installing the skillset does not modify product projects.

This is a narrow exception to manifest-only orchestrator outputs: reconcile root `AGENTS.md` and only the minimum authorized project-local host instruction-file changes needed to load it. Do not modify global settings, managed policies, ancestor/neighbouring repositories or the skillset installation. Domain owners still write their declared artifacts only. Never copy skillset-maintainer instructions into a product.

Use the [project policy template](../assets/project-AGENTS.md). Its coding rules apply after explicit implementation authorization; setup does not open that gate. Read [host loading verification](host-instruction-loading.md) for effective file selection, overrides, import conditions and evidence limits.

## Procedure

1. Verify the actual product root, worktree/branch and existing changes. Inspect relevant root, ancestor, override, nested and host-specific instruction sources before editing. Do not assume the shell directory or skillset clone is the product.
2. Preserve the original in version history or a recoverable local copy before reconciliation. Compare by meaning, retaining unrelated rules, user choices and stricter restrictions. Do not overwrite an existing file with the template or silently remove a conflicting rule.
3. For a missing policy, create it. For an existing policy, reconcile one `sdd-project-execution` section, using its stable marker/revision and the previous installed section or permitted recorded content identity. Reconcile unmarked existing rules by meaning rather than appending a competing policy. Preserve user adaptations. If the earlier source is unavailable, do not assume a difference is disposable template text. Resolve from current authority or present an unresolved material conflict. Confirm a second setup does not create duplicates or undo adaptations.
4. Resolve canonical document locations and adapt supported references without relocating files. Future guardrails, plan, QA and DoD documents need not exist during initial setup; record expected locations and require the actual readable documents before implementation.
5. Verify effective loading according to the host reference. Preserve existing host instruction content; use a project-local import only when needed and supported. Do not delete overrides or change global settings to obtain a pass. An excluded or conflicting policy remains a prerequisite, not successful setup.
6. Explicitly read current effective instructions. Record the host/version, entry path, effective source/content identities, policy revision, reference resolution and actual verification method. Separate current reading from fresh-session automatic loading. Verify a fresh supported session and relevant worker entry paths before advertising compatibility; disclose unavailable host evidence.
7. Report exact changes, preserved content and limits. Keep setup observations and recoverable history in existing operational storage, outside product requirements and approved evidence. Later template updates require authorized reconciliation rather than silent replacement.

## Implementation and recovery preflight

Before a unit starts or resumes, the main agent reads effective instructions, resolves required document references, checks current authorization/source state and supplies relevant instructions to workers. Preserve the effective instruction basis and a recoverable checkpoint in existing execution records. Recheck changed policy, branch/directory and source inputs; review affected execution without automatically invalidating unrelated product evidence.

Missing or suppressed policy, conflicting effective rules, unreadable required references or unavailable required evidence block the affected action. Continue independent authorized work under the six pause reasons. Missing setup does not block standalone specification authoring.

Project instruction setup and policy/checkpoint recording are manual agent responsibilities; the current checker does not enforce them. Do not fabricate checker success, add invented schema fields or present a prose check as mechanical enforcement.

## One source for each rule

| Location | Responsibility |
|---|---|
| Project `AGENTS.md` | Coding execution, continuation, six pause reasons, coordination, checkpoints and truthful reporting. |
| Guardrails | Project-specific authority, permissions, restrictions and material decisions. |
| PRD, design and architecture | Behaviour, presentation, mechanisms and protections. |
| Definition of Done | Completion/release conditions and required evidence. |
| QA checklist | Concrete actions, expected results, findings and evidence. |
| Development plan | Unit scope, dependencies, responsibilities, construction work and required check IDs. |
| Existing execution records | Effective instruction basis, actual assignments, progress, checkpoints and original observations. |

Generated SDD documents reference execution policy rather than copying it. The plan retains one completion condition and all specific unit duties and acceptance mappings. A failed gate blocks its completion claim, not all independent authorized work.

## Verification

Verify missing/existing/conflicting/overriding instructions, local adaptations, repeat setup, document resolution, branch changes and supported fresh-session/worker loading. Preserve original observations. Behavioural evaluation must test actual continuation, pauses and recovery; file checks alone do not demonstrate them.

Instructions cannot restart an ended session or enforce an account-wide spending cap. Pass spending restrictions to workers and authorized recurring tasks and stop at included-allowance boundaries without consuming extra credits or resets automatically.
