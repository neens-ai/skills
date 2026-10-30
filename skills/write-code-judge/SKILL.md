---
name: write-code-judge
description: >
  Write a deterministic Python code judge in Neens for ONE confirmed failure mode that a rule can
  decide: the output's schema or format, a required tool call or its arguments, a policy pattern
  (leaked internals, PII, unfilled placeholders), or a numeric threshold. The code runs in Neens's
  sandbox; test it on real known-pass and known-fail traces, check it against the user's verdicts,
  then deploy it. It can ask the agent's LLM one brokered question (ctx.llm) for a hybrid check.
  Use when the user asks for a code judge, a deterministic or rule-based check, or when
  `write-judge` Step 2 routes a failure here. Do NOT use when deciding the verdict takes judgment
  (grounding, tone, the right action for the request); use `write-judge`. Do NOT use when a
  `list_traces` filter already measures the failure exactly (an error status, a timeout).
---

# Write Code Judge

Some failures are rules: the reply must be valid JSON, an order question must trigger a
`lookup_order` call, a reply must never show a stack trace, an answer must stay under a word
budget. A rule written as Python gives the same verdict every time, costs no model call, and has
no prompt to drift. It still has to agree with the person who owns the agent, so this skill tests
it on real traces and checks it against that person before it scores anything automatically.

## Prerequisites

- A confirmed failure mode, ideally with labeled traces from `triage-failures`: some that show the
  failure and some that pass on the same path.
- The MCP connection is a signed-in user who can configure judges. A project API key can save a
  code judge but cannot run `test_code_judge`.
- Code judges are on the user's plan (Neens Gold) and code execution is on for the deployment.
  Step 1 checks the second; the first shows up as a 403 (see "When code judges are not available").

## Step 1: Reuse, then read the sandbox

1. Call `list_judges` with a `q` naming the failure. If a judge already targets it, check that one
   (Step 5) instead of writing a duplicate.
2. Call `list_code_runtimes`. Read three things:
   - **`executionEnabled`.** If it is false, code will save but never run. Stop and go to
     "When code judges are not available".
   - **`runtimes`.** The `default` runtime and its exact `packages`. The code may import the
     standard library and those packages, nothing else. Nothing is installed at run time.
   - **`limits`.** Time and memory per trace: 5 s and 256 MB by default, at most 30 s and 1,024 MB.

## Step 2: Is a rule the right tool?

A rule fits when two careful people reading the same trace could not disagree:

| The failure | Rule | Reads |
|---|---|---|
| The output is not valid JSON, or misses a required field | `json.loads`, or `jsonschema` when the runtime lists it | `output` |
| A required tool was not called, or was called with the wrong arguments | Find the tool span in `messages` by `name` and `kind`, parse its `input` | `messages` (+ `input` for the condition) |
| The reply leaks internals or PII, or has an unfilled template | Regular expressions | `output` |
| A number is over budget (words, items, characters) | Count and compare | `output` |

If the verdict needs judgment (is the answer supported by the tool result, was it the right action,
is the tone right), use `write-judge`. If a `list_traces` filter (`status`, `tool_name`,
`min_duration_ms`) already measures it exactly, say so and stop: a judge adds nothing.

A rule with one judgment call in the middle (parse the JSON, then ask whether the apology is
sincere) can use `ctx.llm`. See Step 3. The judge is then no longer deterministic, so the check in
Step 5 matters as much as for an LLM judge.

## Step 3: Write the code against the real contract

```python
import re

ORDER = re.compile(r"\border\s+#?(\d{3,})", re.I)


def judge(target, ctx):
    request = target.get("input") or ""
    if not ORDER.search(request):
        ctx.skip("no_order_question")      # not this rule's business: skipped, not passed
    tools = [m.get("name") for m in target.get("messages", []) if m.get("kind") == "tool"]
    if "lookup_order" in tools:
        return {"label": "pass", "reason": "called lookup_order before answering"}
    return {"label": "fail", "reason": f"answered an order question without lookup_order (tools: {tools or 'none'})"}
```

The contract, as Neens enforces it:

- **The function.** A top-level `def judge(target)` or `def judge(target, ctx)`. Module-level
  imports, constants and helpers are fine. Nothing carries over between traces: each verdict
  depends on its own trace only.
- **`target`** holds only the keys named in `required_data`: `input` (text), `output` (text,
  empty when the trace has none), `messages` (every span in order, each with `name`, `kind`,
  `status`, plus `input`, `output` and `error` when present), `context`, the trace's expected
  output, and `metadata` (`agent_name`, `status`, `turn_count` and the trace's own metadata).
  Optional keys are absent, not `None`, so always use `target.get(...)`. Long text is cut.
- **The return value** is a dict whose shape matches `output_spec`. With no `output_spec` the scale
  is 0 to 1 and the code must return `{"score": <0..1>}`. For pass/fail, pass
  `"output_spec": {"type": "binary", "pass_label": "pass", "fail_label": "fail"}` and return
  `{"label": "pass"}` or `{"label": "fail"}`. `"reason"` is optional on every scale; write one
  that names the evidence, because it is what the reviewer and the reports show. A shape that
  does not match the scale, a value off the scale, NaN, or anything that is not a dict fails the
  trace with an invalid return value. Neens never clamps or guesses.
- **`ctx`.** `ctx.skip("reason")` marks the trace skipped: neither pass nor fail, so it does not
  drag the pass rate. Use it for traces the rule does not apply to. `ctx.log` prints,
  `ctx.target_id` is the trace id, and `ctx.now` is the run's start time (use it instead of the
  wall clock, so a rerun grades the same).
- **The sandbox has no network.** Calls to any URL, API or webhook fail, nothing can be installed,
  there are no secrets or environment settings, and only `/tmp` is writable. Code over 64 KB
  cannot be saved, and printed output is capped at 16 KB.
- **`required_data`** names only what the code reads, for example `["input", "messages"]` above.

**`ctx.llm`, for a hybrid check.** Pass `"capabilities": {"llm": true}`, then call
`ctx.llm(prompt, max_tokens=5)` (or `json=True` for a parsed reply, `system=` for a system
prompt). Neens makes the call through the agent's own LLM connection, applies its PII redaction
policy, and hands back only the reply: the provider key never enters the sandbox. At most 5 calls
per trace and 2,000 per run; `max_tokens` is capped at 1,024. Keep the question short and closed.
Saving code that calls `ctx.llm` without the capability is refused, and with no LLM connection
every such trace fails with `CapabilityUnavailable`.

## Step 4: Test it on real traces before saving

Pick traces whose verdict you already know: at least one confirmed failure, one confirmed pass on
the same path, and one the rule should skip. Take them from the triage labels or from
`list_traces` with the failure's `cluster_id`. Then call `test_code_judge`:

```json
{"code": "<the Python source>", "trace_ids": ["<known fail>", "<known pass>", "<should skip>"],
 "required_data": ["input", "messages"],
 "output_spec": {"type": "binary", "pass_label": "pass", "fail_label": "fail"}}
```

It runs the unsaved code in the sandbox on up to 3 traces and saves nothing. Read each row of
`results`:

- **`pass` and `score`** are the verdict. A row's `label` is Neens's display name for the trace,
  not the label your code returned, so do not read the verdict from it.
- **`error`** has a `class`, a `message` and the `line` of your code. `invalid_result` with
  "expected {"score": number}" means the code returns a label but no binary `output_spec` was
  passed. `user_exception` is your code raising, including `ModuleNotFoundError` for a package the
  runtime does not have and connection errors from network calls.
- **`skipped`** with `skipReason` is a `ctx.skip`.
- **`notInProject`** lists trace ids that are not in this project. They were never read.
- **`definitionError`** (with `executed: false`) names the field and line to fix before anything runs.

Every known trace must come back with the verdict you expected. Fix and test again until it does.
A test run is capped at 10 seconds in total and about 20 runs a minute per person, and it counts
against the company's daily code-execution budget. A 429 or "the code sandbox is busy" means retry
in a few seconds.

## Step 5: Create, run, and check it against the user

1. `create_judge` with `name` (for example `code-<failure-slug>`), `type: "custom_python"`,
   `description`, `code`, `required_data`, `output_spec`, and `scope: "trace"`. Add `limits`,
   `capabilities` or `requirements` only if Step 3 needed them. Do not pass `prompt_template` or
   `criteria`: they are refused on a code judge. The reply names the pinned `runtime` and `limits`.
   `level` stays `project`; `org` or `platform` runs the code on every agent and needs a company admin.
2. `deploy_judge` with `{"judge_id": …, "trigger_policy": "manual", "success_threshold": 0.5}`.
3. `run_eval` with `{"judge_id": …, "target_ids": [<up to 20 traces the user has labeled, or will>]}`,
   then `get_eval_run` with the `run_id`. Each task carries `score`, `label` ("pass" or "fail")
   and `reason`; skipped traces are counted in `statusCounts`. `passRate` is passed over scored.
   `successRate` is the share of tasks that finished, not the pass rate.
4. If the user has not labeled these traces yet, show them in batches of five as `write-judge`
   Step 5 does, **without the judge's verdict**, and record each answer with `add_annotation`
   (`"target_type": "trace"`, `"is_gold": true`).
5. `list_judge_disagreements` with `{"judge_id": …}` returns the live disagreements: `falseAlarms`
   (the code failed a trace the user passed) and `misses` (it passed a real failure), each with
   the code's reason and the user's critique. `get_judge_alignment` adds precision, recall and
   Cohen's kappa once Neens has measured them; until then it says no measurement exists yet.

Report both sides as counts: "false alarms 1 of 8, misses 0 of 9". The bar is the same as for an
LLM judge: at most 1 wrong in 10 on each side. A rule that disagrees with the user is usually
right about the trace and wrong about the failure: the condition is too broad (false alarms) or
the pattern too narrow (misses). Read each disagreement with the user.

## Step 6: Iterate or ship

**It misses the bar.** Change the rule, `test_code_judge` it on the disagreeing traces, then
`create_judge_version` with `{"judge_id": …, "code": "<new source>", "note": "<what changed>"}`.
Every setting you do not name carries over. Then `deploy_judge` with the reply's `versionId`,
`run_eval` with the new `deployment_id` (with two deployments enabled, `judge_id` alone is
refused as ambiguous) on the labeled traces, and once it holds, `disable_deployment` on the old
deployment from `deploymentsOnOlderVersions`. `get_judge_runs` lists every run of the judge.

**It meets the bar.** Ask before making it continuous. A code judge makes no model call (unless
it uses `ctx.llm`), but every trace spends the company's daily code-execution budget. On a yes,
`deploy_judge` with `"trigger_policy": "on_new_trace"`. Verdicts appear a few seconds after each
trace arrives.

A checked code judge works wherever a judge does: pass its deployment id in
`judge_deployment_ids` to `create_preprod_run` (`gate-release`) or `run_verification`
(`fix-failure`).

## When code judges are not available

Say exactly what Neens returned, then offer `write-judge` with the rule written as the judge's
PASS and FAIL definitions. Do not keep retrying, and do not deploy a judge that cannot run.

- **Execution is off on the deployment.** `list_code_runtimes` says `executionEnabled: false`,
  `test_code_judge` returns `executed: false` with error class `disabled`, and any `run_eval`
  fails with "disabled: code judges are not enabled on this deployment". The judge can still be
  saved; an administrator has to turn code execution on before it scores anything.
- **A 403.** The plan does not include code judges, or the connection is not allowed to run code
  (it is a project API key, or the user cannot configure judges). The message does not always
  say which. Ask the user to check their plan and role.
- **"No code sandbox runner is available right now"**, or a busy sandbox: capacity, not your code.
  Retry later. **"Daily code-execution budget used up"**: traces are skipped until 00:00 UTC.

Composite judges that combine scores with a Python `combine()`, code enrichments, and custom
package environments use the same sandbox but are set up in the Neens UI (**Judges**,
**Enrichments**, **Settings → Code environments**). Point the user there when the rule needs one.

## Report

- The judge name and id, its runtime, and the failure mode it checks
- The test traces and the verdict on each, then the measured false alarms and misses, as counts
- Whether it is manual or continuous
- Next step: `build-regression-set`, `gate-release` or `fix-failure`, which use this judge as proof

## Anti-patterns

- **A rule for a judgment call.** A keyword list for "fabricated" or "rude" passes the failures
  it was not written for. Use `write-judge`.
- **Returning 0 for traces the rule does not cover.** That is a fake failure. Use `ctx.skip`.
- **Testing only on traces you expect to pass.** A rule that never fails anything looks perfect.
  Include a known failure.
- **Reaching for the network.** The sandbox has none. Put the check in the code or use `ctx.llm`.
- **Shipping because the code is deterministic.** Deterministic is not correct. Check it against
  the user first.
