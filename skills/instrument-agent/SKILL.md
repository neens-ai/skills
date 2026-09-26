---
name: instrument-agent
description: >
  Send an agent's traces to Neens with standard OpenTelemetry, then prove they arrived and carry
  what Neens needs (input, output, model, tool calls, conversation id, version). Use when a project
  has no traces, when the user asks to connect or instrument their agent, or when traces arrive
  but look empty. Do NOT use for analyzing traces that already flow; use `triage-failures`.
---

# Instrument Agent

Get real traces flowing from the user's agent into Neens, and do not call it done until one has
been read back and checked. Neens ingests standard OpenTelemetry. There is no Neens SDK to install.

## Step 1: Find the agent

Read the repo. Identify:

1. The language and the agent framework. Check dependency files (`pyproject.toml`,
   `requirements*.txt`, `package.json`) and imports.
2. The process entry point, where instrumentation must run before the agent is built.
3. Whether OpenTelemetry is already configured. If it is, add Neens as an exporter and keep the
   existing one. Never replace a tracing setup someone else depends on.

## Step 2: Pick the instrumentation

| Framework | Install | Instrument once at startup |
|---|---|---|
| LangGraph / LangChain | `openinference-instrumentation-langchain` | `LangChainInstrumentor().instrument()` |
| OpenAI Agents SDK | `openinference-instrumentation-openai-agents` | `OpenAIAgentsInstrumentor().instrument()` |
| CrewAI | `openinference-instrumentation-crewai` plus `openinference-instrumentation-litellm` | both instrumentors, with `tracer_provider=provider` |
| Claude Agent SDK / Anthropic SDK | `openinference-instrumentation-anthropic` | `AnthropicInstrumentor().instrument()` |
| Pydantic AI | nothing extra, it is built in | `Agent(..., instrument=True)` or `Agent.instrument_all()` |
| Vercel AI SDK (TypeScript) | `@opentelemetry/sdk-node` and an OTLP HTTP exporter | `experimental_telemetry: { isEnabled: true }` on each call |
| Plain OpenAI client | `openinference-instrumentation-openai` | `OpenAIInstrumentor().instrument()` |

Python packages also need `opentelemetry-sdk opentelemetry-exporter-otlp`. Full per-framework
guides live at `https://app.neens.ai/docs/guides/quickstarts/`. Read the matching page when the
framework is not in the table or the snippet below does not fit.

## Step 3: Wire the exporter

Configuration comes from the environment. Never write a key into source code or commit one.

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://app.neens.ai"   # or the self-hosted Neens URL
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${NEENS_API_KEY}"
export OTEL_SERVICE_NAME="checkout-agent"                  # becomes the agent name in Neens
```

`NEENS_API_KEY` is an ingest key (`nk_live_…`) from **Settings → API keys** in Neens. It is not
the MCP sign-in. Ask the user to create one and put it in their secrets manager or local `.env`.
Check that `.env` is in `.gitignore` before anyone writes a key into it.

Python startup code, before the agent is constructed:

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

provider = TracerProvider(resource=Resource.create())  # reads OTEL_SERVICE_NAME
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # reads OTEL_EXPORTER_OTLP_*
trace.set_tracer_provider(provider)
# then the framework instrumentor from Step 2
```

Short-lived processes such as scripts, CLIs and serverless handlers must call
`provider.force_flush()` before exit, or the last batch is lost.

## Step 4: Add the three attributes that make traces useful

Neens can ingest a trace without these, but the fix loop cannot work well without them. Neens reads
each one from any span in the trace, so the simplest place for them is a span that wraps one agent
turn.

| Attribute | Why |
|---|---|
| `session.id` (or `gen_ai.conversation.id`) | Groups the turns of one conversation into a session. |
| `neens.version_label` | The git SHA or release of the agent that produced the trace. Before/after comparisons depend on it. |
| The user's input and the final answer | Judges and regression sets read these. LangGraph: put the reply under `answer`, `final_answer` or `final_output` in the graph state, or Neens shows the question with no reply. |

```python
import os
from opentelemetry import trace

tracer = trace.get_tracer("agent")

def handle_turn(conversation_id: str, message: str):
    with tracer.start_as_current_span("agent.turn", attributes={
        "session.id": conversation_id,
        "neens.version_label": os.environ.get("GIT_SHA", "dev"),
    }):
        return run_agent(message)  # the existing agent call; its spans nest under this one
```

## Step 5: Prove it

1. Run the agent once on a realistic input. Use the user's normal run command.
2. Call `list_traces` with `{"started_after": "<ISO time from just before the run>", "limit": 5}`.
   Ingest is asynchronous, so if nothing is there yet wait about ten seconds and try again, up to
   three times.
3. Call `get_trace` on the newest trace and check each item:
   - the agent name is the one you set
   - the model is present
   - tool calls appear, if the agent called tools
   - the user input and the final output are both present
   - the version label is present
4. Report the trace id and a pass/fail line for each item. Fix every failing item before you finish.

If nothing arrives after three tries, work through these in order: the endpoint (the exporter
appends `/v1/traces` itself, so do not add it to `OTEL_EXPORTER_OTLP_ENDPOINT`), a 401 (wrong,
revoked or missing key), the process exiting before a flush, and the instrumentor running after
the agent was built.

## Anti-patterns

- **A key in source, in a committed `.env`, or pasted into chat.** Read it from the environment.
- **Declaring success because the exporter did not raise.** Exporters fail silently. Only a trace
  read back through `get_trace` counts.
- **No version label.** Without it, "did the fix work?" becomes a guess about which build
  produced which trace.
- **Instrumenting only the LLM client of a tool-using agent.** You get model calls without the
  tool calls between them, and most agent failures happen in the tool calls.
