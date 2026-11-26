---
name: debug-user-report
description: >
  Investigate one reported incident: a customer, support agent or colleague says the agent gave a
  wrong answer, did the wrong thing, or failed in a specific conversation. Finds the trace in
  Neens from what the reporter remembers, reads it to the first step that went wrong, says
  whether it is a known failure mode and how many other conversations it hit, records the verdict,
  and turns the trace into a regression test so it cannot come back unnoticed. Use when the user
  pastes a complaint, a ticket, a screenshot of a conversation, or asks "why did the agent say X".
  Do NOT use for a broad "what's failing" question (`triage-failures`).
---

# Debug a User Report

Go from "a customer says the agent told them X" to the trace, the cause, how often it happens, and
a regression test. One report is one data point; the value is in finding out whether it is one of
many.

Neens tools are called by their bare names here (`list_traces`). Your client may prefix them, for
example `mcp__neens__list_traces` in Claude Code.

## Step 1: Find the trace

Call `get_current_project`. Then ask the user for whatever the reporter has: a conversation or
session id, the time (with time zone), the user's words, the agent's words, the agent or
environment. Search with what you have, narrowest first:

1. An id: `list_traces` with `{"conversation_id": "<id>"}`, or `get_trace` with the trace id.
2. Words and a time: `list_traces` with `q` set to a distinctive phrase the user or the agent
   said, and `started_after`/`started_before` an hour either side of the reported time.
3. Only a time: the same time bounds with `agent_name`, then read the candidates.

If several traces match, show them (time, agent, first user turn) and ask the user which one.
Never pick one silently. If nothing matches, widen the time window once, then say what you
searched for and ask for more detail. The trace may not have been sent to Neens (sampling, a
different environment): say that is possible.

## Step 2: Read it to the first wrong step

`get_trace` on the trace. If its `turnCount` says it is not the first turn, read the earlier
traces in the conversation too: `list_traces` with its `conversation_id` when the reporter gave
one (trace replies do not carry it; the user can copy it from the trace in Neens). The wrong
answer often starts with context from an earlier turn.

Read in order: what the user asked, each tool call's arguments and result, the agent's answer.
Find the first step where it went wrong and quote it. Then classify:

| Verdict | Evidence |
|---|---|
| **Agent-fixable** | Wrong tool or arguments, an answer the tool results do not support, an ignored instruction, a missed step |
| **Downstream** | A tool or service returned an error or wrong data and the agent passed it on faithfully |
| **Working as intended** | A guardrail or policy did what it should; the reporter expected something the agent must not do |
| **Not reproducible from the trace** | The trace shows a correct answer, or the content the report is about is not in it |

If `get_trace` truncates the content you need (`complete` false), ask the user to open the trace in
Neens (**Traces**, then the id) and read the step to you.

Confirm the verdict with the user before recording anything.

## Step 3: How widespread is it?

The `failureMode` field on the trace's `list_traces` row says whether clustering already put it in
a failure mode.

- **A known mode.** `get_failure_mode` with its id gives the member count, the trend and whether a
  fix exists. Tell the user: "This is one of 37 conversations in *Order status contradicts lookup*
  this week; a fix is in review."
- **No mode.** Look for siblings: `list_traces` with the same `tool_name`, a phrase that marks the
  failure in `q`, or `{"score_metric": "<key>", "score_status": "fail"}` if a judge covers it, over
  the last 7 days. Read two or three. Report the count, and say it is a lower bound: search finds
  only what the phrase matches.

## Step 4: Record it

With the user's confirmation:

1. `add_annotation` on the trace:
   `{"target_type": "session", "target_id": "<id>", "verdict": "fail", "critique": "<the observed failure in one or two sentences>", "is_gold": true}`.
   Add `cluster_id` when the trace is in a known mode. Record `"verdict": "pass"` instead when the
   agent was right; that label is just as useful.
2. Add it to a regression set. If the mode already has a dataset, `add_to_dataset` with
   `{"dataset": "<name or id>", "session_ids": ["<id>"]}`. Otherwise create one with
   `create_dataset` and hand off to `build-regression-set` to freeze it with passing controls.
3. If the mode has no fix yet, `generate_remediation` with `{"cluster_id": "<id>"}`, then
   `fix-failure`.

For a downstream verdict, write the ticket text instead: the service, the error, the trace id and
how many other traces it hit.

## Step 5: Answer the reporter

Write a short reply the user can send back, in plain words and without internal ids unless the
reporter is technical: what happened, whether it is a known issue, what is being done, and when
they can expect it fixed if the user knows.

## Anti-patterns

- **Guessing the trace.** Ask when more than one matches.
- **Fixing one conversation.** A prompt patch for one report is how prompts grow contradictory.
  Find out how many conversations share the failure first.
- **Recording your own verdict.** Ground truth comes from a person.
- **Dropping the report after the answer.** Without a regression test the same complaint comes back.
