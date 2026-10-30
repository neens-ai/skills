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

Install the package, then make the instrument call once at startup, before the agent is built.

| Framework | Install | Instrument once at startup |
|---|---|---|
| LangGraph / LangChain | `openinference-instrumentation-langchain` | `LangChainInstrumentor().instrument()` |
| OpenAI Agents SDK | `openinference-instrumentation-openai-agents` | `OpenAIAgentsInstrumentor().instrument()` |
| CrewAI | `openinference-instrumentation-crewai` plus `openinference-instrumentation-litellm` | `CrewAIInstrumentor()` and `LiteLLMInstrumentor()`, each `.instrument(tracer_provider=provider)` |
| Google ADK | built in: `opentelemetry-exporter-otlp-proto-http`, or `openinference-instrumentation-google-adk` | env vars only, or `GoogleADKInstrumentor().instrument(tracer_provider=provider)`. Read `references/google-adk.md` first. |
| Claude Agent SDK / Anthropic SDK | `openinference-instrumentation-anthropic` | `AnthropicInstrumentor().instrument()` |
| Pydantic AI | nothing extra, it is built in | `Agent.instrument_all()` (or `Agent(..., instrument=True)` on releases that accept it) |
| LlamaIndex | `openinference-instrumentation-llama-index` | `LlamaIndexInstrumentor().instrument(tracer_provider=provider)` |
| Agno | `openinference-instrumentation-agno` | `AgnoInstrumentor().instrument(tracer_provider=provider)` |
| smolagents | `openinference-instrumentation-smolagents` | `SmolagentsInstrumentor().instrument(tracer_provider=provider)` |
| Strands Agents | `'strands-agents[otel]'` and `openinference-instrumentation-strands-agents` | `StrandsTelemetry().setup_otlp_exporter()`, then add `StrandsAgentsToOpenInferenceProcessor()` to its tracer provider |
| AWS Bedrock AgentCore | the hosted framework's packages, plus `bedrock-agentcore` | the framework's own call, and turn off AgentCore's ADOT tracer (`DISABLE_ADOT_OBSERVABILITY=true`) |
| Amazon Bedrock Agents | `openinference-instrumentation-bedrock` | `BedrockInstrumentor().instrument(tracer_provider=provider)`, before the boto3 client |
| Vercel AI SDK (TypeScript) | AI SDK 7: `@ai-sdk/otel`, `@opentelemetry/sdk-node`, `@opentelemetry/exporter-trace-otlp-http`. AI SDK 6: the two `@opentelemetry/*` packages | AI SDK 7: `registerTelemetry(new OpenTelemetry())` once at startup. AI SDK 6: `experimental_telemetry: { isEnabled: true }` on each call |
| Plain OpenAI client | `openinference-instrumentation-openai` | `OpenAIInstrumentor().instrument()` |

Python packages also need `opentelemetry-sdk opentelemetry-exporter-otlp` (ADK and Strands name
their own exporter above). Read `references/frameworks.md` for the framework you picked: it has
the import lines, how to set the conversation id, and the trap for that framework. The known traps:

- **Google ADK**: on ADK 2.13 and later the built-in spans carry no messages unless
  `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY` is set, and `adk web` ignores
  `OTEL_*` variables in the agent's `.env`. Both are in `references/google-adk.md`.
- **Strands and AgentCore** own the tracer provider. Skip the generic provider block below.
- **Vercel AI SDK**: AI SDK 7 needs `@ai-sdk/otel` registered or it records no spans. AI SDK 6
  puts the prompt and response only on `ai.*` attributes, which Neens does not read, so add them on
  the turn span (Step 4).
- **CrewAI** records no LLM calls without the LiteLLM (or provider) instrumentor.
- **LangGraph**: the final reply must sit under a recognized key in the graph state (Step 4).

Full guides live at `https://app.neens.ai/docs/guides/quickstarts/`. Read the matching page when
the framework is not listed here.

## Step 3: Wire the exporter

Configuration comes from the environment. Never write a key into source code or commit one.

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="https://app.neens.ai"   # or the self-hosted Neens URL
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${NEENS_API_KEY}"
export OTEL_SERVICE_NAME="checkout-agent"                  # becomes the agent name in Neens
export OTEL_RESOURCE_ATTRIBUTES="neens.version_label=$(git rev-parse --short HEAD)"
```

`NEENS_API_KEY` is an ingest key (`nk_live_…`) from **Settings → API keys** in Neens. It is not
the MCP sign-in. Ask the user to create one and put it in their secrets manager or local `.env`.
Check that `.env` is in `.gitignore` before anyone writes a key into it.

The base URL above gets `/v1/traces` appended by the exporter. `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
and an explicit `endpoint=` are used as given, so they need the full `https://…/v1/traces`. Neens
takes OTLP over HTTP (protobuf or JSON), not gRPC: set `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
wherever an exporter defaults to gRPC.

Python startup code, before the agent is constructed:

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

provider = TracerProvider(resource=Resource.create())  # reads OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # reads OTEL_EXPORTER_OTLP_*
trace.set_tracer_provider(provider)
# then the framework instrumentor from Step 2
```

Short-lived processes such as scripts, CLIs and serverless handlers must call
`provider.force_flush()` before exit, or the last batch is lost.

## Step 4: Make sure the trace carries what Neens needs

Neens can ingest a trace without these, but the fix loop cannot work well without them. It reads
standard OTel GenAI and OpenInference attributes, per field, first match wins, and only from span
and resource attributes. It does not read span events or OTel log records, so content a framework
sends only as events never arrives.

| What | Where Neens reads it |
|---|---|
| Conversation id | The first of `gen_ai.conversation.id`, `session.id`, `conversation.id`, `thread.id` on any span. Groups the turns of one conversation. Reuse one id per conversation. |
| Version | `neens.version_label` on a span or the resource, else the resource `service.version`. Before/after comparisons depend on it. |
| Question and answer | Messages on LLM, agent or chain spans: OpenInference `llm.input_messages.*` / `llm.output_messages.*`, then `gen_ai.input.messages` / `gen_ai.output.messages` (plus `gen_ai.system_instructions`), then ADK's `gcp.vertex.agent.*`, then the deprecated `gen_ai.prompt` / `gen_ai.completion`, then `input.value` / `output.value`. The trace input is the latest user message, the output the last assistant text. LangGraph: put the reply under `answer`, `final_answer` or `final_output` in the graph state. |
| Model, tokens | `gen_ai.response.model` or `gen_ai.request.model` or `llm.model_name`; `gen_ai.usage.*` or `llm.token_count.*` |
| Tool calls | Spans with `gen_ai.operation.name` set to a tool operation, or `gen_ai.tool.name`, or OpenInference kind `TOOL`. Arguments and result from `input.value` / `output.value` or `gen_ai.tool.call.arguments` / `gen_ai.tool.call.result`. |
| Agent name | The resource `service.name` (`OTEL_SERVICE_NAME`) |

Most instrumentors set all of this except the version, and some miss the conversation id. When the
framework gives you no hook (see `references/frameworks.md`), wrap one agent turn in a span:

```python
import os
from opentelemetry import trace

tracer = trace.get_tracer("agent")

def handle_turn(conversation_id: str, message: str):
    with tracer.start_as_current_span("agent.turn", attributes={
        "session.id": conversation_id,
        "neens.version_label": os.environ.get("GIT_SHA", "dev"),
    }) as span:
        answer = run_agent(message)  # the existing agent call; its spans nest under this one
        # Only if Step 5 shows no question or answer: put them on this span as an agent span.
        # span.set_attribute("gen_ai.operation.name", "invoke_agent")
        # span.set_attribute("input.value", message)
        # span.set_attribute("output.value", answer)
        return answer
```

A span with no kind is ignored when Neens builds the question and answer, which is why the
fallback sets `gen_ai.operation.name` as well as the two values.

## Step 5: Prove it

1. Run the agent once on a realistic input that calls a tool. Use the user's normal run command,
   or a one-shot form such as `adk run my_agent "<question>"`, so the process exits and flushes.
2. Call `list_traces` with `{"started_after": "<ISO time from just before the run>", "limit": 5}`.
   Ingest is asynchronous, so if nothing is there yet wait about ten seconds and try again, up to
   three times.
3. Call `get_trace` on the newest trace and check each item:
   - the agent name is the one you set
   - the model is present on the LLM spans
   - tool calls appear with their arguments and result, if the agent called tools
   - the user input and the final output are both present, as plain text
   - the conversation id is present, and a second turn of the same conversation lands in the same
     session
   - the version label is present
   - each span appears once (two exporters send everything twice)
4. Report the trace id and a pass/fail line for each item. Fix every failing item before you finish.

A trace read while its turn is still running can be partial: spans export as they end, so the outer
agent span and the final answer arrive last. If the answer or the root span is missing, wait for the
run to finish and read the trace again before you call it a failure.

If nothing arrives after three tries, work through these in order: the endpoint (base URL versus
full path, Step 3), a 401 (wrong, revoked or missing key), gRPC instead of HTTP, the process exiting
before a flush, and the instrumentor running after the agent was built. If input and output are
empty but spans arrive, the framework is not putting content on its spans: see the trap for that
framework in Step 2.

## Anti-patterns

- **A key in source, in a committed `.env`, or pasted into chat.** Read it from the environment.
- **Declaring success because the exporter did not raise.** Exporters fail silently. Only a trace
  read back through `get_trace` counts.
- **No version label.** Without it, "did the fix work?" becomes a guess about which build
  produced which trace.
- **Instrumenting only the LLM client of a tool-using agent.** You get model calls without the
  tool calls between them, and most agent failures happen in the tool calls.
- **Two exporters in one process.** A framework that already exports (ADK under `adk web`, Strands,
  AgentCore) plus a provider you added sends every span twice. Keep one.
