---
name: choose-model
description: >
  Decide which model an agent should run on, with evidence: a Neens model sweep replays one frozen
  golden set against each candidate model under identical conditions, repeats each item k times,
  and ranks the models on pass^k, cost and latency, with confidence intervals. Use when the user
  asks which model to use, whether a cheaper or newer model is good enough, or wants a model
  comparison. Do NOT use to evaluate a code or prompt change; use `gate-release`.
---

# Choose Model

"Which model should we ship" is answered by running the same inputs, judges and gate against every
model, several times each, and reading the result without flattering it. This skill runs a Neens
model sweep and reports it with the uncertainty left in.

## Step 1: Set up the arms

A sweep compares **agent endpoints**. Each arm is the user's agent configured to use one model,
registered in Neens as an agent endpoint (**Settings → LLM connections → Add agent endpoint**).
Ask the user for each arm's label, for example `gpt-4.1-mini`, and its `agent_connection_id`.

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
again. Call `list_preprod_runs` and check whether the arm runs already exist. If they do, the
sweep is running. Ask the user for its id from the Neens UI (**Model sweeps**), because only that
id unlocks `get_model_sweep_comparison`. Per-run pass rates you work out yourself are not pass^k:
say so if you report them before the proper comparison.

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

## Anti-patterns

- **Picking a model from one run per item.** Models are nondeterministic. k=1 rewards luck.
- **Declaring a winner on overlapping intervals.**
- **Changing the prompt for the new model in the same sweep.** Then you are testing two
  changes at once.
- **Calling an unpriced model the cheapest.**
