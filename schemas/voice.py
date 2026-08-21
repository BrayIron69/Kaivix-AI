"""
Request/response shapes for Vapi's custom-LLM webhook.

Vapi's custom-LLM integration is NOT a bespoke webhook format -- Vapi
requires an OpenAI-compatible POST /chat/completions endpoint and sends a
request following OpenAI's chat completions request format, expecting a
response in OpenAI's chat completion format back. Confirmed directly from
Vapi's own docs and reference server implementations, not guessed at:

  - https://docs.vapi.ai/customization/custom-llm/using-your-server
    ("you need to provide an OpenAI-compatible POST endpoint for
    /chat/completions... requests from Vapi which will follow OpenAI
    Request format and return responses in OpenAI compatible format")
  - https://github.com/VapiAI/example-server-javascript-deno
    (api/custom-llm/basic.ts, openai-sse.ts, openai-advanced.ts -- all
    three reference implementations destructure
    `{ model, messages, max_tokens, temperature, stream, call }` from the
    request body and return a real OpenAI chat.completion object)

Two things worth being explicit about, since they are easy to get wrong
by analogy with schemas/chat.py:

1. Vapi sends the FULL conversation transcript in `messages` on every
   request (stateless, like any OpenAI-compatible chat endpoint) --
   unlike ChatRequest, which carries only the one new message because
   ConversationEngine owns conversation history itself. The route layer
   (api/routers/voice.py) is what reconciles this: it pulls the latest
   user utterance out of `messages` and hands ONLY that to
   ConversationEngine.process_message, the same one-new-message contract
   /chat already uses. This module models Vapi's real wire format
   faithfully; it does not change what ConversationEngine expects.

2. `call` carries Vapi's call metadata (call id, assistant id, customer
   phone number, etc.) -- Vapi's own API reference documents its fields
   as including at least `id`, `assistantId`, `phoneNumberId`, `customer`,
   `status`. Only `id` is used here (as the ConversationEngine
   conversation_id, exactly analogous to ChatRequest.conversation_id) --
   modeled as `extra="allow"` rather than a fully enumerated schema, so an
   undocumented or added field from Vapi never breaks parsing.
"""

from pydantic import BaseModel, ConfigDict, Field


class VapiMessage(BaseModel):
    """One OpenAI-shaped chat message, exactly as Vapi sends/expects it."""

    role: str
    content: str

    # Vapi (like OpenAI) may include extra per-message fields (e.g. a
    # message id or timestamp) this integration has no use for -- ignored
    # rather than rejected, so an addition on Vapi's side never turns into
    # a hard failure here.
    model_config = ConfigDict(extra="ignore")


class VapiCall(BaseModel):
    """
    The subset of Vapi's `call` object this integration actually uses.

    `id` is the one field load-bearing here: it becomes the
    conversation_id ConversationEngine tracks history under, the same
    role ChatRequest.conversation_id plays for the chat widget. Every
    other field Vapi's call object carries (assistantId, phoneNumberId,
    customer, status, cost, ...) passes through unexamined via
    extra="allow" -- there is no reason to enumerate fields nothing here
    reads, and doing so would only create a second, unofficial schema for
    Vapi's call object to drift out of sync with.
    """

    id: str

    model_config = ConfigDict(extra="allow")


class VapiChatCompletionRequest(BaseModel):
    """
    The request body Vapi POSTs to a custom-LLM endpoint.

    `messages` is the only field this integration strictly needs (to find
    the visitor's latest utterance) alongside `call` (to find the
    conversation id). `model`/`max_tokens`/`temperature` are accepted and
    ignored -- ConversationEngine already owns model selection
    (config.py's MODEL) and generation parameters; a per-call override
    from Vapi's assistant config is not something this integration
    exposes a way to honor, since doing so would mean bypassing
    ConversationEngine's own prompt/generation pipeline, which is exactly
    the duplication this integration exists to avoid.
    """

    messages: list[VapiMessage]
    call: VapiCall | None = None
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool | None = None

    # Vapi's request is OpenAI-request-shaped, which carries many more
    # optional fields (tools, tool_choice, top_p, ...) this integration
    # has no use for. Ignored rather than rejected: a field Vapi adds or
    # an assistant config enables must never turn into a 422 here.
    model_config = ConfigDict(extra="ignore")


class VapiResponseMessage(BaseModel):
    """The `message` object inside a chat.completion choice."""

    role: str = "assistant"
    content: str


class VapiChatCompletionChoice(BaseModel):
    index: int = 0
    message: VapiResponseMessage
    finish_reason: str = "stop"


class VapiChatCompletionResponse(BaseModel):
    """
    A real, non-streaming OpenAI chat.completion object -- the shape
    Vapi's own docs point to
    (https://platform.openai.com/docs/api-reference/chat/create) as what
    a custom-LLM response must look like.

    Non-streaming, not SSE, even though Vapi's request sets
    `stream: true`. Vapi's own docs state explicitly that "Vapi is
    equipped to handle both response types" (JSON or SSE) -- so
    non-streaming is documented as acceptable, not merely tolerated as a
    fallback. This is a deliberate scope decision, not an oversight: see
    api/routers/voice.py's module docstring for what it costs.
    """

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[VapiChatCompletionChoice]
