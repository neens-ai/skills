---
name: neens-start
description: >
  Entry point for working with Neens. Use when the user asks for help with Neens, asks "where do I
  start", asks what is wrong with their agent without naming a task, or asks for something no other
  Neens skill matches. It checks the Neens MCP connection, takes a one-screen reading of the
  project's failure→fix loop, and routes to the right skill. Do NOT use when a more specific Neens
  skill already matches the request; load that skill directly.
---

# Neens Start

Confirm the connection, take a reading of the loop, and route to the skill that matches where the
project stands. This skill holds only routing. The workflows live in the targeted skills.

Neens tools are called by their bare names here (`list_traces`). Your client may prefix them, for
example `mcp__neens__list_traces` in Claude Code.

## Step 1: Confirm the connection

Call `get_current_project`.

- **The tool does not exist.** Neens is not connected. Tell the user to run the command below and
  sign in through the browser window it opens, then start a new session. Use their own host if they
  self-host. Stop here.

  ```bash
  claude mcp add --transport http neens https://app.neens.ai/mcp
  ```

- **`projectId` is null.** The connection is not pinned to one project. Ask which project to use
  before reading anything.
- **Otherwise** say in one line which project and company you are connected to. Every later
  action is scoped to it.

## Step 2: Read the loop

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

Pick the first row that matches what the user asked for. If they asked for nothing specific, pick
the first row that matches the project's state.

| Situation | Load |
|---|---|
| `list_traces` total is 0, or the user wants to send traces | `instrument-agent` |
| The user wants to know what is failing, or there are failure modes nobody has reviewed | `triage-failures` |
| A failure mode is confirmed and there is no dataset built from it | `build-regression-set` |
| A failure mode needs an automated check, or a judge's verdicts are in doubt | `write-judge` |
| There are open agent-fixable remediations, or the user wants to fix a failure | `fix-failure` |
| The user is about to ship a change (branch, prompt, model, config) and wants a go/no-go | `gate-release` |
| The user is choosing between models | `choose-model` |
| The user wants a status report: "how are we doing", weekly review, exec summary | `reliability-review` |

The usual order for a new project is `instrument-agent` → `triage-failures` →
`build-regression-set` → `write-judge` → `fix-failure` → `gate-release`. A project with open
remediations but no confirmed failure modes should still go through `triage-failures` first:
fixing a failure nobody has looked at is how the wrong thing gets fixed.

Tell the user which skill you are loading and why in one sentence, then follow that skill from
start to finish. If two rows fit equally, ask which one they want.
