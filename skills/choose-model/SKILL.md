---
name: choose-model
description: >
  Decide which model an agent should run on, with evidence: a Neens model sweep replays one frozen
  golden set against each candidate model under identical conditions, repeats each item k times,
  and ranks the models on pass^k, cost and latency, with confidence intervals. Use when the user
  asks which model to use, whether a cheaper or newer model is good enough, or wants a model
  comparison. Can add an advisory blind pairwise comparison of the top two arms' answers. Do NOT
  use to evaluate a code or prompt change; use `gate-release`.
---

# Choose Model

"Which model should we ship" is answered by running the same inputs, judges and gate against every
model, several times each, and reading the result without flattering it. This skill runs a Neens
model sweep and reports it with the uncertainty left in.

## Step 1: Set up the arms

A sweep compares **agent endpoints**. Each arm is the user's agent configured to use one model,
registered in Neens as an agent endpoint. Call `list_agent_endpoints` (its `model` field shows
which model each one sends) and reuse the matching ones; their `id` is the arm's
`agent_connection_id`. For a model with no endpoint yet, ask the user for the URL and call
`register_agent_endpoint` with a `name`, the `base_url`, the `request_shape` and, for an
`openai_chat` endpoint, the `model` it should send. Give each arm a label, for example
`gpt-4.1-mini`.

If the agent has no URL Neens can reach (a local or CI agent), give `start_model_sweep` runner arms instead:
`{"label": …, "model": …, "runner_mode": "runner"}`. Neens never calls in; the user runs
`neens sweep run --sweep-id <id> -- <agent command>` from the `neens-eval` CLI, which runs the agent
once per arm, repeat and item with `NEENS_EVAL_MODEL` set to the arm's model. Never mix runner and
endpoint arms in one sweep.

- The first arm is the **incumbent**, the model in production today. It is the baseline.
- Two arms on the same connection are the same model twice. Neens rejects that.
- Only the model may differ between arms: same code, same prompt, same tools. Otherwise the
  sweep measures something other than the model.

## Step 2: Pick the set and the judges

1. `list_datasets` and `list_dataset_versions`. Use the broad golden set plus the regression sets
   that matter most. The set must have a golden version.
2. `list_judges`. Use the checked judges and Primary Score. The same judges score every arm.

## Step 3: Launch with a budget

Ask the user for a spending ceiling. Then call `start_model_sweep`:

```json
{"name": "model choice <date>", "version_label": "<branch>@<sha>",
 "dataset_id": "<dataset id>",
 "arms": [{"label": "<incumbent>", "agent_connection_id": "<conn>"},
          {"label": "<candidate>", "agent_connection_id": "<conn>"}],
 "pass_k": 3, "judge_deployment_ids": ["…"], "budget_usd": <ceiling>}
```

Use `pass_k` of 3: an item counts as passed only if it passes all three repeats, which is what
exposes a model that is right only some of the time. If the sweep is refused because it would
exceed the budget, report the estimate and let the user decide. Do not quietly cut `pass_k` or
the dataset to make it fit.

Poll `get_model_sweep` until the status is terminal. Partial results are normal: read each arm's
own status.

If the launch reply never arrived, for example because the client timed out, do **not** launch
again. Call `list_model_sweeps` with `q` set to the sweep's name. If it is listed, it is running:
take its `id` and continue polling with `get_model_sweep`. Launch again only if it is not listed.

## Step 4: Decide

Call `get_model_sweep_comparison` with the `sweep_id`. Leave `baseline_arm` out, so the declared
incumbent stays the baseline. A baseline picked after seeing the results is not a baseline.

Four rules, with no exceptions:

1. **`comparable: false` (a `void` sweep) means the arms did not run under the same conditions.
   Never rank them.** Report `voidReason` and what to fix.
2. **`costPerCaseUsd: null` means unpriced, not free.** An unpriced model cannot win on cost.
3. **A rate of null means no data, not 0%.**
4. **An item passes only if it passed every repeat.** 2 of 3 is a fail, and `flakyItems` counts
   those items.

Report one row per arm: pass rate with n and 95% CI, pass^k (greens/k), flaky items, p95
latency, cost per case, and regressions against the incumbent. Then report Neens's verdict
sentence and the per-agent verdicts.

When two arms' confidence intervals overlap, say that the data cannot separate them on quality,
and let cost and latency decide. Recommend a switch only when the candidate is at least as good as
the incumbent with no regressions, or when the user explicitly accepts a quality drop in exchange
for a cost saving.

## Step 5 (optional): Compare the top two blind

Pass^k says whether each answer is good enough, not which of two acceptable answers is better.
When the top two arms both clear the bar, offer a blind pairwise comparison of their answers on
the same golden items. It is supporting evidence: pass^k, cost and latency stay the ranking, and
a pairwise result never decides a gate or overturns the Step 4 decision.

1. It needs a pairwise judge (`list_judges`, or create one with `write-judge`). Say whether it
   meets the calibration bar in `write-judge` ("A pairwise judge"); until it does, call
   its preference uncalibrated and weak evidence.
2. **Cost first.** It spends LLM budget on the user's connection: two judge calls per item with
   both orders. Tell the user and ask for a ceiling. Call `start_pairwise_comparison` with
   `{"judge_id": …, "sweep_id": …, "arm_x_id": "<arm id>", "arm_y_id": "<arm id>", "budget_usd": <ceiling>}`.
   Name both arms: the default is the first two arms, not the top two. The arm `id`s come from
   `get_model_sweep`. Over the budget it is refused with an error that carries the estimate
   (`calls`, `usd`); a launched comparison returns it as `estimate`. Report it and let the user
   decide; do not cut items to fit. `usd` null means the judge's model is unpriced, not free:
   such a comparison is not refused and the budget cannot stop it, because its spend is unknown.
   Say so and launch only on the user's explicit yes. Keep `both_orders` on. It compares one
   repeat per arm (`attempt`, default 1), so its n is golden items, not items × k.
3. Poll `get_pairwise_comparison` with `{"comparison_id": …}` until `status` is no longer
   pending or running. `budget_stopped` means its priced spend hit the budget and it kept the verdicts it had.

How it stays fair: which answer is A is randomized per item from a recorded `seed`, and every item
is judged in both orders. A pair whose verdict flips with the order is a tie
(`orderInconsistentTies`).

Read `result` and report it as it is:

- `result.x` and `result.y`: `wins`, `winRate` over **decisive** pairs (ties excluded) and its
  95% Wilson `interval`. Always give `decisive` as the n.
- Ties on their own line: `ties`, of which `orderInconsistentTies` flipped with the order, and
  `unjudged`. Never fold ties into a 50/50 split.
- `state`: `insufficient_evidence` (fewer than `minDecisive`, 10, decisive pairs),
  `no_clear_preference` (the interval includes 50%), or `x_preferred` / `y_preferred`.
  `no_data` means nothing was judged. **Name a winner only for `x_preferred` or `y_preferred`.**
  Otherwise say the judge could not separate them.
- `spendPartial` true means part of the spend is unknown. Report `spentUsd` as a lower bound.

If `start_pairwise_comparison` does not exist on this server, skip this step.

## Anti-patterns

- **Picking a model from one run per item.** Models are nondeterministic. k=1 rewards luck.
- **Declaring a winner on overlapping intervals.**
- **Changing the prompt for the new model in the same sweep.** Then you are testing two
  changes at once.
- **Calling an unpriced model the cheapest.**
- **Letting a pairwise preference pick the model.** It is advisory; pass^k, cost and latency rank.
