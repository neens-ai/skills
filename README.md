# Neens Skills

Skills that teach a coding agent (Claude Code, Codex, Cursor and any agent that reads `SKILL.md`) to run the
[Neens](https://neens.ai) failure-to-fix loop on your own agent: find what is failing, prove a
fix, and make sure it cannot come back.

Neens exposes the loop as an MCP server of 60 tools. The tools are the raw capability.
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
| [neens-start](skills/neens-start/SKILL.md) | You're not sure where to begin. Checks the connection, reads the loop, routes you. |
| [instrument-agent](skills/instrument-agent/SKILL.md) | No traces yet. Wires OpenTelemetry to Neens and proves a trace arrived intact. |
| [triage-failures](skills/triage-failures/SKILL.md) | "What's failing?" Reads the evidence, locates each failure, records your verdicts. |
| [build-regression-set](skills/build-regression-set/SKILL.md) | A failure is confirmed. Freezes its traces, plus passing controls, into a golden set. |
| [write-judge](skills/write-judge/SKILL.md) | A failure needs an automated check. Writes a pass/fail judge and measures it against you. |
| [fix-failure](skills/fix-failure/SKILL.md) | Time to fix. Implements the remediation in your repo, proves it, and reports PR and proof back. |
| [gate-release](skills/gate-release/SKILL.md) | "Can we ship this?" Replays every regression set against the candidate and returns GO, NO-GO or NO DATA. |
| [choose-model](skills/choose-model/SKILL.md) | "Which model?" Runs a pass^k model sweep and reads it honestly. |
| [reliability-review](skills/reliability-review/SKILL.md) | "How are we doing?" A one-page, evidence-backed status report. |

The usual path for a new agent:

```
instrument-agent → triage-failures → build-regression-set → write-judge → fix-failure → gate-release
```

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
Fix the top open Neens remediation and prove it against my preview deploy.
Can we ship branch fix/refund-policy?
```

## Requirements

- A Neens project with an MCP connection. Traces are needed for everything except
  `instrument-agent`.
- An LLM connection in Neens (**Settings → LLM providers**) for judges and remediations.
- `fix-failure`, `gate-release` and `choose-model` need your agent reachable over HTTP from Neens
  (a preview deploy, for example), or a harness that replays golden inputs. Each skill explains
  both options.

## How they were tested

Every skill was run end to end by Claude Code against a real Neens instance. The data was traffic
from a multi-agent LangGraph support agent: real LLM calls, real injected tool failures, and no
hand-written fixtures. A person answered every question the skills asked. Those runs:

- **triage-failures:** found one cross-cutting failure that clustering had split across four
  per-tool clusters (answers contradicting tool results), confirmed with the reviewer.
- **build-regression-set:** froze it: 14 failures and 10 passing controls.
- **write-judge:** twice refused to ship a judge that disagreed with the reviewer.
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
