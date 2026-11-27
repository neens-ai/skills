---
name: investigate-regression
description: >
  Find out what changed when an agent in production got worse: a new agent version, a model or
  prompt change, a downstream service, or a shift in what users ask. Compares failure modes,
  judge scores and component errors before and after, attributes the regression to the change
  that caused it with trace ids, and sets Neens up so the same regression is caught in CI next
  time. Use when the user says quality dropped, complaints rose, a score fell, "something broke
  after Tuesday's deploy", or asks what changed. Do NOT use before a change ships (`gate-release`)
  or for a failure that has always been there (`triage-failures`).
---

# Investigate Regression

Find the change behind a drop in quality, and prove it from the traces before anyone rolls back
or patches. A regression is a difference between two windows or two versions, so every claim
here is a comparison with its sample size.

Neens tools are called by their bare names here (`list_traces`). Your client may prefix them, for
example `mcp__neens__list_traces` in Claude Code.

## Step 1: Read what changed

Call `get_current_project`, then in parallel:

- `get_action_inbox` with `{"range": "7d"}`: what changed against the previous 7 days (new
  failures, regressions, anomalies) and the ranked rows. Quote its `lead` sentences rather than
  recomputing them.
- `list_failure_modes` with `{"range": "7d"}`: modes flagged `isNew`, and each mode's traces in the
  window against the window before.
- `list_scores` with `{"range": "7d"}`: each score type's pass rate and its period-over-period
  delta.
- `list_agent_versions` with `{"window": "30d"}`: which versions served when, and which one is live.

Ask the user when they first noticed and what they compare against, if they did not say. Pick the
two windows (or two versions) to compare and keep them fixed for the rest of the skill.

If one of these calls fails, name it in the report and work from the others. If the inbox and
the failure modes both show nothing new for the window, there is no regression to attribute: say
so and stop.

## Step 2: Is it real?

Before attributing anything, check the drop is larger than the noise:

- Every rate gets its counts: "pass rate 71% (142 of 200) against 88% (176 of 200)". A drop from
  2 of 3 to 1 of 3 is not a regression.
- A score type whose `scoredCount` fell sharply may have changed what it samples, not what the
  agent does. Check the counts before the rates.
- Traffic mix: if one kind of request grew, the failure rate can rise with no change to the agent.
  Compare the regressed failure mode's share against its own traffic.

If the drop is inside the noise, say so and stop.

## Step 3: Attribute it

Check each candidate. Stop at the first one the evidence proves; more than one can be true.

| Candidate | Evidence | How to check |
|---|---|---|
| **A new agent version** | The regressed failure mode or failing score sits mostly in one version | `get_failure_mode` on the regressed mode: its version distribution compares members per version with each version's traffic. For a score: `list_traces` with `{"version": "<v>", "score_metric": "<key>", "score_status": "fail", "limit": 1}` and the same without `score_status`, per version, gives each version's fail rate with counts |
| **A model change** | The failures concentrate on one `model` | The same `list_traces` counts with `model` set |
| **A downstream service** | A tool, MCP server or sub-agent's error rate rose; the agent called it correctly | `list_components` for this window and the previous one; `get_component` for its recent errors |
| **A prompt change with no version label** | The failures start at a time, not a version; `get_trace` on a before and an after trace shows a different system prompt | `lint_prompt` with `{"trace_id": "<after trace>"}` to see the prompt that ran; ask the user what shipped |
| **Different traffic** | The new failures come from a kind of request the agent rarely saw before | `get_trace` on new members; `list_traces` with `q` for the new topic, both windows |

Read the evidence: `get_trace` on two or three regressed traces and, for contrast, on a passing
trace of the same kind from before. Quote the step where the new behaviour first differs.

When an unversioned agent makes attribution guesswork, say so and recommend setting
`neens.version_label` on every span (`instrument-agent`): it is what turns "it broke on Tuesday"
into "it broke in v42".

## Step 4: Report

| What regressed | Before (n) | After (n) | Change | Cause | Evidence (trace ids) |
|---|---|---|---|---|---|

Then the options, for the user to choose:

- **Roll back** to the last good version, when one version clearly caused it. Neens does not
  roll back; the user's deploy process does.
- **Fix forward**: `triage-failures` on the regressed failure mode, then `build-regression-set`
  and `fix-failure`.
- **Downstream**: a ticket for the owning team with the component, its error rate before and
  after, and two trace ids.

## Step 5: Make it impossible to ship again

A regression that reached production is a gate that was missing.

1. `list_eval_gates` with `{"limit": 20}`. Was the regressed failure mode gated? If it was and the
   gate passed, its `warnings` say why (`judge_misses_failure`: the judge passes the failure
   itself). If it was not, a gate is the fix: `build-regression-set` on the regressed traces, a
   judge (`write-judge` or `write-code-judge`), then in the app the failure mode's **Create eval**
   → **Create eval gate** (https://app.neens.ai/docs/guides/eval-gates/). No tool creates a gate.
2. Offer a Scout standing instruction that reacts to new versions, with the user's yes:
   `create_standing_instruction` with
   `{"text": "When a new agent version appears, compare its failure modes and scores with the previous version and tell me what got worse", "condition_kind": "agent_version_seen"}`.

## Anti-patterns

- **A rate without counts.** Every before and after carries its n.
- **Blaming the last deploy by default.** Check the version distribution. Many regressions are a
  downstream service or new traffic.
- **Rolling back without evidence.** Name the version and show its fail rate against the one before.
- **Stopping at the fix.** A regression that shipped once ships again without a gate.
