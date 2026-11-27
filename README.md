# Neens Skills

Skills that teach a coding agent (Claude Code, Codex, Cursor and any agent that reads `SKILL.md`) to run the
[Neens](https://neens.ai) failure-to-fix loop on your own agent: find what is failing, prove a
fix, and make sure it cannot come back.

Neens exposes the loop as an MCP server of up to 109 tools (the set depends on which features your Neens has turned on). The tools are the raw capability.
These skills are the judgment about how to use them: which call comes first, what counts as
evidence, what a number means, and when to stop and ask a person.

## The Neens way

Every skill in this repo follows eight rules:

1. **Evidence before opinion.** Read real traces before naming a failure, writing a judge or
   proposing a fix. Every claim cites a trace id or a run id.
2. **A person owns the verdict.** The agent proposes. Ground-truth labels, "this is a real
   failure" and "ship it" come from a human.
3. **One failure, one test.** A judge checks one failure mode, returns pass or fail, and is checked
   against a person before it gates anything.
4. **Freeze before you measure.** Runs replay immutable golden versions, so results stay
   comparable over time.
5. **Every fix ships with its proof.** A fix is done when a real evaluation of the candidate build
   passes the failure's regression set with zero regressions. Unit tests passing is not proof.
6. **Fix where the failure lives.** A downstream outage goes to its owner, not into the prompt. A
   guardrail that fired correctly is not a bug.
7. **Honest numbers.** Null means no data, never zero. Every rate carries its sample size. A void
   comparison is never ranked. Two out of three is not a pass.
8. **A person merges.** Neens and your coding agent diagnose, implement and prove. A person
   decides what ships.

## Skills

| Skill | Use it when |
|---|---|
| [neens-start](skills/neens-start/SKILL.md) | You're not sure where to begin. Checks the connection, reads the next actions and the action inbox, routes you. |
| [instrument-agent](skills/instrument-agent/SKILL.md) | No traces yet. Wires OpenTelemetry to Neens for your framework and proves a trace arrived intact. |
| [triage-failures](skills/triage-failures/SKILL.md) | "What's failing?" Reads the evidence, locates each failure, records your verdicts. |
| [build-regression-set](skills/build-regression-set/SKILL.md) | A failure is confirmed. Freezes its traces, plus passing controls, into a golden set. |
| [write-judge](skills/write-judge/SKILL.md) | A failure needs an automated check that takes judgment. Writes a pass/fail LLM judge and measures it against you; for two acceptable answers, an advisory blind pairwise judge calibrated on your pair labels. |
| [write-code-judge](skills/write-code-judge/SKILL.md) | A rule decides the failure (a schema, a required tool call, a pattern, a limit). Writes a sandboxed Python judge, tests it on real traces, and measures it against you. |
| [fix-failure](skills/fix-failure/SKILL.md) | Time to fix. Implements the fix in your repo (answering earlier reviewers' rejections), proves it, and reports PR, proof and review state back. |
| [gate-release](skills/gate-release/SKILL.md) | "Can we ship this?" Replays every regression set against the candidate, reads each delta against its noise band, and returns GO, NO-GO or NO DATA. Can ablate a prompt change section by section. |
| [choose-model](skills/choose-model/SKILL.md) | "Which model?" Runs a pass^k model sweep and reads it honestly, with an optional advisory blind pairwise comparison of the top two. |
| [reliability-review](skills/reliability-review/SKILL.md) | "How are we doing?" A one-page, evidence-backed status report: targets, failure modes, the fix loop with owners, and which failure modes have an eval gate. |
| [scout](skills/scout/SKILL.md) | "What did Scout find?" Reads Scout's findings, checks or changes what it may do, and sets standing instructions. |
| [investigate-token-usage](skills/investigate-token-usage/SKILL.md) | "Why are we burning so many tokens?" Bands traces by size, reads the heaviest, and separates duplicate requests, growing history, tool loops, bloated prompts, oversized tool results and cache misses, with the share of tokens each explains. |
| [investigate-latency](skills/investigate-latency/SKILL.md) | "Why is the agent slow?" Finds the step the time goes to, by component and by trace, and separates what the agent controls from what a downstream service owns. |
| [investigate-regression](skills/investigate-regression/SKILL.md) | "It got worse after Tuesday." Compares failure modes, scores and components across windows and versions, and names the change behind the drop. |
| [debug-user-report](skills/debug-user-report/SKILL.md) | "A customer says the agent told them X." Finds the trace, reads it to the first wrong step, says how many other conversations it hit, and turns it into a regression test. |
| [find-failing-component](skills/find-failing-component/SKILL.md) | "Which tool is breaking us?" Ranks tools, MCP servers, sub-agents and skills by impact, reads the agent's own papercuts, and decides whether the contract, the agent or a downstream service is at fault. |

`instrument-agent` covers Google ADK, AWS Bedrock AgentCore, Strands, LlamaIndex, Agno, smolagents,
Pydantic AI, the Vercel AI SDK, LangGraph, the OpenAI Agents SDK, CrewAI and the Claude Agent SDK,
plus plain OpenTelemetry for anything else.

`neens-start` routes from `get_next_actions`, the ranked next best actions on the agent's card,
when Scout (the Neens background agent) is turned on. `scout` reads what Scout investigated and
manages its settings and standing instructions. `write-judge` checks a draft judge against your
existing verdicts with `check_judge_agreement` before deploying it, where the server has it.
`choose-model` can add `start_pairwise_comparison`, a blind A/B preference between the top two
arms, as supporting evidence; it never ranks the models or decides a gate.

`neens-start` and `reliability-review` also read `get_action_inbox`, the same ranked "what to fix
next" queue as the Insights page: what changed against the previous window, how many open items
sit at each fix-loop stage (needs fix, fix proposed, in PR, verified, downstream), and the top
rows with the ids the next call needs. It is read-only; rating rows is something people do in the
Insights page, not agents. On a Neens server that does not have the tool yet, both skills fall back
to surveying the loop with the individual list tools.

The five `investigate-*`, `debug-*` and `find-*` skills start from a question someone asks about an
agent in production, not from the loop. Each ends the same way: the evidence is frozen in a dataset,
the fix is proven with `gate-release`, and a judge, alert or Scout instruction is offered so the
problem is caught if it comes back.

The usual path for a new agent:

```
instrument-agent → triage-failures → build-regression-set → write-judge or write-code-judge → fix-failure → gate-release
```

`write-judge` sends a failure to `write-code-judge` when a rule decides it, and both judges can
prove a fix in `fix-failure` and gate a release in `gate-release`.

## Install

### 1. Connect Neens

Add the Neens MCP server, `https://app.neens.ai/mcp`, to your coding agent. For example:

```bash
claude mcp add --transport http neens https://app.neens.ai/mcp        # Claude Code
codex mcp add neens --url https://app.neens.ai/mcp && codex mcp login neens   # Codex
```

Cursor, VS Code and any other MCP client take the same URL in their MCP config. A browser window
opens to sign in to Neens (SSO works); pick the agent this connection is for. If you self-host, use
your own Neens URL. Per-client setup: [Connect a coding agent](https://app.neens.ai/docs/coding-agents/connect/).
The skills themselves are documented at [Skills](https://app.neens.ai/docs/coding-agents/skills/).

### 2. Add the skills

As a Claude Code plugin:

```text
/plugin marketplace add neens-ai/skills
/plugin install neens@neens
```

The skills then appear as `neens:triage-failures`, `neens:fix-failure` and so on.

Or copy them into any agent that reads `SKILL.md` files, for example with
[`npx skills`](https://github.com/vercel-labs/skills):

```bash
npx skills add https://github.com/neens-ai/skills
npx skills add https://github.com/neens-ai/skills --skill triage-failures   # just one
```

### 3. Start

```text
Where do I start with Neens?
What's failing in my agent this week?
Take the top open Neens fix and prove it against my preview deploy.
Can we ship branch fix/refund-policy?
```

## Requirements

- A Neens agent with an MCP connection. Traces are needed for everything except
  `instrument-agent`.
- An LLM connection in Neens (**Settings → LLM providers**) for judges and fixes.
- `write-code-judge` needs a plan that includes code judges, code execution turned on for your
  Neens deployment, and a signed-in MCP connection (a project API key cannot run code). The skill
  says what to do when any of these is missing.
- `fix-failure`, `gate-release` and `choose-model` need your agent reachable over HTTP from Neens
  (a preview deploy, for example), or a harness that replays golden inputs. Each skill explains
  both options.

## How they were tested

Every skill was run end to end by Claude Code against a real Neens instance. The data was traffic
from a multi-agent LangGraph support agent: real LLM calls, real injected tool failures, and no
hand-written fixtures. A person answered every question the skills asked. Those runs:

- **triage-failures:** found one cross-cutting failure that clustering had split across four
  per-tool discovered failure modes (answers contradicting tool results), confirmed with the reviewer.
- **build-regression-set:** froze it: 14 failures and 10 passing controls.
- **write-judge:** twice refused to ship a judge that disagreed with the reviewer.
- **write-code-judge:** run against a local Neens with the development sandbox runner, on traces
  sent through the OpenTelemetry endpoint: tested the code on a known pass, a known fail and an
  out-of-scope trace, created and ran the judge, surfaced a miss against a gold label, versioned it
  and retired the old deployment. It also reported code execution being off, as the skill says.
- **fix-failure:** fixed the agent in the repo.
- **gate-release:** measured the fix: 5/24 → 19/24 on the targeted judge with zero regressions,
  reported as NO-GO against a 90% gate, and left the call to the human.
- **choose-model:** compared two models with pass^k and declined to call a winner inside the noise.
- **instrument-agent:** instrumented a new agent and read its first trace back.
- **reliability-review:** refused to blame a KPI miss on a failure mode whose traces didn't
  support its label.

## Keeping the skills honest

The skills name real Neens tools and arguments. `scripts/check_skills.py` checks every tool name
and every JSON argument in every skill against the Neens tool surface, plus each skill's
frontmatter:

```bash
python3 scripts/check_skills.py                                  # against the committed snapshot
NEENS_TOKEN=... python3 scripts/check_skills.py \
  --url https://your-neens --write-snapshot                      # against a live Neens (see the script's docstring for auth)
```

Run it whenever Neens ships a new MCP version. It needs only the Python standard library.

## Writing your own

These skills cover the loop every agent team runs. Your agent has its own failure modes, tools
and release process, so write skills for those too, following the same eight rules.
