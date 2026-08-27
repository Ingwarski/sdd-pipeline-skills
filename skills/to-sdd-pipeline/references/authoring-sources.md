# Authoring Provenance

Historical influences, not runtime dependencies or product truth. Do not fetch these simply to run an SDD owner.

## to-architecture

These references were used to design this skill. They are not product source files for a project run; product truth still comes only from the Input files and explicit user answers.

- `tad-generator`: `https://github.com/luongnv89/skills/blob/main/skills/tad-generator/SKILL.md`
  - Used: PRD extraction, architecture clarification, system overview, Mermaid diagram, stack/components/data/infrastructure/security/performance/risk coverage, artifact acceptance checks.
  - Not used: `tad.md` output path, automatic git sync/commit/push, README index updates, startup cost defaults, and forced stack assumptions.
- `documentation-and-adrs`: `https://github.com/addyosmani/agent-skills/blob/main/skills/documentation-and-adrs/SKILL.md`
  - Used: document why, alternatives considered, decision consequences, ADR-style decision log.
  - Not used: separate ADR file workflow under `docs/decisions/`, because this skill creates one artifact only.
- `breakdown-epic-arch`: `https://github.com/github/awesome-copilot/blob/main/skills/breakdown-epic-arch/SKILL.md`
  - Used: high-level architecture specification shape, Mermaid architecture diagram, technical enabler thinking.
  - Not used: hard-coded TypeScript/Next.js/tRPC/Turborepo/Docker/Stack Auth assumptions and epic-specific output path.
- `eatmycode`: `https://github.com/xwings/eatmycode`
  - Used: durable architecture documentation as a future-agent alignment surface.
  - Not used: multi-file `ARCHITECTURE.md` plus `ARCHITECTURE/<module>.md` structure, because this pipeline uses one output artifact per skill.
- Existing local SDD skills in this repository:
  - `skills/to-guardrails/SKILL.md`
  - `skills/to-development-plan/SKILL.md`
  - Used: Universal SDD Rule, one-artifact output contract, artifact boundary format, source-backed/open-question behavior, and Final Report shape.

## to-dod-evals

These references were used to design this skill. They are not product source files for a project run; product truth still comes only from the Input files and explicit user answers.

- `definition-of-done`: `https://raw.githubusercontent.com/addyosmani/agent-skills/main/references/definition-of-done.md`
  - Used: acceptance criteria vs Definition of Done distinction, standing reusable DoD, correctness/quality/integration/documentation/ship-readiness sections, and red flags against declaring done too early.
  - Not used: one-size-fits-all checklist as final content; project-specific source files still decide what belongs in `docs/dod-evals.md`.
- `quality-run-quality-gates`: `https://github.com/dawiddutoit/custom-claude/blob/main/skills/quality-run-quality-gates/SKILL.md`
  - Used: gate detection mindset, pass/fail reporting, rerun-after-fix loop, and "Definition of Done met/not met" blocking semantics.
  - Not used: command-runner behavior, tool-specific scripts, or executing gates during artifact creation.
- the installed `verification-before-completion` skill available during authoring
  - Used: evidence before claims, identify/run/read/verify gate function, no completion claim without fresh evidence.
  - Not used: runtime execution as the artifact output; this skill writes the reusable DoD/eval contract.
- `breakdown-plan`: `https://github.com/github/awesome-copilot/blob/main/skills/breakdown-plan/SKILL.md`
  - Used: DoD at multiple planning levels, acceptance criteria plus Definition of Done, dependency and gate thinking.
  - Not used: GitHub project automation, issue hierarchy output, sprint/project-management artifacts.
- Hermes eval/lane-gate proposal: `https://github.com/NousResearch/hermes-agent/issues/44000`
  - Used: eval definitions attached to lane/state transitions, standard eval result shape, quality contract over agent self-assessment.
  - Not used: Hermes-specific architecture, cron/memory/CLI implementation proposals.
- Existing local SDD skills in this repository:
  - `skills/to-guardrails/SKILL.md`
  - `skills/to-qa-checklist/SKILL.md`
  - `skills/to-development-plan/SKILL.md`
  - Used: Universal SDD Rule, one-artifact output contract, evidence policy separation, artifact boundaries, severity/release-readiness separation, and Final Report shape.
