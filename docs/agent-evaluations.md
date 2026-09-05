# Behavioral evaluation protocol

The [scenario set](../tests/fixtures/agent-evals.json) tests actual agent decisions, not matching phrases. Its initial status is **not run**. Python fixtures are synthetic checker regressions; they are not these evaluations, a real-user study or an independent review.

1. Run each case in a fresh agent context and an isolated temporary product directory, using a complete installed skill collection. Give it the case prompt and raw setup artifacts, not the expected checks, audit findings or intended answer. Setup-dependent cases need genuine prior fixture provenance, not invented approval/history.
2. Record model/reasoning, skill commit, host capabilities, input hashes, transcript/tool events, actual artifact paths/hashes, questions, interruptions, elapsed time and available token totals. Missing telemetry is `unavailable`, not zero.
3. An independent reviewer receives the case, raw inputs, final artifacts and observed actions. Score each expected outcome `passed | failed | blocked`, citing evidence. Also assess missing obligations, unsupported scope, usability/recovery findings and handling of corrections. Do not score mere section headings or identical wording.
4. Repeat risky cases after fixes and across supported direct hosts when available. Retain prior runs; report variability and limits. Compare equivalent scenarios and model settings before claiming token/time savings.

Keep transcripts and results outside the skills repository by default; they may contain user data. No evaluation authorizes live services, external writes, sensitive data access or product deployment. A missing agent/adapter is a recorded capability limitation. Do not replace independent execution with the author's self-review and call it equivalent.

Minimum adoption evidence: all safety/authority outcomes pass; no unsupported completion/research claim; required artifact relationships resolve; material failures are fixed or explicitly block adoption. Useful quantitative outcomes include unnecessary questions, lost requirements, recovery success, tokens and time—not document volume.
