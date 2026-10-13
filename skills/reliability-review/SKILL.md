---
name: reliability-review
description: >
  Produce a short, evidence-backed reliability report for an agent from Neens: business KPIs
  against target, quality trends, and the action inbox grouped by fix-loop stage (what needs a
  fix, fixes ready to review, in PR, verified, downstream), including which fixes held after merge. Every number carries its sample size and every claim a trace or
  run id. Use for "how is the agent doing", a weekly review, a status update, or an exec summary.
  Do NOT use to dig into one failure; use `triage-failures`.
---

# Reliability Review

One page that answers four questions: are we hitting our targets, what got worse, what is breaking,
and are our fixes holding. Every number comes from a Neens tool call made in this session. Never
estimate or carry numbers over from memory.

## Step 1: Gather

Call `get_current_project`, then these in parallel. Use the window the user asked for; the default
is `7d`. `get_action_inbox` takes `today`, `24h`, `7d`, `30d` or `all`; for any other window use
the nearest one and say which you used.

| Call | For |
|---|---|
| `get_action_inbox` with `{"range": "7d", "limit": 20}` | The spine: what changed versus the previous window (`deltas`), open items per fix-loop stage (`pipeline`), and the ranked queue of failures with their fix status (`issues`) |
| `get_business_kpis` with `{"range": "7d"}` | Targets: value, target, met or missed, trend |
| `list_scores` with `{"range": "7d"}` | Quality: each metric's pass rate, scored count, and change versus the previous window |
| `list_preprod_runs` with `{"limit": 5}` | Recent release gates and their outcomes |
| `list_traces` with `{"started_after": "<window start>", "limit": 1}` | Volume: `total` traces in the window |

For each KPI that is `missed` or has a `regressed` trend, call `get_business_kpis` with its `kpi_id`
to see which failure clusters are eroding it.

The inbox is read-only here. There is no tool to rate or dismiss a row, so do not offer to.

**If `get_action_inbox` does not exist on this server** (an unknown-tool error, or it is missing
from the tool list) or returns an error, gather the failure and fix sections the older way instead:
`list_failure_modes` (top modes by sessions, and new modes), `list_remediations` (the `stats`
rollup by status, work state and actionability) and `list_open_remediations` with `{"limit": 5}`.
Say in the report that the inbox was unavailable.

### Read the inbox by stage

Group the `issues` rows by `stage`, in the order of the fix loop. `pipeline` gives the count per
stage for the whole inbox; `issues` holds only the top-ranked rows (at most 20), so when
`complete` is false, quote the `pipeline` count and say the list is the top of it.

| `stage` | Means | Drill in with |
|---|---|---|
| `needs_fix` | No fix yet. A row that also has a `remediationId` is a fix that **regressed**: it shipped and the failure came back | `get_failure_mode` (cluster rows), `get_remediation` (if `remediationId`) |
| `fix_proposed` | A fix is ready for someone to review and implement | `get_remediation` with `remediationId` |
| `in_pr` | A PR is open (`prUrl`), or the fix is merged and Neens is watching whether it holds | `get_remediation` with `remediationId` |
| `verified` | The fix held after merge, or was proven by an evaluation | `get_remediation` with `remediationId` |
| `downstream` | A service outside the agent owns it; no prompt change fixes it | `get_remediation` for the owning service |

`targetType` says what a row is. For `cluster`, `targetId` is the cluster id for
`get_failure_mode` and `get_cluster_exemplars`. For `issue`, the row is a named failure mode: read
its traces with `list_traces` and `issue_mode` set to the row's `label`. For `regression`, the row
is a quality score that dropped; read it next to `list_scores`, and cite the row's `cause` as the
detector's summary, not as a verified finding.

A row with `children` groups the same failure across several agents. Report the parent once, with
each child's agent and its own `stage` on a sub-line; a child can be further along the loop than
its siblings.

**An empty inbox** (`issues` empty, `inboxTotal` 0) is a real result only when traces flowed in
the window. If `list_traces` returned `total` 0, the headline is "no traffic in the window", not
"all clear". With traffic, say the inbox is clear, give the trace count, and keep the Targets and
Quality sections: an empty inbox does not mean every KPI is met.

The inbox needs no LLM connection; it is computed from traces. Without one, a row's `cause` can
be null, and remediations may come from a simpler fallback. Report what is there, and if any call
says no LLM connection is configured, add an ask to set one up under **Settings → LLM providers**.

## Step 2: Read it honestly

- **`targetStatus: "unknown"` or a null value means no data.** Say "no data" and why, if Neens gave
  a reason. It is not a miss. The same holds for a null count in the inbox's `deltas` or
  `pipeline`: it could not be read, so write "unknown", never zero.
- **Write the count next to every rate:** "pass rate 69% (33/48)". A metric with fewer than 20
  scored items in the window is too thin to call a trend. Say "thin" and leave it out of the
  headline.
- **A change is not a trend** unless both windows have enough data. A 30-point swing on 8 items
  is noise. For inbox rows, quote `growthPct` only when `growthBasis` is `computed`; otherwise
  write "new", "too few sessions to call a trend" or "no comparison".
- **Name failures by what goes wrong,** with their sessions now and before (`windowAffected`,
  `prevAffected`), and flag new ones: a new failure right after a release is the most likely
  regression.
- **Wasted spend is an estimate.** Quote `estWasteUsd` only when `estWasteBasis` is `priced`; for
  `partial` say "at least"; otherwise leave it out.
- **A failure mode is a clustering hypothesis until someone has reviewed its traces.** Before a
  row goes in the headline or an ask, open two of its exemplars (`get_cluster_exemplars`, then
  `get_trace`) and check that they show what the label claims. Mark rows you have not checked as
  "unreviewed", and never attribute a KPI miss to an unreviewed failure.
- **"Verified"** means proven by an evaluation or by post-merge measurement. A regressed fix (a
  `needs_fix` row with a `remediationId`; confirm with `get_remediation`) is a fix that came back.
  Always surface it.

## Step 3: Write the page

```markdown
# <Agent / project> reliability, <window>

**Headline:** <one sentence: the single most important thing, with its number>

## Targets
| KPI | Now | Target | Status | Trend |
<one row per KPI; "no data" where null>

## Quality
<the 3-5 metrics that matter, each "pass rate x% (n/N), change vs previous window">
<thin metrics listed on one line as "not enough data: …">

## What changed
<from the inbox deltas: new failures, regressions, anomalies, fixes ready, fixes held, each "now (previous)">

## Fix loop
<pipeline counts: needs fix / fix ready to review / in PR / verified / downstream>
<needs fix: top 3 by rank, each with what goes wrong, sessions now (before), new?, reviewed?>
<regressed fixes, always, with remediation id>
<fix ready to review and in PR: top 1-2 each, with remediation id and PR link>
<verified this window; downstream items with their owning service>

## Asks
<at most 3 decisions or actions for the reader, each naming an owner>
```

Keep it to one screen. Put detail in the trace, run and remediation ids, not in more prose.

## Step 4: Offer the next step

After the page, suggest the one follow-up that matters most: `triage-failures` for a new or
growing `needs_fix` row or a regressed fix, `fix-failure` for a top `fix_proposed` row, or
`gate-release` for an `in_pr` fix that is not merged yet or any other pending release.

## Anti-patterns

- **A wall of every metric.** Pick the ones tied to targets and failures.
- **Percentages without counts.**
- **Calling a KPI with no data "missed".**
- **Hiding a regressed fix.** It is the most important line in the report.
