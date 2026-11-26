---
name: find-failing-component
description: >
  Find which part of an agent is breaking it: a tool, MCP server, sub-agent or skill. Ranks the
  components by error rate, latency and cost from real traces in Neens, reads the papercuts the
  agent filed about its own tools, and decides for each whether the fault is the component's
  contract (schema, description), a downstream outage, or the agent misusing it. Routes each to
  the right owner and fix. Use when the user asks which tool or MCP server is failing, whether a
  sub-agent is the problem, what the agent complains about, or when failures cluster around one
  tool. Do NOT use for latency alone (`investigate-latency`).
---

# Find the Failing Component

Rank the agent's components by how much trouble they cause, then decide for each where the fault
lives. A tool that errors is not always the tool's fault: the agent may be calling it wrong.

Neens tools are called by their bare names here (`list_components`). Your client may prefix them,
for example `mcp__neens__list_components` in Claude Code.

## Step 1: Rank the components

Call `get_current_project`, then in parallel:

- `list_components` with `{"range": "7d"}`: each skill, MCP server, sub-agent and tool with its
  invocations, sessions reached, `errorRate`, latency p50/p95, `costUsd` of the model calls inside
  it, and the components most often used with it. A rate over too few invocations is null: say
  "too few to tell", never zero. A null cost is unpriced, never $0.
- `list_papercuts` with `{"range": "30d"}`: the problems the agent reported about its own tools
  (what it tried, expected, what happened, its suggested fix), grouped. These are the agent's
  claims, not verdicts.
- `list_failure_modes` with `{"range": "7d"}`: the failure modes, to cross-reference.

Rank by impact: error rate times sessions reached, not error rate alone. A tool failing 40% of 5
calls matters less than one failing 3% of 4,000.

## Step 2: Read the top two or three

For each, `get_component` with its `kind` and `name` lists recent invocations: trace id, version,
who invoked it, status, duration and error. Then `get_trace` on two failing invocations and one
successful one, and read the tool call's arguments and result.

For failure modes, `get_failure_mode` names a `componentOwner` when the mode's failures start
inside one component. A mode whose owner is the component you are looking at is evidence for it.

## Step 3: Decide where the fault lives

| Fault | Evidence | Fix | Owner |
|---|---|---|---|
| **The component's contract** | The agent's arguments match the tool's description, but the description is wrong, incomplete or ambiguous; or the result is shaped in a way the agent misreads | Change the tool's schema, description or output | Whoever owns the tool definition |
| **Agent misuse** | The description is clear and the agent sends wrong arguments, calls it at the wrong time, or ignores its result | Change the agent's prompt or the step that calls it | The agent team: `triage-failures`, then `fix-failure` |
| **Downstream outage** | Correct arguments, and the service returned an error, a timeout or bad data; errors cluster in time | Nothing in the agent; retry policy at most | The service's owner |
| **Version change** | Errors start with one component version or agent version (`get_component` shows versions) | Roll back or fix that version | Whoever shipped it |

Compare a failing call with a successful one: the difference between their arguments is usually
the answer.

For papercuts: confirm each against the traces it points at. A papercut that the traces support is
evidence; one they do not support is the agent's opinion. With the user's agreement,
`promote_papercut` with `{"group_key": "<groupKey>"}` turns a confirmed group into a fix in the
backlog, marked as needing grounding because it rests on the agent's report.

## Step 4: Report

| Component | Kind | Invocations | Error rate | p95 | Fault | Evidence (trace ids) | Next step |
|---|---|---|---|---|---|---|---|

For each row, the next step is one of: `fix-failure` (contract or misuse, after
`triage-failures` confirms it), a ticket for a downstream owner (two or three sentences with the
component, the error rate, how many sessions it hit and two trace ids), or nothing (thin data:
say how many more invocations would settle it).

## Step 5: Keep watching it

Offer, and do only with the user's yes:

- a code judge (`write-code-judge`) that fails a trace where the component errored and the agent
  still gave a confident answer, which is the failure users notice;
- a Scout standing instruction, for example `create_standing_instruction` with
  `{"text": "Every Monday, tell me which component's error rate rose most this week and show two failing traces", "cron": "0 9 * * 1"}`.

## Anti-patterns

- **Ranking by error rate alone.** Weight by sessions reached.
- **Treating papercuts as findings.** They are the agent's claims. Read the traces.
- **Blaming the tool for the agent's arguments.** Compare a failing call with a successful one.
- **Patching the prompt around an outage.** Route it to the service owner.
