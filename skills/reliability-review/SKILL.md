---
name: reliability-review
description: >
  Produce a short, evidence-backed reliability report for an agent from Neens: business KPIs
  against target, quality trends, new and top failure modes, the state of the fix backlog, and
  which fixes held after merge. Every number carries its sample size and every claim a trace or
  run id. Use for "how is the agent doing", a weekly review, a status update, or an exec summary.
  Do NOT use to dig into one failure; use `triage-failures`.
---

# Reliability Review

One page that answers four questions: are we hitting our targets, what got worse, what is breaking,
and are our fixes holding. Every number comes from a Neens tool call made in this session. Never
estimate or carry numbers over from memory.

## Step 1: Gather

Call `get_current_project`, then these in parallel. Use the window the user asked for; the default
is `7d`.

| Call | For |
|---|---|
| `get_business_kpis` with `{"range": "7d"}` | Targets: value, target, met or missed, trend |
| `list_scores` with `{"range": "7d"}` | Quality: each metric's pass rate, scored count, and change versus the previous window |
| `list_failure_modes` | What is breaking: top modes by sessions, and new modes |
| `list_remediations` | The backlog: the `stats` rollup by status, work state and actionability |
| `list_open_remediations` with `{"limit": 5}` | The top agent-fixable fixes waiting |
| `list_preprod_runs` with `{"limit": 5}` | Recent release gates and their outcomes |
| `list_traces` with `{"started_after": "<window start>", "limit": 1}` | Volume: `total` traces in the window |

For each KPI that is `missed` or has a `regressed` trend, call `get_business_kpis` with its `kpi_id`
to see which failure clusters are eroding it.

## Step 2: Read it honestly

- **`targetStatus: "unknown"` or a null value means no data.** Say "no data" and why, if Neens gave
  a reason. It is not a miss.
- **Write the count next to every rate:** "pass rate 69% (33/48)". A metric with fewer than 20
  scored items in the window is too thin to call a trend. Say "thin" and leave it out of the
  headline.
- **A change is not a trend** unless both windows have enough data. A 30-point swing on 8 items
  is noise.
- **Name failure modes by what goes wrong,** with their session counts, and flag new ones: a new
  mode right after a release is the most likely regression.
- **A failure mode is a clustering hypothesis until someone has reviewed its traces.** Before a
  mode goes in the headline or an ask, open two of its exemplars (`get_cluster_exemplars`, then
  `get_trace`) and check that they show what the label claims. Mark modes you have not checked as
  "unreviewed", and never attribute a KPI miss to an unreviewed mode.
- **"Verified" in the backlog** means proven by an evaluation or by post-merge measurement. A
  `regressed` remediation is a fix that came back. Always surface it.

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

## What's breaking
<top 3 failure modes: what goes wrong, sessions, new?, where it lives (agent / service / guardrail)>

## Fixes
<backlog: proposed / in progress / verified / regressed counts>
<fixes verified this window, and any that regressed>
<top 1-2 open fixes by priority>

## Asks
<at most 3 decisions or actions for the reader, each naming an owner>
```

Keep it to one screen. Put detail in the trace, run and remediation ids, not in more prose.

## Step 4: Offer the next step

After the page, suggest the one follow-up that matters most: `triage-failures` for a new or
growing mode, `fix-failure` for a top open fix, or `gate-release` if a release is pending.

## Anti-patterns

- **A wall of every metric.** Pick the ones tied to targets and failures.
- **Percentages without counts.**
- **Calling a KPI with no data "missed".**
- **Hiding a regressed fix.** It is the most important line in the report.
