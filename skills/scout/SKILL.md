---
name: scout
description: >
  Work with Scout, the Neens background agent that investigates an agent's failures on its own:
  read what it found and why, check or change what it may do (level, budget, pause, the write tools
  it may run at the act level), and give it standing instructions such as "every Monday, tell me
  what changed". Use when the user asks what Scout found or did, wants Scout turned on, off or
  limited, or wants a recurring or event-triggered check. Do NOT use to act on a next action
  yourself; `neens-start` routes those to the skill that does the work.
---

# Scout

Scout investigates on its own after an event (an alert, new insights, a clustering run, a fix's
efficacy verdict, a judge drifting from reviewers, a new agent version) and writes a finding. A
finding is agent-written: it is a lead, not ground truth, and a plan it recommends waits for a
person. Settings changes are admin-only and cost money, so propose them and wait for a yes.

If `get_ambient_settings` does not exist on this server, Scout is not turned on there. Say so and
stop. A server can have Scout without the newer tools: if a tool named below (for example
`create_standing_instruction`, or `act_tools` in `update_ambient_settings`) is missing, say that
part is not available on this Neens yet and do the rest.

## Step 1: Read the settings

Call `get_ambient_settings`. Report in one line each: the level, whether it is paused, the budget
spent and reserved against the period's budget, and any held targets.

- **Level** (only the values in `selectableLevels` can be set) `off` does nothing; `suggest` (the default) ranks next actions but starts no
  investigation; `investigate` investigates events and writes findings; `act` also runs the write
  tools listed in `actTools` itself, chosen from `actEligible`.
- **Held targets** (`quarantined`) are ones Scout stopped after repeated failed runs.
  `release_ambient_quarantine` with a held target's `id` as `quarantine_id` starts it again; it
  has no undo, and a target that keeps failing is held again.

## Step 2: Read what Scout found

`list_ambient_runs` with `{"limit": 10}` is the run log, newest first; filter with `status`.
`include_memory` adds the notes Scout keeps between runs. For one run, `get_ambient_run` with its
`run_id` returns the trigger, each turn's tool calls, and the finding with its confidence and the
ids it cites.

- Before repeating a finding, open one or two cited traces with `get_trace` and check the claim.
  Say "Scout found…", never "Neens confirmed…".
- `recurrenceOf` names the earlier run whose conclusion this one re-checked.
- `waiting` means the run is paused until a long-running job it started ends (`waitingOn`).
  `skipped_no_connection` means no LLM connection (Settings → LLM providers); `budget_refused`
  means the budget ran out; `stopped` means a guardrail ended the run.
- `get_ambient_trace_project` with the `run_id` gives the run's own trace (`sessionId`,
  `projectId`) when its traces are sent; `get_trace` under that project shows every model and
  tool call.
- `cancel_ambient_run` stops a queued, running or waiting run; ask first.
- `get_ambient_signal_quality` shows how useful people rated each kind of next action, and which
  kinds the ranking demotes or mutes.

## Step 3: Change what Scout may do

Show the current values from Step 1, the change, and its cost, then wait for the user's yes.
Call `update_ambient_settings` with only what changes, for example `{"paused": true}` (the kill
switch), `{"level": "investigate"}`, or `{"budget_usd": 20, "budget_period": "week"}`. To undo,
send the previous values.

For `act`, `act_tools` is the whole allowlist (it replaces the stored one; `[]` allows none), from
`actEligible` only: building a regression set, drafting a judge, checking it against reviewers'
verdicts, and running an existing deployment. Scout never deploys a judge. Allow the fewest tools
that do the job.

## Step 4: Standing instructions

A standing instruction is the user's own request to Scout, in their words, on a schedule or an
event. Results go only to that person.

- `list_standing_instructions` lists the user's own; pass `instruction_id` for one with its latest
  results. A non-empty `waitingOn` says why it is not running (the level is below investigate,
  Scout is paused, or the target is held).
- `create_standing_instruction` with `text` and EITHER `cron` + `timezone` (five fields, at most
  about hourly) OR `condition_kind` (+ `condition_target_id` to narrow it). For example
  `{"text": "Review this agent and tell me what changed", "cron": "0 9 * * 1", "timezone": "Europe/Berlin"}`.
  `slack` also sends results as a Slack DM; `once` ends it after the first result. Confirm the
  wording and schedule with the user before creating it; there is a per-person limit.
- `update_standing_instruction` with `instruction_id` and only what changes; `paused` stops or
  resumes it.
- `end_standing_instruction` stops it for good and frees its place under the limit (pausing does
  not). There is no undo, so ask first. No tool deletes an instruction; if the user asks to delete
  one, end it and tell them deleting is done by them in Settings.

## Report

- Scout's level, pause state and budget
- Each finding cited with its run id, and whether you checked it against the traces
- Any change made, with the previous values needed to undo it
