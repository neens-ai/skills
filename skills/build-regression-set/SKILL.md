---
name: build-regression-set
description: >
  Freeze a confirmed failure mode into a golden regression dataset in Neens: the failing traces
  plus passing controls, snapshotted as an immutable golden version that pre-prod runs and fix
  verification replay. Use after a failure mode is confirmed (see `triage-failures`), before
  fixing it, or when the user asks for a golden set, regression set or eval dataset. Do NOT use to
  score the dataset; that is `write-judge` and `gate-release`.
---

# Build Regression Set

A failure you fixed can only stay fixed if something checks for it on every release. This skill
builds that check's data: the real traces that failed, plus traces that passed on the same path,
frozen so every later run is measured against the same thing.

## Prerequisites

- A confirmed failure mode, with its `cluster_id`. If nobody has read its traces yet, run
  `triage-failures` first.

## Step 1: Do not duplicate

Call `list_datasets`. If a dataset was already built from this cluster (its `clusterId` matches)
or its name clearly covers this failure, extend it with `add_to_dataset` instead of creating a new
one, then go to Step 5.

## Step 2: Collect the failures

Call `list_traces` with `{"cluster_id": "<id>", "limit": 50}`. `total` is the full membership size.
If `total` is larger than 50, page back in time with `started_before` set to the oldest
`startedAt` you have received.

Keep sessions that show the failure. Drop exact duplicates: two traces whose user input is the
same text add no information. Target 20 to 50 failures. With fewer than 10, one item moves the
pass rate by 10 points or more, so say that the set is small and that it will be noisy.

## Step 3: Add passing controls

A fix that breaks what already worked is a regression, and a set made only of failures cannot
catch one. Add controls: traces from the same agent that go down the same path and succeed.

Call `list_traces` with the same `agent_name` and, when the failure involves a tool, the same
`tool_name`, plus `{"status": "ok"}`. If the project scores with `primary_score` (check
`list_scores`), also filter `{"score_metric": "primary_score", "score_status": "pass"}`. Open two or
three with `get_trace` to make sure they really did succeed.

Add about one control for every two failures, and never fewer than five.

## Step 4: Create and freeze

1. `create_dataset`:

   ```json
   {"name": "<failure-slug>-regression",
    "description": "Cluster <cluster_id>: <one-line failure>. <N> failures + <M> passing controls, <date>.",
    "session_ids": ["…failures…", "…controls…"]}
   ```

2. `create_golden_version`:

   ```json
   {"dataset": "<dataset id>", "name": "v1",
    "notes": "Frozen from cluster <cluster_id> on <date>: <N> failures, <M> controls."}
   ```

Runs replay the frozen golden version, never the live items. That is what keeps a run next month
comparable to a run today.

## Step 5: Check it

1. `list_dataset_versions` must show a golden version.
2. `get_dataset_version_items` with `{"dataset": …, "version": <number>, "limit": 5}`. Each item
   needs a non-empty input. If inputs are empty, the traces are missing their user input; fix
   that with `instrument-agent` before relying on this set.
3. Call `list_judges` and look for a deployed judge that detects this failure. A regression set
   with no judge that recognizes the failure is a list of inputs, not a test. If none exists,
   the next step is `write-judge`.

## Report

- Dataset name and id, golden version number, and how many failures and controls it holds
- The cluster id it came from
- Whether a judge covers it, and which one
- The next step: `write-judge` if no judge covers it, otherwise `fix-failure`

## Anti-patterns

- **Failures only, no controls.** You would see that the fix works but not what it broke.
- **Evaluating live items instead of a frozen version.** The numbers stop being comparable the
  moment someone adds an item.
- **Building the set from a label search.** Use the `cluster_id` membership. Labels drift.
- **Padding the set with near-identical traces.** Twenty copies of one input count as one test.
