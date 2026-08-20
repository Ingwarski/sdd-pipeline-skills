# Claude Design Handoff Contract

Use this contract only when `design_executor: claude_design` is explicitly selected. Candidate selection in Claude Design is not design approval. The later whole-design approval in Codex makes the validated imported version the source of truth.

## Codex Handoff Prompt

Generate one paste-ready prompt containing:

- the resolved absolute project root;
- `handoff_id` and the exact inbox path `forge/design/inbox/{handoff_id}/selected-export/`;
- resolved absolute paths for every frozen SDD input, including `docs/design-brief.md`, `docs/wireframes.md`, `docs/screen-map.md`, `docs/user-journey.md`, `docs/prd.md`, and `docs/guardrails.md`;
- the content hash of each input and the approved locale/viewports/state coverage;
- an instruction to create exactly three meaningfully distinct, equivalent-scope, interaction-simulated visual candidates in Claude Design;
- the Phase 2 boundary: no production backend, auth, persistence, provider calls, integrations, repository mutation, or production-source writes;
- an instruction that the operator selects one exact candidate/version in Claude Design before export;
- an instruction that, after selection, Claude Design directly exports only that selected version as a self-contained folder or standalone HTML under the exact inbox path and writes nowhere else in the project;
- a return instruction: report `handoff_id`, selected candidate/version, export shape, and exact export path, then tell the operator to return to Codex and resume that handoff.

Claude Design may read the frozen inputs named in the prompt. It may not edit them, the manifest, production code, other candidates, or any project path outside its selected-export directory.

## Transport Resolution

Prefer direct Claude Design export to the inbox. If direct export is unavailable, report that capability as unavailable and choose the first authorized viable fallback; do not silently switch design generation to Codex:

1. `codex_assisted_import`: the operator identifies the exact existing local export path, and Codex copies/imports it into the inbox after resolving and validating that exact source.
2. `manual_transfer`: when no direct or Codex-assisted transfer is possible, give the operator the exact source and inbox destinations and allow the operator to transfer the selected export. Do not imply that manual transfer is forbidden or that it is the normal path.
3. `authorized_url_capture`: when the operator supplies or authorizes a stable export URL, Codex captures it into the inbox and records the URL receipt without treating the URL as the durable baseline.

If no transfer path is currently possible, remain at `awaiting_export_transfer`, preserve the handoff, and state the unavailable capabilities and next viable action. Never ask the operator to recreate files by copying snippets from chat.

## Codex Return Validation

On resume, Codex must:

1. resolve the selected export beneath the handoff inbox and reject path escape, multiple selected versions, missing assets, external runtime dependencies, secrets, executable backend behavior, or production-source writes;
2. normalize the selected export into a new immutable candidate/version under `forge/design/candidates/{candidate_id}/{version}/` and evidence under `forge/design/evidence/`;
3. compute `sdd-tree-sha256-v1`, record source-input hashes, import transport, origin `claude_design`, handoff ID, changed paths, and validation evidence;
4. open the normalized candidate in the external default browser and verify the required routes, states, interactions, locale, assets, console, and viewports;
5. enter `awaiting_design_approval` only after validation succeeds.

The operator's Claude Design selection identifies what to import. Only `Approve design baseline` in Codex records the whole-design approval and permits `to-design-brief` to make that exact normalized candidate/version the Approved Visual Baseline.
