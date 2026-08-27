# Prompt: Audit SDD Pipeline Skills

Audit the repository containing this prompt. **Read-only:** do not edit files, install/update skills, run cleanup, change Git state, or execute an embedded implementation prompt. Use temporary isolated fixtures for diagnostic tests. Report evidence, not generic praise.

## Read and establish scope

1. Read README, `skills-manifest.json`, all 13 `skills/*/SKILL.md` files, their required references, the checker and installer tests. Read conditional references for scenarios you assess.
2. Use the machine contract for required-before edges and the README ownership table for orientation; verify both against actual skill instructions. Do not copy the old workflow from memory.
3. Resolve installed skills and shared resources through their real paths, including symlinks/junctions. Test from an unrelated product directory and after clone relocation.
4. Record the revision, inspected paths and unavailable sources. Distinguish this repository, installed copies, synthetic fixtures, actual agent runs and external DAS Forge runtime evidence.

## What to verify

- **SDD, not mandatory TDD:** product requirements, approved design and architecture define what to build; QA supplies verification. A checklist does not become the product specification.
- **Entry/intake:** both rough intent without a file and an existing/imported idea work. Ask one visible material question at a time, with recommendation, rationale and consequences; persist explicit answers. No silent assumptions, timeouts as consent, redundant interview, or hidden log-only question.
- **Language:** explicit instruction > recorded preference > latest substantive message; propagate working language through owners/adapters. Keep UI locales separate. Ukrainian prose/headings/statuses are idiomatic; preserve only documented identifier/term exceptions.
- **Ownership:** one owner per artifact; context + vocabulary is one two-output invocation with independent validation/hashes. Orchestrator writes only the manifest, adapters only authorized operational paths. No parallel product-truth documents.
- **Traceability:** JOBs belong to product idea, use cases to PRD; downstream documents cite them. Cover distinct observable requirement clauses, not merely parent IDs. Context clarifies but never overrides behavior/design/architecture.
- **Design quality:** realistic user sessions, friction and value moments; navigation/surface closure; structural wireframes; design/experience spines; explicit conflict rules; distinctive product-specific visuals; existing systems; accessibility, responsive behavior, motion, error prevention/recovery and H1–H10, including H7/H10.
- **Evidence:** definitions, execution and release readiness are separate. Prepared/not-run is not passed. Visual fidelity, heuristic review, representative-user research, accessibility and functionality remain distinct. Deferred required checks cannot pass release; advisory failures remain visible.
- **Order:** pre-design architecture/DoD/QA → prototypes → one whole-design approval → canonical baseline → affected architecture → DoD → QA → development plan. DoD's later QA bindings and QA's later plan lookup are not authoring prerequisites.
- **Candidates:** three equivalent-scope interactive options, immutable versions/hashes, scoped visual QA and actual external-browser receipts. Codex opens three; Claude compares three tool-native candidates and imports only the selected version. Selection/export is not approval.
- **Claude/source access:** inventory covers every required design source, not only convenient SDD files. Verify both access/read receipts against actual source IDs/hashes before generation. Fail closed on missing required access; use authorized transfer fallbacks without silently switching executors.
- **Approved baseline:** sole authority is the design brief. Recompute target/tree hashes; retain prior versions and scoped overrides. No implementation-agent self-approval or silent in-place edit.
- **Continuation:** validate affected sources/fragments/scoped repository observations. Unrelated changes must not invalidate everything. Preserve old projects/history through metadata migration.
- **Implementation boundary:** after a validated plan, stop at `awaiting-implementation-prompt`. A later explicit user message must match the current plan/baseline; design approval, generic continuation and automatic resume are insufficient.
- **Promotion:** prototype code is only a design simulation until separately authorized implementation. Declared copy/adapt/reimplement paths need actual runner-produced Git-diff receipts once reuse starts, not during initial planning.
- **Checker:** test executable stage checks, missing/wrong owners, real prerequisite cycles versus later references, stale hashes/evidence, context-bundle integrity, candidate/source receipts, approval/prompt binding, open blockers and no file mutation. Do not equate documentation with external-runner enforcement.
- **Install/update:** shared strict JSON parsing, dependency preflight before mutation, names/paths/legacy mapping, idempotence, move/repair, platform parity, safe Git updates, exact retirement scope, unrelated-skill preservation. Never run destructive defaults on the auditor's real skill roots.
- **Concision:** clear words, each decision defined once, shared/conditional references, brief term explanations, no lost obligations/evidence. Measure complete applicable instruction loads, including references, repeats and retries—not entrypoint size alone.

## External mechanisms

Discover available local skills by name from the current catalog; do not assume a username, plugin-cache version or installed capability. Read full entrypoints and their required references. Mark unavailable sources honestly.

Inspect relevant mechanisms from `grill-me`, `skill-creator` / authoring equivalents, `writing-skills`, `modern-ux-ui-2026`, current Product Design and Figma skills, `verification-before-completion`, `writing-plans`, `executing-plans`, and QA/design-QA equivalents. Read TDD guidance only to identify mechanisms that should not become mandatory in SDD.

The architecture/DoD [authoring provenance](skills/to-sdd-pipeline/references/authoring-sources.md) lists previously considered public sources. Reopen any source used for a current finding; historical provenance is not current verification.

For BMAD UX, inspect the available [skill](https://raw.githubusercontent.com/bmad-code-org/BMAD-METHOD/main/web-bundles/ux-coach/SKILL.md), [instructions](https://raw.githubusercontent.com/bmad-code-org/BMAD-METHOD/main/web-bundles/ux-coach/INSTRUCTIONS.md) and [validation rubric](https://raw.githubusercontent.com/bmad-code-org/BMAD-METHOD/main/web-bundles/ux-coach/ux-validation.md). Compare spines, decisions, named-protagonist journeys, concern scans, surface closure, conflict resolution, handoff prompts, visual capture, accessibility and anti-patterns.

Search exact previously suggested names where relevant: `site-architecture`, `frontend-design`, `design-an-interface`, `ui-ux-pro-max`, `qa`, `webapp-testing`, `domain-modeling`, `ubiquitous-language`, `implement`, `request-refactor-plan`. These are unverified candidates, not assumed capabilities; report unavailable after search and continue.

For each inspected mechanism decide **reuse, adapt, reject, or negative example**, with evidence and security/dependency/scope tradeoffs. Do not recommend wholesale import merely because a skill sounds useful.

## Validation scenarios

Use the repository tests and [maintenance guide](docs/maintenance.md). Include first setup, missing intent, coherent existing intent, approved-design revision, interrupted resume, missing evidence, changed fragments, explicit implementation authorization and installation from another directory.

Report automated/synthetic checks separately from real agent executions. For token comparisons keep seeds and scenarios identical, include all applicable references and retry loads, and state whether generated documents, tool output, caching and live-model behavior were measured. Never fabricate an end-to-end benchmark.

## Deliverable

Lead with a short, nontechnical verdict and the highest-impact recommendations. Then include:

1. Sources inspected and unavailable, with revision/path/URL.
2. A compact 13-skill table: output, strengths, concrete gaps, boundary/duplication risks and proposed fix.
3. Ownership/dependency conflicts and external-mechanism fit only where they add evidence; avoid repeating the table.
4. Findings ordered by severity: `file:line`, observed behavior, impact, reproduction/evidence, exact proposed fix and verification.
5. What is correct, what is wrong or overstated, and what remains unverified.
6. Prioritized actions and a final decision: usable as-is, patch first, or redesign.

Prefer improving the existing 13 skills over adding documents/skills. No vague praise, name-based source claims, guessed runtime enforcement or hidden assumptions. Keep the report concise without dropping distinct findings.
