# Seven-Step Communications Framework

This reference distills the seven-step method from the canonical presentation `Ефективна Комунікація full.key`. Use the questions as a diagnostic system, not as seven mechanical report chapters.

## Canonical dimensions

| # | Dimension | Canonical question | Audit interpretation |
|---|---|---|---|
| 1 | Communicator | Who are we? | Is the speaker's identity, authority, offer knowledge, point of view, value, and credibility clear and coherent? |
| 2 | Audience | Who are we addressing? | Does the communication reflect a specific audience's situation, priorities, language, objections, knowledge, and decision role? |
| 3 | Desired Effect | What should happen? | Is the intended change in understanding, belief, feeling, or action explicit, realistic, and supported by a clear next step? |
| 4 | Message | What are we saying? | Is the central proposition clear, relevant, differentiated, credible, memorable, and supported by proof? |
| 5 | Channel | Where is it communicated? | Does the content fit the medium, device, format, placement, context, and audience expectations of the channel? |
| 6 | Timing | When does it reach the audience? | Does the communication align with the journey stage and the current market, industry, geographic, seasonal, regulatory, labor, or reputational context? |
| 7 | Execution | How is it communicated? | Do structure, hierarchy, tone, language, emotion, story, visuals, pacing, interaction, and CTA make the message easy to receive and act on? |

The two `Who` questions from the source method become Communicator and Audience. The two `What` questions become Desired Effect and Message. `Where`, `When`, and `How` become Channel, Timing, and Execution.

## Rating rubric

Score each applicable dimension with one integer:

| Score | Meaning | Evidence standard |
|---|---|---|
| 1 | Failing | Fundamentally absent, contradictory, misleading, or actively harmful to the intended effect. |
| 2 | Weak | Serious gaps dominate; the communication works only with substantial audience effort or prior knowledge. |
| 3 | Functional | The basics work, but inconsistency or important omissions limit effectiveness. |
| 4 | Strong | Clear and convincing with only bounded, non-critical improvements required. |
| 5 | Exemplary | Fully aligned, distinctive, credible, and unusually effective for the mandate and evidence available. |

Assign confidence separately:

- **High:** direct, repeated evidence and adequate context.
- **Medium:** sufficient evidence with one or more bounded assumptions.
- **Low:** limited evidence, missing performance data, or a material hypothesis that requires validation.

Confidence explains certainty; it never changes the score arithmetically.

## Default weight profiles

Use the closest profile as a starting point. Adjust weights when the communication mandate justifies it, state the reason, and keep the total at 100%.

| Dimension | Website / landing page | Sales deck / proposal / one-pager | Email / outbound | Ads / social | Brochure / collateral | Audio / video |
|---|---:|---:|---:|---:|---:|---:|
| Communicator | 10 | 10 | 10 | 10 | 10 | 10 |
| Audience | 20 | 20 | 20 | 20 | 20 | 15 |
| Desired Effect | 20 | 15 | 20 | 20 | 15 | 15 |
| Message | 20 | 25 | 20 | 20 | 25 | 20 |
| Channel | 5 | 10 | 10 | 10 | 10 | 10 |
| Timing | 10 | 5 | 10 | 10 | 5 | 10 |
| Execution | 15 | 15 | 10 | 10 | 15 | 20 |
| **Total** | **100** | **100** | **100** | **100** | **100** | **100** |

For a mixed campaign, define one transparent blended profile from its primary business objective. Do not average scores from unrelated artifacts without explaining the aggregation method.

## Timing applicability and research

Timing is applicable whenever journey stage or current external context could change how the communication is interpreted or acted on. Examples include an IT outsourcing offer during programmer layoffs, a financial offer during rate changes, a seasonal promotion, a new regulation, a crisis, or a reputational event.

When applicable:

1. Research the current situation on the web.
2. Prefer primary or authoritative recent sources.
3. Match sources to the relevant geography and industry.
4. Record an as-of date.
5. Cite each external claim.
6. Separate contextual research from competitor benchmarking.

When genuinely not applicable, mark Timing `N/A`, explain why, and reallocate its weight proportionally:

`effective_weight_i = original_weight_i / sum(original_weights_of_applicable_dimensions) * 100`

## Overall score

Normalize the 1–5 rating scale to 0–100, then apply effective weights:

`overall = sum(effective_weight_i * (score_i - 1) / 4)`

Round only the final result to the nearest whole number.

| Overall | Band | Interpretation |
|---:|---|---|
| 0–24 | Critical | Communication is fundamentally misaligned or damaging. |
| 25–49 | Weak | Material strategic or execution gaps suppress effectiveness. |
| 50–69 | Functional | The communication works but leaves meaningful value unrealized. |
| 70–84 | Strong | The communication is effective with focused improvements available. |
| 85–100 | Excellent | The communication is highly aligned, credible, and action-oriented. |

Never present the overall score without dimension scores, weights, confidence, evidence, and the audit scope.
