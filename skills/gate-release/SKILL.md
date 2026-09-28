---
name: gate-release
description: >
  Decide whether a candidate agent version (a branch, a prompt change, a model or config change)
  is safe to ship: replay the project's frozen golden and regression sets against it in a Neens
  pre-prod run, compare it with the current version, explain every regression from the
  trajectories, and return GO, NO-GO or NO DATA with the evidence. Use when the user asks "can we
  ship this", wants a release gate or a CI check, or wants two candidates compared. Do NOT use to
  prove one specific remediation; that is `fix-failure`.
---

# Gate Release

Every failure you have fixed has a regression set. A release is safe when none of them come back
and nothing that passed before now fails. This skill runs that check against the candidate and
gives a verdict that cites its evidence.

## Step 1: Pin down the candidate

Get three things from the user or the repo:

1. **Version label**: `<branch>@<short sha>`, or a release tag.
2. **How Neens reaches it**, one of:
   - **Push**: Neens calls the candidate's HTTP endpoint. It needs a registered agent endpoint:
     an existing `agent_connection_id`, or one the user adds under **Settings → LLM providers →
     Agent endpoints**. The endpoint takes `{"input": …}` and returns `{"output": …}`, or is
     OpenAI-compatible.
   - **Runner**: the user's own harness runs each golden input and sends the traces. Use this when
     the candidate cannot be exposed over HTTP. See Step 4.
3. **The baseline**: the version it replaces. The best baseline is a pre-prod run of the current
   production version on the same frozen set, because both sides then answer identical inputs.
   Use `list_preprod_runs` to find an existing one. The fallback is the production window
   (`baseline_kind: "prod_window"`), which is weaker because production traffic is not the golden
   set.

## Step 2: Choose what to replay and who judges

1. `list_datasets`. Take every regression set built from a fixed failure (those with a
   `clusterId`, or named `*-regression`) and the project's broad golden set, if it has one. Each
   dataset gets its own run.
2. `list_dataset_versions` on each. A dataset with no golden version cannot be replayed: freeze it
   with `create_golden_version`, or skip it and say that you skipped it.
3. `list_judges`. Pass `judge_deployment_ids` explicitly: the checked judges for these failures
   (from `write-judge`) plus the project's Primary Score deployment. Leave out judges nobody has
   checked against a person, and say which ones you left out.

## Step 3: Create and start the run (push)

For each dataset:

```json
{"name": "gate: <version label> on <dataset name>",
 "dataset_id": "<dataset id>", "version_label": "<branch>@<sha>",
 "runner_mode": "push", "agent_connection_id": "<conn id>",
 "judge_deployment_ids": ["<dep id>", "…"],
 "baseline_kind": "preprod_run", "baseline_run_id": "<baseline run id>",
 "min_pass_rate": 0.9, "max_regressions": 0}
```

`create_preprod_run` with that, then `start_preprod_run` with the returned run id. Poll
`list_preprod_runs` until the status is `completed`, `completed_with_regressions`, `failed` or
`cancelled`.

If there is no baseline run and the incumbent version is reachable, create and start the same run
for the incumbent first, with its own version label. That run is the baseline.

## Step 4: Runner mode, when there is no endpoint

1. `create_preprod_run` with `"runner_mode": "runner"` and no connection.
2. `get_preprod_run_items` lists each frozen input with its `itemId`.
3. Write a short script in the user's repo that, for each item, calls the agent's real entry point
   with the item's input, inside a span carrying three attributes:
   `neens.eval_run_id` (the run id), `neens.dataset_item_id` (the `itemId`) and
   `neens.version_label`. Traces go to Neens through the normal exporter (see `instrument-agent`).
4. `start_preprod_run` moves the run to `running`. Run the script, then poll as in Step 3.

## Step 5: Read the result

For each run:

1. `get_preprod_comparison` returns the candidate's pass rate, the regressions (items the
   baseline passed and the candidate failed), the new passes, and cost, latency and step deltas.
2. `get_preprod_metrics` returns the per-judge breakdown. An aggregate that holds can hide one
   judge that collapsed.
3. For up to three regressions, `get_preprod_trajectory` with the run id, the `baseline_run_id` and
   the item's id shows what the agent did differently, as an aligned step diff. Explain each
   regression in one sentence from that diff, for example "the candidate skipped `lookup_order`
   and answered from memory".

Rules for reading the numbers:

- **Count regressions from `regressionCount`,** not from the length of the `regressions` list. The
  list is capped evidence.
- **A null pass rate or a null delta means no data,** never 0% and never "no change".
- **Write the item count next to every rate:** "27/30 (90%)". On 10 items, one item is 10 points.
- **If captured items are fewer than the total,** some inputs errored at the endpoint. Name how
  many. A verdict on 12 of 30 items is not a verdict on the set.
- **A run status of `completed` does not mean the gate passed.** The status tracks regressions
  only. Compare the pass rate against `min_pass_rate` yourself.
- **Replay both sides the same way.** If the candidate branch changes how the agent reads golden
  inputs (for example, a replay fix), run the baseline from the incumbent plus that same change.
  Otherwise the comparison measures the replay, not the change being gated.
- **Run pre-prod runs one at a time** when they share a small self-hosted database, and re-run a
  run that failed with nothing captured before reading anything into it.

## Step 6: Verdict

- **GO**: every run met its gate, with zero regressions, and at least 90% of items were captured.
- **NO-GO**: any regression, or any run under its gate. List each regression with its one-line
  explanation.
- **NO DATA**: a run failed, or nothing was scored or captured. That is an infrastructure problem:
  fix the endpoint, the judges or the harness, and run again. It is not a verdict on the change.

Report a table with one row per dataset: dataset, items scored/total, pass rate (candidate vs
baseline), regressions, new passes, and cost and p95 latency deltas. Then the verdict, then the
regression explanations.

Do not relax a gate to turn NO-GO into GO. That call belongs to the user, and the report must say
it was made.

## Comparing several candidates

When there are two or more candidate runs on the **same** frozen dataset version, call
`compare_preprod_runs` with their `run_ids` and the incumbent's run as `baseline_run_id`. Runs on
different dataset versions are not comparable, and Neens refuses them. To compare models, use
`choose-model`.

## Anti-patterns

- **Gating only on the new feature's dataset.** Old fixes come back through new changes. Replay
  every regression set.
- **A production-window baseline when the incumbent can run.** Different inputs on each side mean
  a different test on each side.
- **"Pass rate went from 90% to 88%" on 10 items.** That is one item. Say so.
- **Reporting NO DATA as NO-GO,** or as GO.
