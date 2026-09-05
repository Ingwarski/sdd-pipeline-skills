---
name: to-user-journey
description: Map a source-backed user journey, real-session context, decisions, friction and outcomes from the PRD before screen design.
---
# to-user-journey

Read the [shared operating rules](../to-sdd-pipeline/references/common-contract.md) before work; resolve the link from this SKILL.md's real directory, not the open project. Preserve `working_language`, source truth and approval boundaries.

## Inputs

Required before starting: `docs/prd.md` and `docs/guardrails.md`; in pipeline mode also the validated `docs/project-context.md` and `docs/canonical-terms.md` bundle.

Optional grounding: README, explicit decisions and relevant confirmed context/terms. Use the PRD's `UC-*` and referenced upstream `JOB-*` definitions; do not redefine them.

## Output and ownership

Write only `docs/user-journey.md`. Own the user's context, goal, motivation, stages, actions, decisions, friction/fears, exits, success/failure, value moment and MVP journey risks.

Do not define routes or a screen inventory, internal layouts, visual style/tokens, QA items or implementation tasks. System-facing use-case paths remain in the PRD.

## Workflow

1. Read sources; identify the primary user and material JOB/UC coverage.
2. Describe the real session: situation, trigger, device/environment, time/attention pressure and stakes. Use a named protagonist only if confirmed; otherwise use the role and record any material gap.
   Carry source/confidence on important assumptions. Observed task failures return to the affected journey and upstream use case; an operator hypothesis is not user research. For headless scope, describe the operator/system task without inventing screens.
3. Map entry-to-completion stages as numbered steps. Each stage records user action, decision, relevant friction/trust concern and outcome.
4. Name the value moment or central friction (`climax beat`), failure/recovery path and safe exits.
5. Trace the journey to source requirements and JOB/UC IDs without copying their definitions. Add no unsupported persona, feature or goal.
6. Check that the user can reach the stated success outcome and that every material source obligation is covered or an explicit open question.
   Preserve applicable PRD security IDs in sensitive actions, permission failures and recovery; a changed flow cannot silently remove a required authorization or confirmation boundary.
7. Write only the journey. Use a Mermaid journey diagram only when it clarifies the flow; keep the text understandable alone.

A missing detail blocks only when it materially changes scope or a high-risk boundary; otherwise record the smallest reversible source-grounded interpretation.

## Artifact coverage

Required semantic sections: Source References; Primary User; User Goal; Starting Context; Journey Stages; Success State; Open Questions.

Include stakes, a journey overview, value moment, decisions, friction/risks, failure/recovery and exits where applicable. Put JOB/UC references beside the overview or stages, not in a duplicate use-case narrative.

## Return

Report the file, changed journey decisions, coverage/evidence, open questions and next owner. Follow the shared provenance contract; no intermediate approval.
