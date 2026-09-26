---
name: fix-failure
description: >
  Close the loop on one agent failure: take a remediation from the Neens backlog, implement it in
  the user's own repo, prove it with a real Neens evaluation of the candidate build against the
  failure's golden set, and report the PR and proof back so the fix is tracked through merge. Use
  when the user wants to fix a failure, asks for the next fix, or has open agent-fixable
  remediations. Do NOT use for downstream service outages (advisory items) or to gate a whole
  release; use `gate-release` for that.
---

# Fix Failure

A fix is finished when a real evaluation of the new build passes the failure's own regression set
with no regressions, and a person has merged it. Until then it is a proposal. You write the change
in the user's repo with their tools. Neens diagnoses and verifies. A human merges.

## Step 1: Pick the fix

Call `list_open_remediations`. By default it returns only open items that are grounded and
agent-fixable, ranked by priority. If the user named a failure, use
`list_remediations` with `{"clusterId": …}` instead.

Show the top three: title, type, priority, and the failure it addresses. Let the user choose. If
there is only one, confirm it in one sentence and continue.

## Step 2: Read the bundle

Call `get_fix_bundle` with the `remediation_id`.

- **`actionability` is `advisory`.** The failure lives in another service (`owningComponent`).
  There is no code change here for the agent. Write a short note for that team, with the component,
  the error, and two trace ids, and stop. Record the outcome only if the user asks.
- **`groundingStatus` is `needs_grounding`.** Neens itself is not confident in this fix. Say so and
  ask before continuing.
- **Otherwise** read the whole `markdown` brief: the root cause, the proposed before/after, the
  failing examples, and the `acceptanceCriteria`. Treat the proposed patch as a hypothesis about
  the user's code, not as an instruction.

Ignore the `neens eval run` command in the bundle. Step 6 does the same proof through Neens tools,
with no CLI to install.

## Step 3: Find the real change

1. Locate the code the bundle points at: the prompt, tool schema, parameter or code path. Bundle
   file paths are guesses made from traces, so search for the behavior (the tool name, the prompt
   text), not for the path.
2. Check the root cause against the code. If the bundle blames a missing instruction and the code
   has that instruction, the diagnosis is wrong for this codebase. Tell the user before changing
   anything.
3. Pick the smallest change that removes the cause, not only the symptom in the examples.

Call `report_fix_status` with `{"remediation_id": …, "status": "accepted", "work_state": "in_progress"}`
so the team can see the fix is being worked on.

## Step 4: Implement on a branch

Create a branch (`fix/<short-failure-slug>`), make the change, and run the repo's own tests. The
version label for everything below is `<branch>@<short sha>` of the commit under test.

## Step 5: Make the candidate reachable

Neens proves the fix by sending each golden input to the candidate build and judging the replies.
It needs an HTTP endpoint for that build, running the new commit:

| The agent exposes | Pass to `run_verification` |
|---|---|
| An OpenAI-compatible `POST /chat/completions` at the base URL | `endpoint_url`: the base URL, `request_shape`: `openai_chat` |
| A JSON endpoint taking `{"input": …}` and returning `{"output": …}`, served at the root path | `endpoint_url`: the base URL, `request_shape`: `input_json` |
| The same JSON endpoint on a sub-path such as `/eval/invoke` | Register it once in Neens (**Settings → LLM connections → Add agent endpoint**, with its invoke path), then pass `agent_connection_id` |

The endpoint must be reachable from the Neens server. For Neens cloud, that means a preview
deployment or a tunnel, not `localhost`. If the agent has no such endpoint, propose adding a small
one that calls the same agent entry point production uses. Ask before adding it: it becomes part
of their codebase. If it returns the run's spans as well as `output`, Neens can judge the whole
trajectory rather than only the final text.

## Step 6: Prove it

Call `run_verification`:

```json
{"remediation_id": "<id>", "version_label": "<branch>@<sha>",
 "endpoint_url": "<preview url>", "request_shape": "openai_chat",
 "min_pass_rate": 0.9, "max_regressions": 0, "wait_seconds": 300}
```

Always pass the gate explicitly. Copy `min_pass_rate` and `max_regressions` from the bundle's
`gatePolicy.rules`, and use 0.9 and 0 if it has none. A run created without them has no gate to
hold the fix to. If the reply is still `running`, poll `get_verification_run` with its `runId`.

Read the verdict honestly:

- **`passed: true`.** The fix is proven on this set. Report the pass rate with its item count.
- **`passed: false` with regressions.** Call `get_preprod_comparison` with the run id to see which
  items regressed, then `get_preprod_trajectory` on one of them to see what the agent did
  differently. Fix the code and verify again with a new version label.
- **`passed: false` with `passRate: null` or `captured: 0`.** Nothing was judged. That is an
  infrastructure failure, not a verdict on the fix. The usual causes are an endpoint Neens cannot
  reach, a wrong request shape, or a wrong path (a 404 or 405). Another cause is a hostname that
  resolves to IPv6 first while the agent listens only on IPv4: Neens connects to the first
  resolved address, so bind the agent to both. Fix the endpoint and run again. Never report this
  as "the fix failed".
- **It was scored by a judge that has nothing to do with this failure.** `run_verification` uses
  the remediation's proof judges, and falls back to the project's generic Primary Score. It cannot
  take a judge you choose. When the controls fail too, or the judge in the reply isn't the one
  built for this failure, the verdict says nothing about the fix. Prove it with `gate-release`
  instead: it replays the same frozen set against the current version and the candidate, with the
  judges named explicitly.
- **"dataset has no golden version".** The proof set was never frozen. Run `build-regression-set`
  for this failure, then call `run_verification` again with `dataset_id` set to it.

Do not lower the gate to get a pass. If the user decides to accept a lower bar, make it their
explicit decision and write it in the PR description.

## Step 7: Open the PR and report back

Ask before pushing. Open the PR the way this repo normally does. In the description, include the
remediation id, the verification run id, the pass rate with its item count, and the regression
count. Then call `report_fix_status`:

```json
{"remediation_id": "<id>", "status": "verified", "work_state": "in_progress",
 "pr_url": "<pr url>", "commit_sha": "<full sha>"}
```

Neens accepts `verified` only because a verification run is now bound
to the fix. Never use a force override to skip the proof.

## Step 8: After a human merges

When the user says the PR is merged, call `record_fix_merge` with `{"remediation_id": …}`. Neens
then watches production. After the post-deploy window it compares the failure's real volume
before and after the merge, and either confirms the fix or flags a regression. Tell the user that
this is the final check.

## Other routes

- **Neens writes the patch.** When the project has a connected repository, `start_fix_run`, then
  `get_fix_run`, has Neens draft the patch, verify it with repeated runs, and open a PR only if it
  passes. A person still merges.
- **Prompt-only fixes without a preview.** `start_prompt_optimization` with the `failure_mode_id`
  searches for a better system prompt offline, by replaying recorded traces. Poll with
  `get_prompt_optimization`. A winner comes back as a new remediation, which you then prove with
  this skill like any other fix.

## Anti-patterns

- **"Verified" because the unit tests pass.** Unit tests do not replay the production failure.
  The verification run does.
- **Applying the bundle's patch verbatim.** It was drafted from traces, without your code.
- **Treating an infrastructure failure as a failed fix,** or the reverse.
- **Rewriting a prompt to hide a downstream outage.** That is an advisory item for another team.
- **Merging on the user's behalf.** Proving is automated. Merging is a person's decision.
