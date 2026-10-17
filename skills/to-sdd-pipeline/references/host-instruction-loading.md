# Verify effective project instructions

Read during project instruction setup, host changes and implementation/resumption preflight. These are loading checks, not proof that an agent obeys instructions. Verify supported versions and current host behaviour before claiming compatibility; do not assume CLI and desktop parity.

## Codex

1. Identify the actual repository root, current working directory, configured Codex home and accessible instruction configuration. Inspect rather than change global settings.
2. Determine the selected instruction file at each applicable level. Codex selects the first nonempty supported file per directory: `AGENTS.override.md`, then `AGENTS.md`, then configured fallback names. Global instructions have their own selected file. Project discovery runs from the project root to the working directory; explicitly inspect relevant nested instructions before editing their files.
3. Account for the combined configured instruction byte limit, 32 KiB by default. A policy within the limit by itself can still be excluded or truncated by other loaded files. Do not increase a global limit automatically.
4. If an override excludes the shared policy, do not declare root-file creation successful setup. Inspect and reconcile the effective sources within authorized project-local scope. Do not delete or overwrite an override merely to make the policy load. If no acceptable loading arrangement is authorized, preserve the files and report the exact conflict or required decision.
5. Read the effective instructions for the current work. Codex normally builds its instruction chain at run/session startup; a file written during an existing session does not prove automatic rediscovery. Verify fresh-session discovery separately before claiming that entry path supported.

For an authorized CLI probe, use the installed CLI's supported instruction-inspection method; official documentation illustrates `codex --cd /project "List the instruction sources you loaded."`. Supplement a response with available host logs or source-loading evidence. Do not run paid or unbudgeted probes, change approval settings or launch unrelated app instances for this check.

Source: [OpenAI project instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

## Claude Code

1. Identify the actual version and active project-instruction setting. Native AGENTS.md loading starts at v2.1.277, with additional session/version conditions. Do not infer support from version alone.
2. Inspect project/ancestor `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md`, plus relevant nested files and rules. Under the default selection, a qualifying project/ancestor Claude instruction file suppresses direct AGENTS.md loading. User-global and managed CLAUDE.md have different roles; do not infer suppression merely from their existence.
3. Inspect the effective setting when exposed: `claude-md-or-agents-md`, `claude-md-and-agents-md`, `claude-md` or `managed-only`. Respect managed restrictions and do not modify global or managed settings.
4. When direct loading is unavailable or suppressed, use the minimum authorized project-local `CLAUDE.md` import of `@AGENTS.md`, preserving existing content. Avoid duplicate imports and cycles. A sentence suggesting the agent might read a file is not an automatic import. A managed restriction that excludes project instructions is not bypassed by adding a wrapper.
5. Claude does not directly read `AGENTS.override.md`. Inspect applicable Codex overrides for portability conflicts; importing AGENTS.md does not import an override's distinct restrictions. Resolve supported shared rules without silently weakening either host's restrictions.
6. Use `/context`, supported loading records or equivalent host evidence in an authorized fresh-session check. Check worker instruction inheritance separately, including workers configured to start without project instructions. Supply the relevant policy explicitly when required.

Source: [Anthropic memory and project instructions](https://code.claude.com/docs/en/memory).

## Record the actual result

In existing operational records, retain the host/version and entry path, selected policy revision, effective source paths/content identities, relevant settings or unavailable-setting limitation, resolved canonical document references, and verification method/result. Record current-session explicit reads separately from fresh-session automatic loading. Keep private instruction contents and credentials out of reports and version control; capture only permitted provenance.

A source inventory proves availability; a host loading record supports a loading claim; a task outcome supports a behavioural claim. Do not substitute one for another. If the host exposes no loading evidence, report the limitation and the observations available instead of asserting automatic discovery.

Recheck relevant sources after branch/directory changes, resumption or instruction changes. If rules conflict or required content is missing/suppressed, stop the affected start/action, resolve within existing authority and apply the six project pause reasons. This check grants no new authority and cannot enforce a billing cap or restart an ended session.
