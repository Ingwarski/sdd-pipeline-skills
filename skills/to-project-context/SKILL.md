---
name: to-project-context
description: Create or update project-context.md and canonical-terms.md after product discovery or PRD work, including as the project-context-bundle node in an orchestrated SDD pipeline. Use when the user wants to clarify product context, user personas, platform targets, constraints, domain vocabulary, canonical terms, or prepare stronger source-of-truth documents before user journeys, screen maps, wireframes, UX/UI briefs, guardrails, or implementation planning.
---

# To Project Context

Create two source-of-truth documents that make product work more deterministic:

- `project-context.md` - product context, users, platforms, constraints, assumptions, risks, and open questions.
- `canonical-terms.md` - approved vocabulary for the product, domain concepts, user roles, objects, states, actions, and terms to avoid.

Working-language contract: use the orchestrator-supplied `working_language`; in standalone use, prefer an explicit language request, otherwise use the language of the latest substantive user message. Use it for every question, playback, report, and all natural-language headings and prose in both owned artifacts. English headings below are semantic templates, not literal output strings.

For Ukrainian (`uk`), write natural, idiomatic Ukrainian. Keep English only in immutable filenames/paths, code and commands, machine-readable schema or enum values, API/identifier names, proper names or verbatim quotations, and established IT terms such as `SDD Pipeline`. Record every deliberately preserved English IT term with its Ukrainian meaning in `canonical-terms.md`; do not leave ordinary headings or prose in English and do not produce literal calques. Keep product content locales separate from `working_language`.

Default output path:
- Use `docs/project-context.md` and `docs/canonical-terms.md` when a `docs/` directory exists or when source documents already live in `docs/`.
- Otherwise use `project-context.md` and `canonical-terms.md` at the project root.
- If the user gives explicit paths, use those paths.

## Output Boundary

Create or update exactly one declared two-file output bundle:

- `docs/project-context.md`
- `docs/canonical-terms.md`

Use the root-level equivalents only when the project has no `docs/` convention or the user explicitly provides other paths. Do not modify any other artifact. The two files have separate content and validation results but one owner invocation; a missing or invalid member leaves the bundle incomplete.

## Source Discovery

Before asking questions, inspect the project and read existing product truth when present:

- `docs/product-idea.md`
- `docs/prd.md`
- `docs/user-journey.md`
- `docs/screen-map.md`
- `docs/design-brief.md`
- `docs/development-plan.md`
- `README.md`
- `CODEX.md`
- issue descriptions, project notes, or attached docs if provided by the user

If an answer is discoverable from project files, use the files instead of asking. Cite the source file in the output when useful.

### Pipeline Mode

When invoked by `to-sdd-pipeline`, this node runs immediately after the PRD. Read only:

- `docs/product-idea.md`
- `docs/prd.md`
- `README.md` and `CODEX.md`, when present
- explicit user decisions
- independent codebase or project evidence

Do not read downstream SDD artifacts back into these two upstream context files in pipeline mode. In particular, do not use user journeys, screen maps, wireframes, design briefs, architecture, guardrails, DoD/evals, QA, prototypes, or development plans as upstream sources. This keeps the dependency graph acyclic. Standalone update requests may inspect existing downstream files only when the user explicitly asks to reconcile context from them.

## Grill-With-Docs Mechanics

Use the Matt Pocock-style grilling approach, adapted for documents:

1. Walk the product context decision tree branch by branch.
2. Resolve dependencies in order: product purpose -> users -> platforms -> core scenarios -> constraints -> terms.
3. Ask only one question at a time when information is missing and blocking.
4. For every question, include a recommended answer based on the evidence.
5. Do not ask questions that can be answered by reading the project files.
6. Cite the source basis for the question, or say no source confirms the answer.
7. State what downstream artifacts or vocabulary boundaries change if the answer differs.
8. After the answer, play back the confirmed decision and consequences before continuing or returning to the orchestrator.
9. Do not create PRD, screen map, wireframes, code, or implementation outputs. A full `to-sdd-pipeline` invocation already authorizes the orchestrator, not this owner skill, to continue after this bundle validates.
10. Stop grilling once the documents can be created with clearly labeled assumptions.

## Context Decision Tree

Clarify these areas, using documents first and questions only when needed:

0. Working language and product locales
   - working language for interaction, reports, and SDD artifact prose
   - source of the language decision
   - explicitly required product UI/content locales, if different
   - deliberately preserved English IT terms and their Ukrainian meanings

1. Product identity
   - product name
   - product category
   - one-sentence purpose
   - desired user outcome

2. User personas
   - primary user
   - secondary users, if any
   - user skill level
   - user motivation
   - user pain points
   - decision maker vs end user, if different

3. Platform targets
   - web, mobile web, iOS, Android, desktop, browser extension, API, admin tool, or other
   - primary device and viewport assumptions
   - accessibility or localization requirements
   - hosting/deployment constraints, if known

4. Product boundaries
   - MVP scope
   - out-of-scope features
   - non-goals
   - risky assumptions
   - dependencies on external services

5. Operational constraints
   - payment, privacy, personal data, auth, roles, admin access, notifications, analytics, legal, or compliance constraints
   - content, language, geography, brand, or provenance restrictions
   - technical constraints that affect product decisions

6. Canonical terms
   - user-facing labels
   - internal domain terms
   - entities and objects
   - roles
   - states
   - actions
   - terms to avoid
   - synonyms that must collapse into one canonical term

## Output: project-context.md

Create or update `project-context.md` with this structure:

```markdown
# Project Context

## Working Language And Product Locales

## 1. Product Summary

## 2. Product Purpose

## 3. Target Users

## 4. User Personas

## 5. Main User Problems

## 6. Desired User Outcomes

## 7. Platform Targets

## 8. Core Scenarios

## 9. MVP Boundaries

## 10. Out of Scope

## 11. Constraints

## 12. Assumptions

## 13. Risks

## 14. Open Questions

## 15. Source Notes
```

Keep the document concise, decision-useful, and grounded in source files. Label inferred content as assumptions.

## Output: canonical-terms.md

Create or update `canonical-terms.md` with this structure:

```markdown
# Canonical Terms

## Working Language And Preserved IT Terms

## 1. Product Name

## 2. User Roles

## 3. Core Domain Objects

## 4. User Actions

## 5. Product States

## 6. Screen / Flow Names

## 7. Approved User-Facing Terms

## 8. Internal Terms

## 9. Synonyms to Normalize

## 10. Terms to Avoid

## 11. Open Vocabulary Questions
```

For each important term, prefer this format:

```markdown
### Canonical Term
- Meaning:
- Use when:
- Avoid:
- Notes:
```

## Rules

- Preserve existing useful content when updating files.
- Do not invent product logic silently.
- Do not add features outside the existing product scope.
- Do not write application code.
- Do not create frontend components.
- Do not create PRD, screen map, wireframes, UX/UI brief, or implementation plan unless separately asked.
- Apply the working-language contract to headings, prose, questions, playback, and reports; treat the English structure labels above as translatable semantics.
- When `working_language: uk`, language-edit both artifacts for idiomatic Ukrainian, ordinary-English leakage, and calques before validation.
- Keep filenames, paths, code, commands, machine values, API/identifier names, proper names, verbatim quotations, and approved English IT terms unchanged.
- Record each approved English IT term in `canonical-terms.md` with its Ukrainian meaning and usage boundary; do not preserve ordinary English merely because an upstream template used it.
- Do not confuse working language with product locale; preserve an explicitly source-backed UI/content locale separately.
- If authoritative sources conflict materially in standalone mode, report the conflict and ask which source wins. In pipeline mode, return `upstream_reconciliation_required` so the orchestrator can re-invoke the owning upstream skill; do not edit the PRD from this skill. Normalize non-material vocabulary differences to explicit upstream wording, record aliases or assumptions, and continue without creating an approval gate.
- If information is missing but not blocking, proceed with a clearly labeled assumption.
- If information is blocking, ask one question and wait.

## Pipeline Return Contract

When invoked by `to-sdd-pipeline`:

- write both declared files in one owner invocation;
- return both paths, their independent validation results, residual open questions, and one shared owner-invocation ID;
- treat assumptions and non-blocking open questions as visible context, not approval gates;
- pause only for a genuinely non-inferable decision that materially changes product scope or a high-risk operational boundary;
- return control immediately after validation so the orchestrator can hash both files and dispatch downstream owners.

## Verification

After creating or updating files:

1. Re-read both output files.
2. Check that `project-context.md` records working language, product locales, users, platforms, constraints, assumptions, risks, and open questions.
3. Check that `canonical-terms.md` records every deliberately preserved English IT term and its Ukrainian meaning when the working language is Ukrainian.
4. Check that `canonical-terms.md` includes approved terms, synonyms to normalize, and terms to avoid.
5. When pipeline-invoked, confirm that both files came from the same owner invocation and neither depends on a downstream SDD artifact.
6. Run `git diff -- <output files>` when in a git repository.
6. Report changed files and unresolved questions.
