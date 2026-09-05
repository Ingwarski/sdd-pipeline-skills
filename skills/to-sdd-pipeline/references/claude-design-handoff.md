# Claude Design Handoff Contract

Use only when `design_executor: claude_design` is explicit. Claude Design selection is not approval. The later whole-design decision in the active host makes the validated imported version authoritative.

Carry the pipeline language record unchanged through the handoff. Write the paste-ready prompt, operator instructions, source-access failures, selection/export guidance, and return report in `working_language`. Keep product UI/content locales separate. For Ukrainian, require idiomatic Ukrainian and permit English only for immutable paths/filenames, code/commands, machine values, API/identifier names, names/quotations, and the approved IT terms listed in `preserved_english_terms`, such as `SDD Pipeline`.

## Required Design Source Access Gate

`docs/design-brief.md` owns the `Design Source Material Inventory`. It is the authoritative list of every design source Claude Design must be able to see: local files, screenshots, captured assets, Figma/Storybook/Drive links, design-system references, brand assets, and reference products. The orchestrator must not derive a smaller list by selecting only the frozen SDD files.

For each Claude Design handoff, create and hash these operational records under `forge/design/handoffs/{handoff_id}/`:

- `design-source-manifest.json`: the current language record plus one entry for every inventory item, with `material_id`, `kind`, `required`, exact location or captured-bundle path, purpose, source basis, access mode, and content hash or capture ID;
- `codex-access-receipt.json`: the preflight result for every item, with resolved location, status `accessible | inaccessible | not_required`, observed hash or capture ID, checked-at timestamp, and an error or note when applicable;
- `claude-source-read-receipt.json`: Claude Design's receipt after it has opened/read every required item, with the manifest hash, one result per `material_id`, observed hash or capture ID, and unresolved items.

Do not store credentials, tokens, cookies, or other secrets in these records. A URL is not evidence that Claude Design saw the source: the receipt must record a successful authorized open/read or a self-contained capture/bundle.

Before candidate generation, the orchestrator must:

1. build the manifest from the complete design-brief inventory and the frozen SDD inputs;
2. resolve every required local path and external material in the environment that will be handed off, recording the result in `codex-access-receipt.json`;
3. if any required item is inaccessible, set `design_execution.state` to `awaiting_design_source_access` (projected pipeline state `awaiting-design-source-access`), do not invoke Claude Design candidate generation, and report the exact `material_id`, location, failure, and authorized capture/permission needed;
4. include the manifest path/hash and preflight receipt path/hash in the prompt;
5. require Claude Design to return `claude-source-read-receipt.json` (or an equivalent structured receipt) before creating candidates. If any required item is not read, remain at `awaiting_design_source_access` and do not proceed to selection or export.

This gate is separate from whole-design approval. A source-access receipt proves visibility, not correctness, quality, selection, or approval.

## Codex Handoff Prompt

Generate one paste-ready prompt containing:

- the resolved absolute project root;
- `working_language`, its selection source, distinct product content locales, and every approved preserved English IT term with its Ukrainian meaning when applicable;
- `handoff_id` and the exact inbox path `forge/design/inbox/{handoff_id}/selected-export/`;
- resolved absolute paths for every frozen SDD input, including `docs/design-brief.md`, `docs/wireframes.md`, `docs/screen-map.md`, `docs/user-journey.md`, `docs/prd.md`, and `docs/guardrails.md`;
- the content hash of each input and the approved locale/viewports/state coverage;
- the resolved absolute paths and hashes for `design-source-manifest.json` and `codex-access-receipt.json`;
- the exact authorized path for `claude-source-read-receipt.json`;
- a complete, one-line-per-item inventory of every required and optional design material: `material_id`, kind, exact location or capture path, required flag, purpose, access mode, and observed hash/capture ID;
- an explicit instruction to open/read every required material before candidate generation and return `claude-source-read-receipt.json` with one result for every `material_id`;
- an explicit instruction to use `working_language` for all explanations, candidate names, review text, and specification-facing copy, while using only source-backed product locales for product UI/content;
- for Ukrainian, an explicit instruction not to leave ordinary headings, prose, controls, or statuses in English and not to literal-translate English phrasing; only the recorded exception classes and approved IT terms may remain English;
- an instruction to create exactly three meaningfully distinct, equivalent-scope, interaction-simulated visual candidates in Claude Design;
- the Phase 2 boundary: no production backend, auth, persistence, provider calls, integrations, repository mutation, or production-source writes;
- an instruction that the operator selects one exact candidate/version in Claude Design before export;
- an instruction that, after selection, Claude Design directly exports only that selected version as a self-contained folder or standalone HTML under the exact inbox path and writes nowhere else in the project;
- a return instruction in `working_language`: report `handoff_id`, selected candidate/version, export shape, and exact export path, then tell the operator to return to Codex and resume that handoff.

Claude Design may read the frozen inputs and source materials named in the prompt. It may not edit them, the manifest, receipts, production code, other candidates, or any project path outside its selected-export directory and the authorized handoff-receipt path. It must stop and return the inaccessible `material_id` values instead of guessing or silently replacing a required source.

## Transport Resolution

Prefer direct Claude Design export to the inbox. If direct export is unavailable, report that capability as unavailable and choose the first authorized viable fallback; do not silently switch design generation to Codex:

1. `codex_assisted_import`: the operator identifies the exact existing local export path, and Codex copies/imports it into the inbox after resolving and validating that exact source.
2. `manual_transfer`: when no direct or Codex-assisted transfer is possible, give the operator the exact source and inbox destinations and allow the operator to transfer the selected export. Do not imply that manual transfer is forbidden or that it is the normal path.
3. `authorized_url_capture`: when the operator supplies or authorizes a stable export URL, Codex captures it into the inbox and records the URL receipt without treating the URL as the durable baseline.

If required source access is missing, remain at `awaiting_design_source_access` before candidate generation. If source access is complete but no transfer path is currently possible, remain at `awaiting_export_transfer`, preserve the handoff, and state the unavailable capabilities and next viable action. Never ask the operator to recreate files by copying snippets from chat.

## Codex Return Validation

On resume, Codex must:

1. validate the Claude source-read receipt against the exact manifest hash and language record, and require one successful read result for every required `material_id`; otherwise remain at `awaiting_design_source_access`;
2. resolve the selected export beneath the handoff inbox and reject path escape, multiple selected versions, missing assets, external runtime dependencies, secrets, executable backend behavior, or production-source writes;
3. normalize the selected export into a new immutable candidate/version under `forge/design/candidates/{candidate_id}/{version}/` and evidence under `forge/design/evidence/`;
4. apply the [freeze contract](freeze-contract.md); record input/receipt hashes, transport, origin `claude_design`, handoff ID, changed paths and validation evidence;
5. open the normalized candidate on the selected visible review surface (external default unless explicitly changed); verify routes, states, interactions, locale, assets, console and viewports;
6. enter `awaiting_design_approval` only after source-read, import, and visual validation succeed.

Claude Design selection identifies the import. Only an explicit whole-design approval of the exact normalized candidate/version in the active host permits `to-design-brief` to record the Approved Visual Baseline.
