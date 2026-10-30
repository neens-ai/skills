# Framework notes

Per-framework detail behind the Step 2 table. Every Python entry also needs a tracer provider
with an OTLP exporter (Step 3 of SKILL.md). Each one says how to stamp the conversation id, because
that is the attribute most often missing. Google ADK has its own page: `google-adk.md`.

The general rule for the conversation id: Neens takes the first of `gen_ai.conversation.id`,
`session.id`, `conversation.id`, `thread.id` found on any span of the trace. When the framework has
no hook for it, use the wrapper span in SKILL.md Step 4.

## LangGraph / LangChain

```bash
pip install openinference-instrumentation-langchain opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.langchain import LangChainInstrumentor
LangChainInstrumentor().instrument()   # before the graph is built or invoked
```

LangGraph runs on LangChain, so this one instrumentor covers it. Every node and the graph become
`chain` spans whose payload is graph state. Neens reads a chain span as a turn only when the state
names its content: the question under `message`, `query`, `question` or `prompt`, and the reply
under `answer`, `final_answer` or `final_output` (`response`, `output` and `result` also work).
A last node that returns a bare string or an unknown key gives a trace with the question and no
reply. Rename the key; do not add a second exporter to work around it.

## OpenAI Agents SDK

```bash
pip install openinference-instrumentation-openai-agents opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor
OpenAIAgentsInstrumentor().instrument()   # before the agent runs
```

The instrumentor re-emits the SDK's own tracing as OpenTelemetry spans. If the project already
bridges the SDK through Pydantic Logfire (`logfire.instrument_openai_agents()`), point Logfire's
OTLP export at Neens instead of adding this instrumentor. Never both.

## CrewAI

```bash
pip install openinference-instrumentation-crewai openinference-instrumentation-litellm opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.crewai import CrewAIInstrumentor
from openinference.instrumentation.litellm import LiteLLMInstrumentor
CrewAIInstrumentor().instrument(tracer_provider=provider)
LiteLLMInstrumentor().instrument(tracer_provider=provider)
```

The CrewAI instrumentor records crews, agents and tasks but **no LLM calls**. Pair it with the
instrumentor for whatever the model string routes to: LiteLLM for most models, or
`openinference-instrumentation-openai` / `-anthropic` when the model goes to a native SDK.
CrewAI's built-in "telemetry" is anonymous usage stats, unrelated to trace export.

## Claude Agent SDK / Anthropic SDK

```bash
pip install openinference-instrumentation-anthropic opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.anthropic import AnthropicInstrumentor
AnthropicInstrumentor().instrument()
```

This traces each Claude call. Two alternatives, both read by Neens:

1. `openinference-instrumentation-claude-agent-sdk` with `ClaudeAgentSDKInstrumentor().instrument()`
   gives agent-shaped traces (`query()` / `ClaudeSDKClient` as agent spans, tools as children).
   Install it **instead of** the Anthropic one.
2. The SDK's native export (it runs the Claude Code CLI): `CLAUDE_CODE_ENABLE_TELEMETRY=1`,
   `OTEL_TRACES_EXPORTER=otlp`, `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`,
   `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, plus the endpoint and headers. Trace export there is
   beta and its schema may change, so prefer an instrumentor.

## Pydantic AI

```bash
pip install pydantic-ai opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from pydantic_ai import Agent
Agent.instrument_all()   # after trace.set_tracer_provider(provider)
```

Instrumentation is built in and emits OTel GenAI spans. The Neens quickstart also shows
`Agent("openai:gpt-4o", instrument=True)`. Pydantic AI 2.x rejects that keyword
(`TypeError: unexpected keyword argument 'instrument'`), so use `Agent.instrument_all()` unless the
project pins an older release that accepts it. Logfire users can instead call `logfire.configure()`
with the Neens endpoint and then `logfire.instrument_pydantic_ai()`.

## LlamaIndex

```bash
pip install openinference-instrumentation-llama-index opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
LlamaIndexInstrumentor().instrument(tracer_provider=provider)   # before agents, indexes, query engines
```

Covers agents, workflows, retrievers, LLM calls and tools. LlamaIndex 0.12.3 and later needs
instrumentor 4.0 or later.

## Agno

```bash
pip install openinference-instrumentation-agno opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.agno import AgnoInstrumentor
AgnoInstrumentor().instrument(tracer_provider=provider)
```

Records agent and team runs, model calls and tools, including which team member handled what.

## smolagents

```bash
pip install openinference-instrumentation-smolagents opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.smolagents import SmolagentsInstrumentor
SmolagentsInstrumentor().instrument(tracer_provider=provider)   # before the agents are created
```

Records each run and step, including the code a `CodeAgent` wrote. Managed agents nest under the
agent that called them.

## Strands Agents

```bash
pip install 'strands-agents[otel]' openinference-instrumentation-strands-agents
```

```python
from openinference.instrumentation.strands_agents import StrandsAgentsToOpenInferenceProcessor
from strands.telemetry import StrandsTelemetry

telemetry = StrandsTelemetry()
telemetry.setup_otlp_exporter()   # reads OTEL_EXPORTER_OTLP_*; or pass endpoint=..., headers=...
telemetry.tracer_provider.add_span_processor(StrandsAgentsToOpenInferenceProcessor())
```

Strands owns the tracer provider here, so skip the generic provider block from Step 3. The
OpenInference processor is optional: without it Strands emits OTel GenAI `gen_ai.*` spans, which
Neens also reads. Set the conversation id on the agent:

```python
agent = Agent(tools=[...], trace_attributes={"session.id": conversation_id})
```

## AWS Bedrock AgentCore

AgentCore Runtime hosts an agent written with any framework. Keep that framework's
instrumentation, then:

1. Set up telemetry at module load in the entrypoint (for Strands, the block above).
2. Stamp the runtime session on each invocation, so every turn of one AgentCore session is one
   Neens conversation: `Agent(trace_attributes={"session.id": context.session_id})` inside the
   `@app.entrypoint` handler. Callers reuse the same `runtimeSessionId` across turns.
3. Turn off AgentCore's own ADOT tracer: `"instrumentation": { "enableOtel": false }` in
   `agentcore.json`, or `agentcore configure --entrypoint main.py --disable-otel`.
4. Set on the runtime: `DISABLE_ADOT_OBSERVABILITY=true`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
   `OTEL_EXPORTER_OTLP_HEADERS` and `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`. Neens accepts
   OTLP over HTTP only, not gRPC.

`agentcore.json` is usually committed, so inject the header from the deploy pipeline's secret
store, never the file. With ADOT off, traces go to Neens instead of CloudWatch; AgentCore's service
metrics still go to CloudWatch. "Traces in CloudWatch but not Neens" means step 3 or 4 is missing.

**Classic Amazon Bedrock Agents** (configured in the console, called with `invoke_agent`):

```bash
pip install openinference-instrumentation-bedrock opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.bedrock import BedrockInstrumentor
BedrockInstrumentor().instrument(tracer_provider=provider)   # BEFORE the boto3 client is created
```

Call `invoke_agent` with `enableTrace=True` and the same `sessionId` across turns, and read the
whole `completion` stream: the orchestration steps arrive on it, and unread steps are not traced.

## Vercel AI SDK (TypeScript)

Check the installed major version first (`npm ls ai`). The setup and what Neens can show differ.

**AI SDK 7.** Spans come from the separate `@ai-sdk/otel` integration. Without it the SDK records
no spans at all. Register it once at startup; no per-call flag is needed (`experimental_telemetry`
is deprecated in 7):

```bash
npm install ai @ai-sdk/otel @opentelemetry/sdk-node @opentelemetry/exporter-trace-otlp-http
# Next.js: npm install @vercel/otel @opentelemetry/api  (keep @ai-sdk/otel)
```

```typescript
// instrumentation.ts, loaded with: node --import ./instrumentation.js app.js
import { NodeSDK } from '@opentelemetry/sdk-node'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { registerTelemetry } from 'ai'
import { OpenTelemetry } from '@ai-sdk/otel'

const sdk = new NodeSDK({ traceExporter: new OTLPTraceExporter() })  // reads OTEL_EXPORTER_OTLP_*
sdk.start()
registerTelemetry(new OpenTelemetry())
process.on('SIGTERM', () => { sdk.shutdown().finally(() => process.exit(0)) })
```

In Next.js, call `registerOTel({ serviceName })` from `@vercel/otel` and then
`registerTelemetry(new OpenTelemetry())` inside `register()` in `instrumentation.ts`. AI SDK 7
emits `gen_ai.*` attributes, so Neens shows the model, tokens, the question and answer, and tool
calls with arguments and results.

**AI SDK 6.** Spans are built in and turned on per call:

```bash
npm install @opentelemetry/sdk-node @opentelemetry/exporter-trace-otlp-http
```

```typescript
await generateText({ model, prompt, experimental_telemetry: { isEnabled: true, functionId: 'summarize-ticket' } })
```

AI SDK 6 puts the prompt and response only on its own `ai.*` attributes (`ai.prompt`,
`ai.response.text`, `ai.toolCall.*`), which Neens does not read. Neens shows the model and tokens
only, so add the wrapper span from SKILL.md Step 4 with the question and answer on it.

**Both versions.** The SDK has no conversation-id hook Neens reads, so set `session.id` on a
wrapper span around the turn:

```typescript
import { trace } from '@opentelemetry/api'
const tracer = trace.getTracer('agent')

await tracer.startActiveSpan('agent.turn', { attributes: {
  'session.id': conversationId,
  'neens.version_label': process.env.GIT_SHA ?? 'dev',
  'gen_ai.operation.name': 'invoke_agent',
  'input.value': message,           // needed on AI SDK 6
} }, async (span) => {
  try {
    const { text } = await generateText({ model, prompt: message })  // AI SDK 6: add experimental_telemetry
    span.setAttribute('output.value', text)
    return text
  } finally {
    span.end()
  }
})
```

On AI SDK 7, check the turn count and token totals in Step 5: one question can show up as two
turns, and tokens can be counted twice. That is a known Neens ingest issue, not your setup.

## Plain OpenAI client

```bash
pip install openinference-instrumentation-openai opentelemetry-sdk opentelemetry-exporter-otlp
```

```python
from openinference.instrumentation.openai import OpenAIInstrumentor
OpenAIInstrumentor().instrument()
```

Model calls only. If the agent calls tools in its own loop, wrap each tool call in a span with
`gen_ai.operation.name` set to `execute_tool` and `gen_ai.tool.name` set, or the tool steps are
missing from the trace.
