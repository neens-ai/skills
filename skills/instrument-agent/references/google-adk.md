# Google ADK

Google's Agent Development Kit (`google-adk`, Python). Neens reads ADK traces with no Neens code.
There are two ways to get them, and you use exactly one per process.

| | Built-in tracing (Path A) | OpenInference instrumentor (Path B) |
|---|---|---|
| Install | `pip install google-adk opentelemetry-exporter-otlp-proto-http` | `pip install google-adk openinference-instrumentation-google-adk opentelemetry-sdk opentelemetry-exporter-otlp-proto-http` |
| Code | None under `adk web` / `adk api_server`. `adk run` and your own scripts register a tracer provider (below). | `GoogleADKInstrumentor().instrument(tracer_provider=provider)`, once, before the agents or runner are built |
| Vocabulary | OTel GenAI `gen_ai.*`, plus ADK's own `gcp.vertex.agent.*` on older ADK | OpenInference (`llm.*`, `input.value`, `session.id`) |
| Content by default | Depends on the ADK version. Read "Content capture" before you trust it. | Yes |

Pick Path A when the user does not want a new dependency. Pick Path B when their other agents
already use OpenInference, or when you cannot control the process environment.

**Never run two exporters.** Under `adk web`, ADK already exports when `OTEL_EXPORTER_OTLP_*` is set
in the shell. If the agent code also registers a provider or adds a span processor, every span
arrives twice. The guarded block below avoids that.

## Content capture (the part that usually goes wrong)

Neens builds the question, the answer and the tool arguments from attributes **on the span**. It
does not read span events or OTel log records. Check the version first: `pip show google-adk`.

- **ADK 2.x** (checked on 2.13.0): built-in spans are `invoke_workflow`, `invoke_agent`,
  `generate_content <model>` and `execute_tool <tool>`. With no extra settings they carry the
  model, the conversation id and the tool name, but **no messages and no tool arguments or
  results**. Neens then shows an empty question and answer. Set:

  ```bash
  export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY   # or SPAN_AND_EVENT
  ```

  ADK then writes `gen_ai.input.messages`, `gen_ai.output.messages` and
  `gen_ai.system_instructions` on the LLM spans, and `gen_ai.tool.call.arguments` /
  `gen_ai.tool.call.result` on the tool spans. Neens reads all of them. `EVENT_ONLY`, `true`, or
  leaving it unset keeps the content off the span. `OTEL_SEMCONV_STABILITY_OPT_IN` on its own adds
  no content.
- **Older ADK** (spans named `call_llm`): ADK writes the request and response to
  `gcp.vertex.agent.llm_request` / `gcp.vertex.agent.llm_response`, and tool input and output to
  `gcp.vertex.agent.tool_call_args` / `gcp.vertex.agent.tool_response`. That is on by default and
  controlled by `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS` (default `true`). With `false`, ADK writes
  placeholders (`{}`, `<not specified>`, `N/A`) that Neens treats as "not captured".
  `adk deploy agent_engine` sets it to `false` unless the agent's `.env` sets it first.

Setting `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY` and leaving
`ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS` unset is safe on both. The OpenInference instrumentor
captures content without either variable.

## Environment

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://app.neens.ai/v1/traces"   # full path
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer ${NEENS_API_KEY}"
export OTEL_SERVICE_NAME="weather-agent"                                      # agent name in Neens
export OTEL_RESOURCE_ATTRIBUTES="neens.version_label=$(git rev-parse --short HEAD)"
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY          # Path A on ADK 2.x
```

Use the traces-only variable with the full path. The base-URL variable
`OTEL_EXPORTER_OTLP_ENDPOINT` also makes `adk web` start metric and log exporters to the same host,
and Neens only ingests traces. `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` and an explicit
`OTLPSpanExporter(endpoint=...)` are used exactly as given, so they need `/v1/traces`. The base URL
must not have it.

## Where the variables must live

| Command | Tracer provider | Put the `OTEL_*` variables in |
|---|---|---|
| `adk web`, `adk api_server` | ADK registers one at server start, with an exporter only if an OTLP endpoint variable is set at that moment | **The shell** (or process manager). The agent's `.env` loads later, so ADK's tracing setup never sees it. Model keys such as `GOOGLE_API_KEY` can stay in `.env`. |
| `adk run` | None. Nothing exports unless the agent module registers a provider. | The shell or the agent's `.env` (loaded before the agent module is imported; shell wins) |

The usual failure: a setup that works under `adk run` stops exporting under `adk web` because the
variables moved into `my_agent/.env`.

## The guarded block (works for both commands)

Put this at the top of the agent module, `my_agent/agent.py`:

```python
import atexit

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# `adk web` / `adk api_server` have already registered a provider by now; `adk run` has not.
if isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
    _provider = TracerProvider()  # reads OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # reads OTEL_EXPORTER_OTLP_*
    trace.set_tracer_provider(_provider)
    atexit.register(_provider.force_flush)

# Path B only: instrument the global provider (ADK's under `adk web`, ours under `adk run`).
# from openinference.instrumentation.google_adk import GoogleADKInstrumentor
# GoogleADKInstrumentor().instrument()

from google.adk.agents import Agent

root_agent = Agent(
    name="weather_agent",
    model="gemini-3.8-flash",  # any current Gemini model
    instruction="Use the available tools to answer.",
    tools=[...],
)
```

If the user configures the exporter in code (custom headers, a proxy), unset the shell
`OTEL_EXPORTER_OTLP_*` variables. Never both.

## Model id

The Neens examples use `gemini-3.8-flash`. It replaced `gemini-2.5-flash`, which Google retired for
new API users. A retired id fails with `404 NOT_FOUND: This model … is no longer available to new
users`. If the user's agent hits that, swap in the model the error suggests or one listed in
Google AI Studio. Do not change a model that works: Neens records whatever model the agent uses.

## Conversation id and the final answer

- **Conversation id.** ADK's session id is stamped on the spans: `gen_ai.conversation.id` with
  built-in tracing, `session.id` with the instrumentor. Neens groups traces by it, so reuse the
  same `session_id` across the turns of one conversation (in your own `Runner` code, the value
  passed to `create_session` and `run_async`). No wrapper span is needed for this.
- **Input.** Each trace's input is the latest user message of that turn, even though ADK resends
  the whole history to the model on every call. Tool results never count as the question.
- **Output.** The trace's output is the last assistant text, the reply ADK marks with
  `event.is_final_response()`. A function-call-only step is not an answer. With the instrumentor,
  Neens lifts the plain text out of ADK's raw run request and final event; the raw JSON stays
  under **Raw**.
- **One invocation is one turn**, however many model round trips it took. Token counts are not
  doubled when a wrapper span re-reports its children's usage.

A runner script for your own code:

```python
runner = InMemoryRunner(agent=agent, app_name="weather_app")
await runner.session_service.create_session(app_name="weather_app", user_id="user-123", session_id="conv-42")
async for event in runner.run_async(user_id="user-123", session_id="conv-42", new_message=types.Content(
        role="user", parts=[types.Part(text="Weather in Paris?")])):
    if event.is_final_response():
        print(event.content.parts[0].text)
provider.shutdown()  # short-lived script: flush the last batch
```

## Running one turn to verify

```bash
adk run my_agent "What's the weather in Paris?"
```

The one-shot form answers one question, exits normally and flushes the last batch, so it is the
easiest run for Step 5. In interactive `adk run`, quit with `exit`; a killed process loses its last
batch.

**A trace can look partial while its turn is still running.** `BatchSpanProcessor` exports each
span when it ends, so a slow model call can leave a trace with one LLM span and a tool call but no
answer and no outer `invoke_agent` / `invocation` span yet. Those end last. Wait for the turn to
finish (or `adk run` to exit), then call `get_trace` again before you mark anything failed.

## Checks specific to ADK

On top of the Step 5 list:

- the tool call shows its arguments and result, for example `get_weather` with `{"city": "Paris"}`
- the trace input and output are plain text, not ADK JSON
- one question counts as one turn, and each span appears once
- spans that finished cleanly read as `ok` (ADK leaves span status unset on success)

| Symptom | Fix |
|---|---|
| Nothing from `adk web` | Variables are in `.env`, not the shell. Export them where the server starts. |
| Nothing from `adk run` | Add the guarded block. |
| Every span twice | Two exporters. Keep the guarded block, or drop the shell variables if you export in code. |
| Empty input and output, ADK 2.x | Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY`, or use Path B. |
| Empty input and output, tool args `{}`, older ADK | `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` somewhere. Set it to `true`. |
| `404 NOT_FOUND` from the model | Retired model id. See "Model id". |
| Traces from before a Neens upgrade look wrong (JSON input, doubled tokens, extra turns) | Older traces are not re-processed. Send a new one. |
