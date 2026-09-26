---
name: triage-failures
description: >
  Find out what is actually failing in an agent and why, from real traces. Reads Neens failure
  modes and clusters, inspects representative traces, sorts each failure by where it lives
  (agent-fixable, a downstream service, or a guardrail working as intended), and records the
  user's confirmed verdicts as ground truth. Use when the user asks what is failing, wants error
  analysis, or has failure modes nobody has reviewed. Do NOT use to write a judge or implement a
  fix; this skill hands off to `build-regression-set`, `write-judge` and `fix-failure`.
---

# Triage Failures

Turn Neens failure clusters into a short list of confirmed, located failures, with a trace id
behind every claim. Clusters are hypotheses. A failure is confirmed when a person has read the
evidence and agreed.

## Step 1: Load the failure modes

Call `get_current_project`, then `list_failure_modes`.

- **`readiness.ready` is false.** Clustering has not produced modes yet. Tell the user how many
  sessions are in the failure set (`readiness.failureSetCount`). Then triage by hand: call
  `list_traces` with `{"status": "error", "limit": 20}`, plus
  `{"score_metric": "primary_score", "score_status": "fail", "limit": 20}` if that metric exists.
  Read them as in Step 2 and group them yourself.
- **Otherwise** rank the modes by `sessionCount` and flag `isNew`. If the user named a failure,
  work on that one. If not, take the top three, and include any new mode even if it is small: a
  new mode is often a regression.

A mode whose label says it has no single root cause (a "mixed" or catch-all bucket) is not a
failure mode. Say so, and do not triage it as one.

## Step 2: Read the evidence

For each mode:

1. `get_failure_mode` with its `cluster_id` to get the description, root-cause hypothesis and
   member session ids.
2. `get_cluster_exemplars` with `{"cluster_id": …, "limit": 3}`. These are the most
   representative members.
3. `get_trace` on each exemplar. Read what the user asked, what each tool call returned, and the
   first step where the agent went wrong. Quote the specific evidence: the tool error, the
   fabricated field, the skipped step.
4. `list_traces` with `{"cluster_id": …, "limit": 10}`, then `get_trace` on one or two members
   that are **not** exemplars. If they fail differently, the cluster is mixed. Say so rather than
   forcing one story onto it.

If `get_trace` returns no `conversation` and no tool `arguments`/`result` (older Neens versions),
you can see the structure of the run but not what was said. Classify only what the structure
proves, such as a tool error or a guardrail span that fired. For content failures such as a
fabricated answer, say plainly that you cannot verify them, and ask the user to open the trace in
Neens (**Traces**, then the trace id) and tell you what the answer said.

Always filter by `cluster_id`. Never match on the mode's label with `issue_mode`, because labels
change when clustering re-runs and the label match silently returns a different set.

## Step 3: Locate each failure

Put every mode in exactly one of these classes, based on the evidence and not on the label:

| Class | Evidence looks like | What happens next |
|---|---|---|
| **Agent-fixable** | Wrong tool choice, bad arguments, an ungrounded or fabricated answer, an ignored instruction, a missed step, the wrong format | `build-regression-set`, then `fix-failure` |
| **Advisory (downstream/upstream)** | Timeouts, 5xx, pool exhaustion, a vendor outage in a tool the agent called correctly | Goes to the owning service's team. A prompt change here only hides the failure. |
| **Working as intended** | A guardrail or policy blocked a request it should block | Nothing to fix. Consider excluding it from failure metrics. |

If a remediation exists for the mode, `list_remediations` with `{"clusterId": …}` and then
`get_remediation` show Neens's own `actionability` and `failureLocus`. Use them as a second opinion,
and say so when you disagree with the evidence.

## Step 4: Confirm with the user

Present one table:

| Mode | Sessions | New | Class | What goes wrong (evidence) | Trace ids |
|---|---|---|---|---|---|

Then ask the user, one mode at a time, whether they agree with the class and the description.
Offer to show the full trace for any row. The user can correct you; their answer is the verdict.

## Step 5: Record the confirmed verdicts

For each exemplar trace the user confirmed as a real failure, call `add_annotation`:

```json
{"target_type": "session", "target_id": "<session id>", "verdict": "fail",
 "critique": "<the specific observed failure, one or two sentences>",
 "cluster_id": "<cluster id>", "is_gold": true}
```

If the user reviewed a trace and judged it fine, record `"verdict": "pass"` with the reason. Those
labels are just as valuable, because they are how a judge's false alarms get measured later.

- Only record a label the user explicitly confirmed. Never record your own judgment as ground truth.
- Set `is_gold: true` only for traces the user actually looked at.
- The critique names the behavior ("claimed a delivery date the order lookup did not return"),
  not a vague quality ("bad answer").

## Step 6: Hand off

For each **agent-fixable** mode, check for a remediation (`list_remediations` with
`{"clusterId": …}`). If there is none, call `generate_remediation` with `{"cluster_id": …}` and
report its `actionability`. Then suggest `build-regression-set` for that mode, followed by
`fix-failure`.

For **advisory** modes, write two or three sentences the user can paste into a ticket for the
owning team: the component, the error, how many sessions it hit, and two trace ids.

End with the ranked list of confirmed failures and the next skill to run for each.

## Anti-patterns

- **Reporting cluster labels as findings without reading a single trace.** A label is a summary
  written by a model. The trace is the evidence.
- **Recording labels the user never confirmed.** Ground truth that came from the agent is not
  ground truth.
- **Treating a vendor outage as a prompt problem.** Rewriting the prompt around a 503 hides the
  outage and fixes nothing.
- **"Fixing" a guardrail that worked.** A blocked request that should be blocked is a success.
- **Triaging twenty modes at once.** Two or three real, confirmed failures beat a long list nobody
  acts on.
