---
name: to-project-context
description: Create the coupled project-context and canonical-terms documents after PRD discovery, clarifying users, platforms, constraints, working language and vocabulary.
---
# to-project-context

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve the link from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs and modes

Pipeline prerequisites: validated `docs/product-idea.md` and `docs/prd.md`. Optional grounding: README/CODEX, explicit decisions and independent repository/project evidence.

Never read downstream journey, screens, wireframes, design, architecture, guardrails, DoD, QA, prototypes or plans back into the bundle during a pipeline run. Standalone, inspect downstream files only when the user explicitly requests reconciliation from them; that lookup does not become a pipeline prerequisite.

Inspect sources before asking. Use one material question with a recommendation, source basis, consequences and playback only when the answer cannot be inferred safely.

## Output and ownership

Write exactly one coupled two-file bundle:

- `docs/project-context.md`
- `docs/canonical-terms.md`

Standalone, use root-level equivalents only if there is no `docs/` convention, or use explicit user paths. Pipeline paths stay canonical. Both files share one owner invocation and source set but have independent hashes/validation results; one missing/invalid member makes the bundle incomplete.

Context owns confirmed users/platforms/constraints, assumptions, risks and questions. Terms owns canonical vocabulary, meanings, aliases and names to avoid. Neither creates product behavior or overrides another owner's artifact. Do not write other documents or application code.

## Discovery and workflow

Resolve dependencies in this order, using sources first:

1. **Language:** working language and decision source; separate product content locales; deliberately preserved English IT terms and Ukrainian meanings when applicable.
2. **Identity:** product name/category, purpose and desired user outcome.
3. **Users:** primary/secondary roles, skill level, motivations, pain points, decision maker versus end user.
4. **Platforms:** surfaces, primary devices/viewports, accessibility/localization, source-backed hosting/deployment constraints.
5. **Boundaries:** MVP, exclusions, non-goals, assumptions and external dependencies.
6. **Constraints:** payments, privacy/data, auth/roles/admin, notifications/analytics, legal/compliance, content/geography/brand/provenance, and relevant technical limits.
7. **Vocabulary:** product/domain objects, user-facing labels, internal terms, roles, states, actions, synonyms and prohibited aliases.

Preserve useful existing content and history. State each fact once; cite the PRD rather than repeating its requirements or use-case paths. Stop questioning when the bundle can be written with explicit non-material assumptions.

Material conflicts return `upstream_reconciliation_required` in pipeline mode; the upstream owner fixes them first. Standalone, ask which authoritative source wins when needed. Normalize non-material wording to explicit upstream terminology, recording aliases.

## Artifact coverage

`project-context.md` must cover working language/product locales, product identity/purpose, target users/personas, problems/outcomes, platforms, core scenarios, MVP/exclusions, constraints, assumptions, risks, open questions and sources. Combine overlapping sections; do not duplicate product summaries or scope prose.

`canonical-terms.md` must cover working language/preserved IT terms, product name, roles, objects, actions, states, source-backed screen/flow names, user-facing/internal terms, synonyms, terms to avoid and open vocabulary questions. Prefer a compact table: term → meaning/use → aliases to avoid → source. Preserve established technical identifiers.

For Ukrainian (`uk`), record every deliberately retained English IT term with its Ukrainian meaning and usage boundary. Language-edit both documents; ordinary headings/prose must be idiomatic Ukrainian, while machine identifiers and explicit product locales remain unchanged.

## Validation and return

Re-read both files; verify source grounding, language/locales, vocabulary and labeled assumptions. In pipeline mode verify the shared invocation/source set and absence of downstream dependencies. Inspect the scoped diff when Git is available.

Return both paths, independent hashes/results, one shared invocation ID, exact consumed sources and unresolved questions. Assumptions and playback do not create approvals. Return to the orchestrator immediately; it records provenance and dispatches later owners.
