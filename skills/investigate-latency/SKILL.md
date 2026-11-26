---
name: investigate-latency
description: >
  Find out why an agent is slow, from real traces in Neens: a slow tool, MCP server or
  sub-agent, a slow model, too many sequential steps, retries and timeouts, or long contexts.
  Names the step the time goes to, separates what the agent controls from what a downstream
  service owns, and sets Neens up to prove the fix. Use when the user says the agent got slow,
  users complain about response time, p95 latency rose, or requests time out. Do NOT use for token
  cost (`investigate-token-usage`) or for failures that are not about time (`triage-failures`).
---

# Investigate Latency

Find where the time goes, step by step, with trace ids behind every claim. A trace's duration is
the sum of its sequential steps, so the question is always: which step, how often, and who owns it.

Neens tools are called by their bare names here (`list_traces`). Your client may prefix them, for
example `mcp__neens__list_traces` in Claude Code.

## Step 1: Size the problem

Call `get_current_project`, then in parallel:

- `list_components` with `{"range": "7d"}`: every tool, MCP server, sub-agent and skill the agent
  invoked, with its latency p50/p95, error rate and invocation count. A rate over too few
  invocations is null (thin): say "too few to tell", not zero.
- `list_agent_versions` with `{"window": "30d"}`: did a version start serving when it got slow?
- `list_traces` with `{"limit": 1}` for the total.

Ask what "slow" means to the user if they did not say: a p95 target, a timeout in their client,
or "it used to take 5 seconds".

## Step 2: Find the slow traces

`list_traces` takes `min_duration_ms` and `max_duration_ms` and returns the matching `total`.
Count the traces in bands with `{"limit": 1}`, for example under 5 s, 5 to 15 s, 15 to 60 s and
over 60 s, over the same `started_after`/`started_before`. Then:

- **Compare windows.** The same bands for the previous week tell you whether the tail grew or
  everything shifted.
- **Compare versions and models.** The same bands with `version` or `model` set. A shift that
  starts with one version is a change in the agent.
- **Compare outcomes.** The slow band with `{"status": "error"}`: slow traces that also fail are
  usually timeouts and retries.

## Step 3: Read where the time goes

`get_trace` on five to ten traces from the slowest band and two from a normal band. For each,
read `durationMs`, every span's `durationMs` and kind, and each tool call's `durationMs` and
`error`. Sum the spans by kind and by name, and find the one or two that hold most of the time.

Then check the shapes:

| Shape | Evidence | Owner |
|---|---|---|
| **One slow component** | One tool, MCP server or sub-agent holds most of the duration; its p95 in `list_components` is high | Its owner. A third-party service is downstream: not fixed in the agent |
| **Timeouts and retries** | The same call repeated with errors before it succeeds; `get_failure_mode` `paths` shows `retryLoop` or `recoveredRetry` | Retry policy is the agent's; the failing service is downstream |
| **Too many steps** | Many `llm` spans in sequence, each of normal length | The agent: planning, tool choice, or a loop |
| **Slow model calls** | `llm` spans long relative to their output; worse with long contexts | The agent's model choice and context size (`investigate-token-usage` if the context grew) |
| **Sequential calls that could run together** | Independent tool calls one after another | The agent's orchestration |

For the slowest component, `get_component` with its `kind` and `name` lists recent invocations
with trace ids, versions, statuses and errors. When several failure modes start inside the same
component, `get_failure_mode` on each names it as `componentOwner`.

## Step 4: Report and recommend

One table, ordered by the share of time each cause explains:

| Cause | Evidence (trace ids) | Traces affected | Time it explains | Owner | Fix |
|---|---|---|---|---|---|

- Give latency as p50 and p95 with the number of traces or invocations behind each. An average
  hides the tail users complain about.
- Say which causes belong to the agent and which to a downstream service. For a downstream one,
  write two or three sentences the user can paste into a ticket: the component, its p95, how many
  traces it hit, and two trace ids. A prompt change does not make a slow service fast.
- For a model choice, hand off to `choose-model`: a model sweep measures latency beside quality
  and cost, so a faster model is chosen on evidence.

## Step 5: Set Neens up to prove the fix

1. **Freeze the slow traces.** With the user's agreement, `create_dataset` with
   `{"name": "latency-<date>", "session_ids": ["<the slow traces>"]}`.
2. **Prove it.** After the fix ships under a new version label, compare the duration bands for the
   old and new `version`, and `list_components` for the component you changed. Run
   `gate-release` on the candidate so a faster agent that answers worse is caught before it ships.
3. **Catch it next time.** Offer, and do only with the user's yes: an alert rule on latency in the
   Neens app (**Alerts**, https://app.neens.ai/docs/guides/alerts/), or a Scout standing
   instruction, for example `create_standing_instruction` with
   `{"text": "Every Monday, tell me which component's p95 latency rose most against the week before", "cron": "0 9 * * 1"}`.

## Anti-patterns

- **Averages.** Report p50 and p95, with counts.
- **Blaming the model first.** Read the spans. Most slow traces are slow because of a tool or a
  loop, not because one model call is slow.
- **Fixing a downstream service in the prompt.** Telling the agent to "be faster" changes nothing.
  Route it to the owner.
- **One trace.** A slow trace is a lead. The cause is what the slow band shares.
