---
name: gate-release
description: >
  Decide whether a candidate agent version (a branch, a prompt change, a model or config change)
  is safe to ship: replay the agent's frozen golden and regression sets against it in a Neens
  pre-prod run, compare it with the current version, explain every regression from the
  trajectories, read every delta against its measured noise band, and return GO, NO-GO or NO DATA
  with the evidence. Optionally ablates a prompt change section by section. Use when the user asks
  "can we ship this", wants a release gate or a CI check, or wants two candidates compared. Do NOT
  use to prove one specific fix; that is `fix-failure`.
---

# Gate Release

Every failure you have fixed has a regression set. A release is safe when none of them come back
and nothing that passed before now fails. This skill runs that check against the candidate and
gives a verdict that cites its evidence.

## Step 1: Pin down the candidate

Get three things from the user or the repo:

1. **Version label**: `<branch>@<short sha>`, or a release tag.
2. **How Neens reaches it**, one of:
   - **Push**: Neens calls the candidate's HTTP endpoint. It needs a registered agent endpoint.
     Call `list_agent_endpoints` (with `q` set to the service name or URL) and reuse a match: its
     `id` is the `agent_connection_id`. If there is none, ask the user for the URL and register it
     with `register_agent_endpoint`:
     `{"name": "<agent>-<version label>", "base_url": "<preview url>", "request_shape": "input_json", "invoke_path": "/invoke"}`.
     `input_json` posts `{"input": …}` and reads `{"output": …}`; `openai_chat` posts a
     chat-completions body. Registering the same name and URL again updates it. A bearer token
     goes in `auth_token`, is stored encrypted and is never returned. The URL must be reachable
     from Neens: private and loopback addresses are refused unless the deployment allows them.
   - **Runner**: the user's own harness runs each golden input and sends the traces. Use this when
     the candidate cannot be exposed over HTTP. See Step 5.
3. **The baseline**: the version it replaces. The best baseline is a pre-prod run of the current
   production version on the same frozen set, because both sides then answer identical inputs.
   Use `list_preprod_runs` to find an existing one. The fallback is the production window
   (`baseline_kind: "prod_window"`), which is weaker because production traffic is not the golden
   set.

## Step 2: Check the eval gates

An eval gate is a failure mode CI replays on every build. A green CI check is evidence only when
the gate is current and its judge catches the failure. Read the gates before you replay anything.

Call `list_eval_gates` with `{"needs_attention": true, "limit": 50}`. If the tool does not exist on
this server, say so in the report and go on. For each gate returned, read `health`:

- **`warnings` holds `stale`.** CI has not checked an enforced gate within `staleAfterDays`. Its
  last pass says nothing about this candidate.
- **`warnings` holds `judge_misses_failure`.** The gate's judge passes the very failure it guards
  (`evidenceCatchRate` is the share of its own past failures it catches). A pass from that judge
  proves nothing, in CI or in your replay.
- **`state` is `failed` or `error`.** The newest CI check failed, or could not run. Report it; if
  that build is the candidate, the replay must explain it.
- **`saturated` is true.** CI passed 100% on each of the last `saturateAfterRuns` checks
  (`perfectStreak` is the current run of them). The gate still passes, but it no longer tells a
  good build from a bad one. This is advisory: it never blocks GO. Suggest the user add harder,
  real failing cases to its golden set from recent failure modes (`build-regression-set`).

List every one in the report: the gate's failure mode, `state`, the warnings and their
`warningMessages`. Never cite a stale or blind gate's CI pass as evidence for GO. Repairing a gate
is the user's job, in the app: tighten its judge and run **Check evidence** again, or get CI
checking it again. See https://app.neens.ai/docs/guides/eval-gates/.

## Step 3: Choose what to replay and who judges

1. `list_datasets`. Take every regression set built from a fixed failure (those with a
   `clusterId`, or named `*-regression`) and the agent's broad golden set, if it has one. Each
   dataset gets its own run.
2. `list_dataset_versions` on each. A dataset with no golden version cannot be replayed: freeze it
   with `create_golden_version`, or skip it and say that you skipped it.
3. `list_judges`. Pass `judge_deployment_ids` explicitly: the checked judges for these failures
   (LLM judges from `write-judge`, code judges from `write-code-judge`) plus the project's Primary
   Score deployment. Leave out judges nobody has
   checked against a person, and say which ones you left out. A judge on a gate flagged
   `judge_misses_failure` in Step 2 counts as unchecked for that failure mode.

## Step 4: Create and start the run (push)

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
`cancelled`. A run created with the wrong dataset, endpoint or judges, or one left waiting for
traces that will never come, is stopped with `cancel_preprod_run`; a finished run cannot be
cancelled, so its result stands.

If there is no baseline run and the incumbent version is reachable, create and start the same run
for the incumbent first, with its own version label. That run is the baseline.

## Step 5: Runner mode, when there is no endpoint

1. `create_preprod_run` with `"runner_mode": "runner"` and no connection.
2. `get_preprod_run_items` lists each frozen input with its `itemId`.
3. Write a short script in the user's repo that, for each item, calls the agent's real entry point
   with the item's input, inside a span carrying three attributes:
   `neens.eval_run_id` (the run id), `neens.dataset_item_id` (the `itemId`) and
   `neens.version_label`. Traces go to Neens through the normal exporter (see `instrument-agent`).
4. `start_preprod_run` moves the run to `running`. Run the script, then poll as in Step 4.

## Step 6: Read the result

For each run:

1. `get_preprod_comparison` returns the candidate's pass rate, the regressions (items the
   baseline passed and the candidate failed), the new passes, and cost, latency and step deltas.
2. `get_preprod_metrics` returns the per-judge breakdown. An aggregate that holds can hide one
   judge that collapsed.
3. For up to three regressions, `get_preprod_trajectory` with the run id, the `baseline_run_id` and
   the item's id shows what the agent did differently, as an aligned step diff. Explain each
   regression in one sentence from that diff, for example "the candidate skipped `lookup_order`
   and answered from memory".
4. Read `noise` on the comparison: the run-to-run noise band, measured from identical re-runs.
   `band` is how far two identical runs drift apart on these items, as a pass-rate fraction (0.09
   is ±9 pts); `withinNoise` says whether the overall delta is inside it. Outside the band is not
   significance by itself: two runs that happened to agree on every item give a band of 0, so the
   `regressionAnalysis` interval still decides whether a change is real. `get_preprod_noise`
   with the run id reads the same band. If the comparison has no `noise` field, this server
   predates the band: say so and read the `regressionAnalysis` interval alone.

Rules for reading the numbers:

- **Count regressions from `regressionCount`,** not from the length of the `regressions` list. The
  list is capped evidence.
- **A null pass rate or a null delta means no data,** never 0% and never "no change".
- **Quote the noise band beside every pass-rate delta:** "+2/30 (+6.7 pts), noise band ±9 pts,
  within noise". A delta inside the band (`withinNoise` true) is indistinguishable from noise:
  never call it a regression or an improvement. If `noise` is null or its `status` is
  `unmeasured`, say "noise not measured", never assume a band. Then, if `canMeasure` is true,
  offer to measure it: call `measure_preprod_noise` with `{"run_id": "<measureRunId>", "dry_run": true}` first (the
  run Neens picked to re-run, usually the baseline) and show the user its `estimate`; only on
  their yes, call it again without `dry_run` (pass `budget_usd` as a cap). It re-runs that run
  unchanged and costs money. If `canMeasure` is false, quote `measureBlockedReason`; for runs your
  own harness drove (runner mode), run the harness again on the same version and golden set, and
  the band fills in on its own.
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

## Step 7: Verdict

- **GO**: every run met its gate, with zero regressions, and at least 90% of items were captured.
- **NO-GO**: any regression, or any run under its gate. List each regression with its one-line
  explanation.
- **NO DATA**: a run failed, or nothing was scored or captured. That is an infrastructure problem:
  fix the endpoint, the judges or the harness, and run again. It is not a verdict on the change.

The noise band and saturation are advisory: they never change GO, NO-GO or NO DATA. Item
regressions still count from `regressionCount` as above. When the overall delta sits inside the
band, describe the pass-rate change as within noise, not as a regression or an improvement, and
suggest more evidence (more items, or a re-run) before the user acts on it.

Stale and blind gates from Step 2 do not block GO by themselves: the replay is the evidence, and a
stale gate's judge can still score the replay. But a failure mode whose only judge is one flagged
`judge_misses_failure` has no evidence: it is NO DATA for that failure mode, and the verdict cannot
be GO until it has a judge that catches it. Say which failure mode it is. A regression elsewhere
still makes it NO-GO.

**Lint findings are advisory.** If the candidate changes a system prompt or a SKILL.md, lint the
changed file (`neens lint <path>` or `npx neens-eval lint <path>`; `lint_prompt` with `text`,
`prompt_id` or `trace_id` when there is no file) and list the errors and warnings with their
lines. They do not change GO or NO-GO, unless the user's CI already makes lint blocking (a lint
step exiting 1, findings at or above its `--fail-on`); then a failing lint is NO-GO and the report
says so. Exit 2 means the file was not linted: say that, never "clean". When lint is blocking
and the changed file was not linted (exit 2, or no linter available), the verdict cannot be GO:
report NO DATA for lint until it lints.

Report a table with one row per dataset: dataset, items scored/total, pass rate (candidate vs
baseline), noise band (or "not measured"), regressions, new passes, and cost and p95 latency
deltas. Then the gates from Step 2 (saturated ones as advisory), then the lint findings, then the
verdict, with its reasoning naming any gate it could not count, then the regression explanations.

Do not relax `min_pass_rate` or `max_regressions` to turn NO-GO into GO. That call belongs to
the user, and the report must say it was made.

## Comparing several candidates

When there are two or more candidate runs on the **same** frozen dataset version, call
`compare_preprod_runs` with their `run_ids` and the incumbent's run as `baseline_run_id`. Runs on
different dataset versions are not comparable, and Neens refuses them. To compare models, use
`choose-model`.

## Optional: ablate a prompt change

When the candidate is a system prompt change, the user can ask which sections earn their place.
An ablation replays one frozen golden set with the full prompt (`full_repeats` times, default 2,
which also measures the noise band) and once per section with that one section removed. It ablates
prompt sections only, never tools: the agent owns its tools. If `start_ablation_run` does not
exist on this server, say so and skip this step.

1. The push endpoint must use the system prompt Neens sends. Only after the user confirms the
   agent uses that prompt instead of its own, register a separate endpoint for the ablation with
   `register_agent_endpoint`: a new `name`, `"accepts_system_prompt": true`, and the same
   `base_url`, `request_shape`, `invoke_path`, `model`, `output_jsonpath` and `auth_token` as the
   existing one (`list_agent_endpoints` shows the first four; ask the user for the rest). Never
   re-register the existing endpoint for this: re-registering replaces every option left out, and
   the gate's own runs use it. Pass the new endpoint's `id` as `agent_connection_id` below.
2. `start_ablation_run` with `"dry_run": true` first:
   `{"name": "ablate: <version label>", "version_label": "<branch>@<sha>", "agent_connection_id": "<conn id>", "dataset_id": "<dataset id>", "system_prompt": "<prompt text>", "dry_run": true}`
   (or `prompt_id` for a managed prompt). It lists the prompt's `sections` (their `key`s), the
   `estimate` and any `refusals`, and starts nothing. Show the user the estimate and let them pick
   the sections.
3. On their yes, call it again without `dry_run`, with `"sections": ["<key>", "…"]` and a
   `budget_usd` cap. Poll `get_ablation_run` with the `ablation_id`; `list_ablation_runs` finds
   earlier ones.
4. Report each section's `verdict` with its `quality` delta, interval and `n`, the noise band,
   `costDelta` and `latencyDeltaMs`: `earns_its_place` (the agent is worse without it),
   `no_measurable_effect` (this set cannot see an effect, which is not proof the section is
   useless) or `removing_it_helps`. `pending`, `failed` and `no_data` are not verdicts on the
   section. If `noiseMeasured` is false (for example `full_repeats` was 1), the verdict rests on
   the interval alone: say so.

"Removing it helps" is a proposal, never an edit. Do not touch the prompt. Offer to turn it into
a fix and call `propose_ablation_fix` with the `ablation_id` and the section's `arm_id` (its `id`
in `sections`) only after the user approves; it creates a `prompt_change` fix a person still
verifies and merges. An ablation result never changes the release verdict.

## Anti-patterns

- **Gating only on the new feature's dataset.** Old fixes come back through new changes. Replay
  every regression set.
- **A production-window baseline when the incumbent can run.** Different inputs on each side mean
  a different test on each side.
- **"Pass rate went from 90% to 88%" on 10 items.** That is one item. Say so.
- **Calling an in-band delta a regression or an improvement,** or leaving the band out because it
  was not measured. Quote it, or say it is not measured.
- **Reporting NO DATA as NO-GO,** or as GO.
