---
name: write-judge
description: >
  Create a binary pass/fail LLM judge in Neens for ONE confirmed failure mode, run it on real
  traces, and check it against the user's own verdicts before it scores anything automatically or
  gates a release. Use when a failure mode needs an automated check, when the user asks for a
  judge, scorer or evaluator, or when a judge's verdicts are in doubt. Do NOT use for failures a
  plain filter already catches (errors, a missing tool call); see Step 2.
---

# Write Judge

A judge is only worth running if it agrees with the person who owns the agent. This skill writes a
narrow pass/fail judge for one failure mode, then measures it against that person's verdicts.
It does not switch the judge on for every trace until it has passed that check.

## Prerequisites

- A confirmed failure mode, ideally with labeled examples from `triage-failures`.
- The project has an LLM connection for judges, backed by a capable model. A judge grading a
  whole trajectory needs at least the model class the agent itself runs on. If `run_eval` fails
  with a connection or credential error, the user must add one in **Settings → LLM connections**.

## Step 1: Reuse before you create

Call `list_judges` with a `q` naming the failure. If a judge already targets it, go to Step 5 and
check that judge instead of writing a duplicate.

## Step 2: Is a judge the right tool?

Neens already records trace status, errors, tool calls and latency. If the failure is mechanical,
such as a tool returning an error, a required tool never being called, or a timeout,
`list_traces` filters (`status`, `tool_name`, `min_duration_ms`) already measure it exactly, and an
LLM judge only adds cost and noise. Say so and stop.

Write a judge when catching the failure takes judgment: an answer not supported by the tool
results, the wrong action for the request, a missed policy step, the wrong tone for the context.

## Step 3: Write the prompt

One failure mode per judge. The verdict is binary. The prompt has four parts:

```text
You are checking one thing: <the failure, in one sentence>.

PASS when: <observable behavior, drawn from the confirmed passing traces>.
FAIL when: <observable behavior, drawn from the confirmed failing traces>.
Judge only this criterion. Other problems in the trace do not change the verdict.

Examples:
<one clear FAIL, one clear PASS, and one borderline case, each a few lines with a short critique>

Trace:
{target}

Write your critique first, citing the exact evidence from the trace, then decide.
Return only JSON: {"reason": "<critique>", "score": <1 for PASS, 0 for FAIL>}
```

- `{target}` is where Neens inserts the trace. Keep it.
- Draw the examples from the triage evidence, shortened, with names and identifiers removed.
  Remember which traces you used; they must not appear in the check in Step 5.
- Critique first, then score. Deciding first and justifying afterwards produces worse verdicts.
- `required_data`: only what the criterion needs. Use `["input", "output"]` for answer quality,
  and add `"messages"` when the verdict depends on tool calls or tool results.

## Step 4: Create, deploy, run

1. `create_judge` with `name` (for example `fm-<failure-slug>`), `description`, `prompt_template`,
   `required_data`, and `scope: "trace"`.
2. `deploy_judge` with `{"judge_id": …, "trigger_policy": "manual", "success_threshold": 0.5}`.
   Keep it manual until Step 6.
3. `run_eval` with `{"judge_id": …, "sample_size": 30}`. It scores the 30 most recent eligible
   traces. If the reply is not terminal yet, poll `get_eval_run` until it is.
4. `get_eval_run` with `{"run_id": …, "limit": 50}`. Count the verdicts yourself: `score` 1 is a
   pass and `score` 0 is a fail.

`successRate` in the run is the share of tasks that finished scoring. It is not the pass rate.
Never report it as one.

Read five of the reasons. If a reason contradicts its score, for example "no fabrication found"
with a score of 0, the verdicts cannot be trusted. That usually means the judge's model is too
small for the task, not that the prompt is inverted. Check which model the project's judge
connection uses, and recommend a stronger one before going further. Do not call the prompt
backwards unless its PASS and FAIL definitions actually are.

If fewer than 5 traces were failed, the recent sample holds too few examples of this failure to
check the judge. Say so and ask the user whether to run a larger `sample_size`.

## Step 5: Check the judge against the user

1. From the run's tasks, choose up to 10 the judge failed and up to 10 it passed. Leave out the
   traces you used as prompt examples.
2. Show them to the user in batches of five, numbered. For each one, show a compact summary built
   from `get_trace`: the user's request, the tool calls and their results, and the final answer.
   **Do not show the judge's verdict or reason.** Seeing it first anchors the reviewer. If
   `get_trace` has no `conversation` (older Neens versions), give the reviewer the trace ids and
   ask them to review each one in the Neens UI.
3. Ask for pass or fail on this one criterion, for example "1 pass, 2 fail, 3 pass …".
4. Record each answer with `add_annotation`:
   `{"target_type": "trace", "target_id": …, "verdict": "pass"|"fail", "critique": "<their reason, if given>", "is_gold": true}`.
   Neens also uses these labels in its own judge-alignment view.
5. Report both sides with counts, not only percentages:
   - **False alarms**: of the N traces the judge failed, how many the user passed.
   - **Misses**: of the M traces the judge passed, how many the user failed.

Target: at most 1 wrong in 10 on each side. Minimum to use it at all: 2 in 10. With 10 per side,
one disagreement moves the rate by 10 points, so present the counts next to the percentages.

## Step 6: Iterate or ship

**It misses the bar.** Read every disagreement with the user. A false alarm means FAIL is defined
too broadly; a miss means PASS is too lenient or an example is misleading. Change the definitions or
the examples, not the output format. MCP cannot add a version to an existing judge, so create
`<name>-v2` with `create_judge` and repeat Steps 4 and 5 on fresh traces. Ask the user to disable
the old deployment in the Neens UI (**Judges**) so the two do not both score.

**It meets the bar.** Ask the user before making it continuous: every new trace becomes one judge
call, and that costs money. On a yes, call `deploy_judge` with
`{"judge_id": …, "trigger_policy": "on_new_trace", "success_threshold": 0.5}`.

## Report

- The judge name and id, and the failure mode it checks
- The measured false alarms and misses, as counts and rates
- Whether it is manual or continuous
- Next step: `gate-release` or `fix-failure`, which use this judge as proof

## Anti-patterns

- **One judge for "quality".** A verdict on everything tells you nothing about what to fix.
- **1–5 scales.** Nobody can say what separates a 3 from a 4, and the judge cannot either.
- **Trusting a judge nobody checked.** An unchecked judge on a release gate blocks good changes
  and passes bad ones, with confidence.
- **Showing the reviewer the judge's answer first.** Then you are measuring agreement with
  yourself.
- **Checking on the prompt's own examples.** That is guaranteed agreement and measures nothing.
