---
name: investigate-token-usage
description: >
  Find out why an agent uses (or is billed for) more tokens than expected, from real traces in
  Neens: duplicate requests, history that grows turn after turn, tool loops that re-send the
  context, a bloated system prompt, oversized tool results, a prompt cache that never hits, or
  verbose output. Measures how much of the spend each cause explains, recommends the fix, and
  sets Neens up to prove the fix and catch the pattern if it comes back. Use when the user says
  token usage or cost spiked, traces look huge, suspects duplicate or bloated requests, or asks
  where the tokens go. Do NOT use to pick a cheaper model (`choose-model`) or to diagnose a
  quality failure (`triage-failures`).
---

# Investigate Token Usage

Explain where an agent's tokens go, with a trace id behind every claim, and turn the answer into
something Neens can measure before and after the fix. "Tokens are high" has a handful of causes and
each one leaves a different shape in the traces. Find the shape first; recommend second.

Neens tools are called by their bare names here (`list_traces`). Your client may prefix them, for
example `mcp__neens__list_traces` in Claude Code.

## Step 1: Size the problem

Call `get_current_project`, then in parallel:

- `get_cost_quality_brief` with `{"page": "overview", "window": "30d"}`. Read the spend per version
  and per model, `per1kUsd` (spend per 1,000 traces), `pricing.partial` and `unpricedModels`, and
  the prompt-cache counts (`cacheReadInputTokens`, `cacheWriteInputTokens`). Spend for an
  unpriced model is null, never $0: say "unpriced", not "free".
- `list_agent_versions` with `{"window": "30d"}`. A version that started serving when the spend
  rose is the first suspect.
- `list_traces` with `{"limit": 1}` and `started_after` set to the window start, for the
  total trace count. Without `started_after` the count covers all time.

Ask the user what they compare against ("last month", "our estimate of 5k tokens a request",
"the provider bill") if they did not say. A spike against what?

## Step 2: Find where the tokens concentrate

`list_traces` rows do not carry token counts, but its `min_tokens` and `max_tokens` filters do,
and every reply carries the matching `total`. Count the traces in bands, each with `{"limit": 1}`
and the same `started_after` and `started_before`:

| Band | Filter |
|---|---|
| under 10k | `{"max_tokens": 10000}` |
| 10k to 50k | `{"min_tokens": 10000, "max_tokens": 50000}` |
| 50k to 200k | `{"min_tokens": 50000, "max_tokens": 200000}` |
| over 200k | `{"min_tokens": 200000}` |

Move the band edges to fit the agent. What you are looking for:

- **A long tail.** Most traces are small and a few are enormous: the cause lives in those few.
  Read them (Step 3).
- **Everything shifted.** The median trace grew: the fixed part of every request grew (the
  system prompt, the tool definitions, a new retrieval step) or a new version or model changed
  it. Compare the same bands with `version` set to each version from Step 1.
- **One conversation.** Run the top band again with `{"min_tokens": 200000, "limit": 50}`. If the
  rows cluster in one agent and one stretch of time, and `get_trace` on a few shows `turnCount`
  climbing and the same topic, they are likely one long conversation: Step 4's context-growth
  check comes first. Trace replies do not carry the conversation id, so ask the user to copy it
  from one of those traces in Neens (**Traces**, then the trace id).

Report the band counts as they are. A count is a count of traces, not of tokens; when you
estimate a share of tokens from bands, say it is a range.

## Step 3: Read the heaviest traces

Call `get_trace` on five to ten traces from the top band, plus two from a normal band as
controls. For each, write down:

| Field | What it tells you |
|---|---|
| `inputTokens`, `outputTokens` | Input-heavy (context) or output-heavy (verbose answers, long reasoning) |
| `cacheReadInputTokens`, `cacheWriteInputTokens` | Null = the trace did not report cache usage; 0 = it reported no hits |
| `estimatedCostUsd` | What this one trace cost; null = unpriced |
| `spanCount`, `toolCallCount`, the `spans` kinds | How many model calls the trace made. Input tokens divided by the number of `llm` spans is the average size of one request |
| `toolCalls` | Which tools ran, how often the same one repeated, and whether a `result` was cut (`…`, `complete` false): a cut result is a long one |
| `conversation`, `turnCount` | What the user asked, and how far into the conversation this trace is |
| `startedAt`, `agentName` | For finding duplicates and neighbours |

The trace's tokens are counted once per model call. Neens drops the totals that a wrapper span
repeats from its children for the frameworks it knows (Google ADK, the Vercel AI SDK), so a
wrapper and its child do not double the count there.

## Step 4: Match the shape to a cause

Check each cause in this order. Stop treating a cause as the answer until the evidence says so.

| Cause | Evidence that proves it | How to check |
|---|---|---|
| **Duplicate requests** | Two or more traces with the same first user turn and nearly identical token counts, started seconds apart. Often a client retrying after a timeout: the first copy ends in an error | `list_traces` with `q` set to a phrase from the user turn and `started_after`/`started_before` a minute either side; `get_trace` each match |
| **History grows across turns** | Within one conversation, each trace's `inputTokens` is larger than the last and never drops. The first turn is small | With the conversation id from the user (Step 2), `list_traces` with `{"conversation_id": "<id>", "limit": 50}`, then `get_trace` on the first, a middle and the last trace, in `startedAt` order |
| **Tool loops re-send the context** | One trace with many `llm` spans and the same tool called again and again; input per request is large, so the trace total is request size times loop length | `get_trace` span and tool-call counts; `get_failure_mode` `paths` with kind `retryLoop` when the loop also fails |
| **Large fixed prompt** | The first turn of a fresh conversation is already large, and every trace is | `lint_prompt` with `{"trace_id": "<a first-turn trace>"}`: its token-budget finding estimates the system prompt's size |
| **Oversized tool results** | Tool `result` values cut in `get_trace`, and the traces after that tool call are much larger | `get_trace` on a trace before and after the tool first appears. To see the full result, ask the user to open the trace in Neens (**Traces**, then the id) |
| **Prompt cache not used** | Long, repeated prefixes (growing history, a large fixed prompt) with cache reads null or 0 | Step 3's cache fields; null means the instrumentation does not report cached tokens, which the provider may still be applying |
| **Verbose output** | `outputTokens` large relative to the answer the user needed | `get_trace` `conversation` |
| **A model or version change** | The shift starts on the day a version or model started serving | `list_traces` bands per `version` or `model`; `get_cost_quality_brief` per model |

Several causes compound. History growth times a tool loop is the usual way one conversation costs
more than a thousand normal ones: each step of the loop re-sends the whole history.

## Step 5: Quantify and recommend

Present one table, ordered by how much of the spend each cause explains:

| Cause | Evidence (trace ids) | Traces affected | Share of tokens (range) | Fix |
|---|---|---|---|---|

Rules for the numbers:

- Every share carries the trace count behind it. "95% of tokens, from 1 conversation of 53
  traces" is honest; "95% of tokens" alone is not.
- A pattern seen in three traces is a hypothesis. Say so, and say how many traces you read.
- Null cost is unpriced, never $0.

The fixes that usually apply, to adapt to the user's framework:

| Cause | Fix |
|---|---|
| Duplicate requests | Make client retries idempotent; raise the client timeout above the agent's p95 latency |
| History grows | Start a new session per task, or compact: summarise older turns and drop raw tool results once used |
| Tool loops | Cap the iterations per turn; fix the tool that keeps failing (`triage-failures` on its failure mode) |
| Large fixed prompt | Trim the prompt and the tool definitions; move reference material behind a retrieval tool |
| Oversized tool results | Return only the fields the agent uses; paginate; cache static listings outside the history |
| Prompt cache | Turn on the provider's prompt caching with a stable prefix; report cached tokens in the spans |
| Verbose output | An output-length instruction and a lower max output tokens |

If a cause is in the instrumentation rather than the agent (cached tokens not reported, a token
count Neens cannot attribute), hand off to `instrument-agent`.

## Step 6: Set Neens up to prove the fix

The fix is a change to the agent, so prove it the way any change is proven: on the same traffic,
before and after, with quality held.

1. **Freeze the evidence.** With the user's agreement, `create_dataset` with
   `{"name": "token-usage-<date>", "session_ids": ["<the heavy traces>"]}`. It is the set to
   replay against the fixed build.
2. **Prove cost dropped and quality held.** After the fix ships under a new version label, compare
   the same `list_traces` bands with `version` set to the old and the new label, and
   `get_cost_quality_brief` with `{"page": "overview"}` for each version. Then run `gate-release`
   on the candidate: a cheaper agent that answers worse is not a fix.
3. **Catch it next time.** Offer, and do only with the user's yes:
   - a code judge (`write-code-judge`) that fails a trace whose `messages` hold more than N `llm`
     spans, or the same tool call repeated more than N times: it guards the loop shape
     continuously and in CI. A code judge does not see token counts, so it guards the shape, not
     the number;
   - an alert rule on spend in the Neens app (**Alerts**, https://app.neens.ai/docs/guides/alerts/);
   - a Scout standing instruction, for example `create_standing_instruction` with
     `{"text": "Every Monday, list this agent's traces over 200k tokens and the conversations they belong to", "cron": "0 9 * * 1"}`.

## Anti-patterns

- **Calling it duplicates without matching traces.** Duplicates are two traces with the same
  input seconds apart. Large traces are not duplicates.
- **Averaging.** An average trace size hides a long tail. Band the traces.
- **Reading one trace.** One huge trace is a lead. The cause is what a group of them share.
- **Blaming the model for context the agent sends.** Switching to a cheaper model shrinks the
  price of a bloated request, not the bloat.
- **Recommending a cut without a quality check.** Every token fix changes what the model sees.
  Prove it with `gate-release`.
