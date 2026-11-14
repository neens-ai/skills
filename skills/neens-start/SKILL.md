---
name: neens-start
description: >
  Entry point for working with Neens. Use when the user asks for help with Neens, asks "where do I
  start", asks what is wrong with their agent without naming a task, or asks for something no other
  Neens skill matches. It checks the Neens MCP connection, reads the agent's next best actions and
  action inbox (the ranked failure→fix queue), and routes to the right skill. Do NOT use when a
  more specific Neens skill already matches the request; load that skill directly.
---

# Neens Start

Confirm the connection, take a reading of the loop, and route to the skill that matches where the
project stands. This skill holds only routing. The workflows live in the targeted skills.

Neens tools are called by their bare names here (`list_traces`). Your client may prefix them, for
example `mcp__neens__list_traces` in Claude Code.

## Step 1: Confirm the connection

Call `get_current_project`.

- **The tool does not exist.** Neens is not connected. Tell the user to add the Neens MCP server
  (`https://app.neens.ai/mcp`, or their own host if they self-host) to their coding agent, sign in
  through the browser window it opens, then start a new session. Stop here. For example:

  ```bash
  claude mcp add --transport http neens https://app.neens.ai/mcp                 # Claude Code
  codex mcp add neens --url https://app.neens.ai/mcp && codex mcp login neens    # Codex
  ```

  Other clients (Cursor, VS Code, …): https://app.neens.ai/docs/coding-agents/connect/

- **`projectId` is null.** The connection is not pinned to one project. Ask which project to use
  before reading anything.
- **Otherwise** say in one line which project and company you are connected to. Every later
  action is scoped to it.

## Step 2: Read the next actions

Call `get_next_actions` and `get_action_inbox` with `{"range": "7d"}` in parallel. Next actions
decide the route; the inbox (below) says what changed. If `get_next_actions` does not exist on
this server (Scout, the Neens background agent, is not turned on there) or returns an error, skip
to the inbox.

`get_next_actions` returns the ranked actions the agent's card shows, a primary one first. For
each of the top three, show one line: `title`, `impact`, and whether it is yours to do:

- **`steps`** lists the tools a run calls, or a `link` for work done in the Neens app. Route on the
  `kind` with the table below; a `link` step is done by a person in Neens, so give the link.
- **`canRun` false** means this connection lacks a capability in `requires` (or is an API key).
  Say who can do it instead of trying.
- **`finding`** is Scout's own investigation of the action, agent-written. Present it as Scout's,
  with its `runId`, and confirm its claims from the traces before acting on them. `get_ambient_run`
  with the `runId` shows what it read.
- **`scopeKind`** `org` or `company` spans agents; `parts` names them. Work one agent at a time.

| `kind` | Load |
|---|---|
| `connect_agent` | `instrument-agent` |
| `confirm_failure_mode`, `shared_failure` | `triage-failures` |
| `build_regression_set` | `build-regression-set` |
| `write_judge`, `review_disagreements`, `uneven_coverage` | `write-judge` (or `write-code-judge` when a rule decides the failure) |
| `start_fix_run` | `fix-failure` |
| `merge_fix_pr` | none: a person merges. Offer `gate-release` first |
| `add_llm_connection`, `connect_repo`, `resume_autonomy`, `failing_connection`, `unpriced_model`, `budget_near_limit` | none: a setting in Neens. Give the step's link and say what it unblocks |

An unlisted `kind`: follow its `steps`. Do not rate an action unless the user asks; when they do,
`rate_next_action` with their `rating` and `note`. A rating from an agent is shown but never
changes the ranking.

## Step 2b: Read the inbox

`get_action_inbox` with `{"range": "7d"}` returns the same ranked "what to do
next" queue the Insights page shows: what changed against the previous 7 days, how many open items
sit at each fix-loop stage (`pipeline`), and the ranked rows (`issues`). This skill only reads the
inbox. There is no tool to rate or dismiss a row, so do not offer to. When Step 2 showed next
actions, add only the `pipeline` line and rows they do not already cover.

Read the reply:

- **`issues` has rows.** Show the top three to five, one line each: `label`, `severity`,
  `windowAffected` sessions (and `prevAffected` before), the growth, and the next action for its
  `stage` from the table below. Add one line for the `pipeline` counts. Write growth as
  `growthPct` only when `growthBasis` is `computed`; otherwise write "new", "too few sessions to
  call a trend" or "no comparison". A `stale` row has nothing in this window: list it last, if at
  all.
- **A row has `children`.** It groups the same failure across several agents.
  Show the parent line, then one short line per child with its own agent, `stage` and next action.
  Route on the child the user cares about, not on the parent.
- **`issues` is empty and `inboxTotal` is 0.** Before calling it all clear, call `list_traces`
  with `{"limit": 1}`. If `total` is 0, nothing has been ingested: route to `instrument-agent`. If
  traces are flowing, say the inbox is clear for the last 7 days, give the trace count, and offer
  the most useful next step from Step 3 for a healthy project: `gate-release` before the next
  change ships, `reliability-review` for a status report, or `write-judge` if no judge is deployed
  yet (check with `list_judges` with `{"limit": 10}`).
- **A count is null.** It could not be read. Say "unknown", never zero.
- **The reply is an error.** Report the error and its `status` as returned and fall back to the
  survey below. A 401 or 403 means the sign-in or role, not an empty project.

The inbox is computed from traces and needs no LLM connection. A project without one still gets
its rows, but the steps after it that call a model (generating a remediation, running a judge)
report a connection error or use a simpler fallback. If any later call says no LLM connection is
configured, tell the user to add one under **Settings → LLM providers**.

| `stage` | Next action | Load |
|---|---|---|
| `needs_fix` | No fix yet, or a shipped fix regressed. Confirm the failure from its traces, then fix it | `triage-failures` (unreviewed), then `fix-failure` |
| `fix_proposed` | A fix is waiting. Read it with `get_remediation` (`remediationId`), implement it and prove it | `fix-failure` |
| `in_pr` | A PR is open (`prUrl`), or the fix is merged and Neens is watching whether it holds. Before merge, check it is safe to ship; after merge, wait for the watch | `gate-release` before merge, none after |
| `verified` | The fix held. Nothing to do; mention it as good news | none |
| `downstream` | A service outside the agent owns it. Name the owner from `get_remediation`; do not change the prompt | `triage-failures` |

`targetType` says what a row is: `cluster` (a failure cluster; `targetId` goes to
`get_failure_mode`), `issue` (a named failure mode) or `regression` (a quality score that dropped;
there is no fix source, so start with `triage-failures`). `fixSource` carries the id a fix is
generated from and `remediationId` the fix itself, when one exists.

### Fallback: the survey

Use this only when `get_action_inbox` does not exist on this server (the client reports an unknown
tool, or it is missing from the tool list) or returns an error. Older Neens servers do not have it.
Make these calls in parallel. Each takes no required arguments.

| Call | What it tells you |
|---|---|
| `list_traces` with `{"limit": 1}` | `total` = whether traces are flowing at all |
| `list_failure_modes` | `readiness` (has clustering run?) and the ranked failure modes |
| `list_open_remediations` with `{"limit": 5}` | agent-fixable fixes waiting to be implemented and proven |
| `list_judges` with `{"limit": 10}` | which judges exist and which are deployed |
| `list_datasets` with `{"limit": 10}` | which regression sets exist |

Report a snapshot of at most six lines: traces, failure modes (count, how many are new, the top
one by sessions), open fixes, judges, datasets. Use the numbers the tools returned, and write
"none" for zero rather than leaving a line out.

## Step 3: Route

Pick the first row that matches what the user asked for. If they asked for nothing specific,
route on the primary next action from Step 2; with no next actions, pick the first row that
matches the project's state.

| Situation | Load |
|---|---|
| No traces (`list_traces` total is 0), or the user wants to send traces | `instrument-agent` |
| The user wants to know what is failing, the top inbox row is `needs_fix` or `downstream`, or there are failure modes nobody has reviewed | `triage-failures` |
| A failure mode is confirmed and there is no dataset built from it | `build-regression-set` |
| A failure mode needs an automated check that takes judgment (grounding, the right action, tone), or a judge's verdicts are in doubt | `write-judge` |
| A failure mode needs an automated check a rule can decide (output schema or format, a required tool call or its arguments, a forbidden pattern, a numeric limit), or the user asks for a code judge | `write-code-judge` |
| The top inbox row is `fix_proposed`, there are open agent-fixable remediations, or the user wants to fix a failure | `fix-failure` |
| The user is about to ship a change (branch, prompt, model, config) and wants a go/no-go | `gate-release` |
| The user is choosing between models | `choose-model` |
| The user wants a status report: "how are we doing", weekly review, exec summary | `reliability-review` |
| The user asks what Scout found or did, wants to change what Scout may do, or wants a recurring check ("every Monday, tell me…") | `scout` |

The usual order for a new project is `instrument-agent` → `triage-failures` →
`build-regression-set` → `write-judge` or `write-code-judge` → `fix-failure` → `gate-release`. A project with open
remediations but no confirmed failure modes should still go through `triage-failures` first:
fixing a failure nobody has looked at is how the wrong thing gets fixed.

Tell the user which skill you are loading and why in one sentence, then follow that skill from
start to finish. If two rows fit equally, ask which one they want.
