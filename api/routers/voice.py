"""
Vapi custom-LLM webhook: voice as a new way in and out of the exact same
ConversationEngine the chat widget already uses.

Vapi handles the phone call itself -- speech-to-text, text-to-speech, call
routing -- and calls a real HTTP endpoint on our backend with the
conversation transcript so far, expecting a chat-completion-shaped
response back. Confirmed against Vapi's own documentation and reference
server implementations (see schemas/voice.py's module docstring for the
exact sources): this is an OpenAI-compatible POST /chat/completions
contract, not a bespoke Vapi format.

REUSE, NOT DUPLICATION. This route builds no new qualification, booking,
anti-fabrication, or CRM-sync logic. Every one of those already lives in
ConversationEngine (via ChatService, via services/chat_service.py) and
runs unchanged for a voice conversation: the deterministic
UnbackedActionDetector gate, the pricing guard, the em-dash filter, real
calendar booking, real lead sync. This route's only job is translating
between Vapi's wire format and ConversationEngine.process_message's
existing (conversation_id, user_message) -> response_text contract --
literally `chat_router.chat_service.chat(...)`, the same call
api/routers/chat.py's /chat/{business_id} makes, imported and reused
rather than re-implemented.

business_id scoping mirrors /chat/{business_id} exactly: one Vapi
assistant per business, one URL per business
(POST /voice/{business_id}/chat/completions), same
ChatService.get_engine(business_id) cache so a business's chat and voice
traffic share the exact same cached ConversationEngine instance rather
than each channel paying for and holding a separate one.

Authentication reuses require_business_api_key -- the SAME X-API-Key
scheme and the SAME key source (auth/business_api_keys.py, resolved from
the BUSINESS_API_KEYS environment variable) already protecting
POST /chat/{business_id} -- rather than inventing a second credential
system for a second channel. This is a real, unauthenticated-by-default
gap otherwise: unlike the chat widget (deliberately open, because it has
no way to hold a secret), this endpoint has no legitimate reason to be
open -- Vapi is a server-to-server caller that can hold a credential, and
an open version of this endpoint could sync fabricated leads, trigger
real emails, and book real calendar events for anyone who found the URL.
Vapi's dashboard lets you set custom headers on a custom-LLM model's
server URL, so this is expected to be wireable directly -- but the exact
mechanics have not been verified against a real Vapi account, which item
5 of this build (deliberately) defers. If Vapi's header configuration
turns out not to support an arbitrary header name, swap this dependency
for one reading the `Authorization` header instead (Vapi's own default
convention for authenticating TO a custom LLM, per Vapi's docs) --
whichever it is, the actual verification stays require_business_api_key's
existing logic (business_api_keys.verify_key, scoped by business_id and
constant-time); only the header read would change.

NOT DONE HERE, on purpose (see item 5): no real Vapi account, phone
number, or assistant is configured against this endpoint. This is the
backend contract existing and working correctly against a simulated
request -- wiring a real assistant to a real business_id's real URL and
real key is a founder-account step, not a code step.

STREAMING: implemented, after a real call proved the non-streaming
shortcut silently broken. Vapi's request sets `stream: true`; this route
used to always return a single flat JSON chat.completion regardless,
reasoning that Vapi's own docs describe it as "equipped to handle both
response types." A real live call showed that claim does not hold in
practice: Vapi's own call-logs event export for that call showed every
`assistant.model.requestAttemptSucceeded` event parsing `content: ""`
and `completionTokens: 0` from our 200 OK JSON responses, and
`assistant.voice.cleanup` showing `charactersUsed: 0` for the whole
call -- the caller heard nothing after the first line, every turn.

This still does not stream real LLM tokens --
ConversationEngine.process_message is one synchronous call that returns
a complete string, and building true token-level streaming would mean
re-architecting how process_message produces output, which is out of
scope here (see this module's reuse-not-duplication stance above). What
changed is the *framing*: the already-complete response text is now
replayed through a sequence of `chat.completion.chunk` SSE frames
(_sse_chunks below) instead of one flat JSON body, when the request asks
for it. This is the same shape Vapi's client actually parses -- proven
by the real call above -- even though no token arrives before the whole
answer is ready. Time-to-first-word is therefore unchanged from before;
what's fixed is that any word arrives at all. A non-streaming request
(`stream` falsy or absent) still gets the plain JSON body unchanged.
"""

import re
import time
import uuid
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from api.routers import chat as chat_router
from core_ai.business_config import BusinessConfigError
from schemas.voice import (
    VapiChatCompletionChoice,
    VapiChatCompletionChunk,
    VapiChatCompletionChunkChoice,
    VapiChatCompletionChunkDelta,
    VapiChatCompletionRequest,
    VapiChatCompletionResponse,
    VapiMessage,
    VapiResponseMessage,
)

router = APIRouter(
    prefix="/voice",
    tags=["Voice"],
)


def _latest_user_message(messages: list[VapiMessage]) -> str:
    """
    The visitor's newest utterance -- the one thing ConversationEngine
    needs, out of the full transcript Vapi resends on every request.

    ConversationEngine is stateful per conversation_id (it owns its own
    history via ConversationMemory, see conversation_engine.py); Vapi's
    contract is stateless per request (the full transcript comes back
    every time, same as any OpenAI-compatible chat endpoint). Taking only
    the last `role == "user"` message is what reconciles the two: it is
    exactly the one new thing this turn, matching /chat's
    ChatRequest.message contract rather than replaying Vapi's whole
    transcript into the engine a second time (which would double up
    everything already in ConversationMemory).

    In practice this is always found: Vapi calls this endpoint only after
    speech-to-text has produced a user utterance -- an assistant's
    configured opening line is spoken directly by Vapi's TTS without
    reaching this endpoint at all. Raises rather than guesses if the
    contract is ever violated, the same "fail loud, don't fabricate"
    stance _reject_oversized_message and calendar_oauth.py's missing-state
    check already take.
    """
    for message in reversed(messages):
        if message.role == "user":
            return message.content

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No user message found in the Vapi request's messages array.",
    )


def _sse_chunks(response_text: str, chat_id: str, model_name: str) -> Iterator[str]:
    """
    Replay an already-complete response as a sequence of
    `chat.completion.chunk` SSE frames, ending with the standard
    `finish_reason: "stop"` frame and a literal `data: [DONE]` line --
    the shape a real call proved Vapi's client actually needs to extract
    any content at all (see this module's docstring).

    Split on whitespace runs (`\\S+\\s*`) rather than emitted word-by-word
    for cosmetic effect: it is the simplest split that reassembles back
    to the exact original string (no lost or doubled spaces), and it
    gives Vapi's TTS layer more than one frame to start from without
    requiring real token-level output from the LLM. An empty
    response_text still yields one content-carrying frame (content="")
    before the finish frame, so a stream is never literally empty.
    """
    created = int(time.time())
    words = re.findall(r"\S+\s*", response_text) or [""]

    for index, word in enumerate(words):
        delta = VapiChatCompletionChunkDelta(
            role="assistant" if index == 0 else None,
            content=word,
        )
        chunk = VapiChatCompletionChunk(
            id=chat_id,
            created=created,
            model=model_name,
            choices=[VapiChatCompletionChunkChoice(delta=delta)],
        )
        yield f"data: {chunk.model_dump_json()}\n\n"

    final_chunk = VapiChatCompletionChunk(
        id=chat_id,
        created=created,
        model=model_name,
        choices=[
            VapiChatCompletionChunkChoice(
                delta=VapiChatCompletionChunkDelta(), finish_reason="stop"
            )
        ],
    )
    yield f"data: {final_chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"


@router.post(
    "/{business_id}/chat/completions",
    dependencies=[Depends(chat_router.require_business_api_key)],
)
def voice_chat_completions(business_id: str, request: VapiChatCompletionRequest):
    """
    Vapi's custom-LLM webhook target for one business.

    Translates Vapi's OpenAI-shaped request into ConversationEngine's
    existing contract, calls it, and translates the plain string response
    back into an OpenAI-shaped chat.completion -- no qualification,
    booking, or gate logic lives here; see this module's docstring.

    Returns SSE (`text/event-stream`, chat.completion.chunk frames) when
    the request sets `stream: true` -- which a real call proved is the
    only shape Vapi's client actually extracts content from -- and the
    plain non-streaming JSON body otherwise. Not response_model-typed on
    the route decorator because a single route now legitimately returns
    either a StreamingResponse or a VapiChatCompletionResponse.
    """
    if request.call is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Vapi request is missing 'call' -- call.id is required as "
                "the conversation id."
            ),
        )

    user_message = _latest_user_message(request.messages)
    # Reuses api/routers/chat.py's own oversized-message guard rather than
    # a second copy of the same 2000-character cap.
    chat_router._reject_oversized_message(user_message)

    try:
        response_text = chat_router.chat_service.chat(
            conversation_id=request.call.id,
            message=user_message,
            business_id=business_id,
            # Explicit, the same way business_id is -- never inferred.
            # This is what tells ConversationEngine a raw booking-link
            # URL must never appear in the response (a phone caller
            # cannot click a link); see conversation_engine.py's
            # _guard_against_spoken_url and _voice_booking_alternative.
            channel="voice",
        )
    except BusinessConfigError as error:
        # Same mapping api/routers/chat.py's _handle uses: an unknown or
        # misconfigured business_id is a client error (a mistyped
        # business_id in the Vapi assistant's server URL), not a 500.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown or misconfigured business_id: {business_id!r}",
        ) from error

    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
    model_name = request.model or "kaivix-voice"

    if request.stream:
        return StreamingResponse(
            _sse_chunks(response_text, chat_id, model_name),
            media_type="text/event-stream",
        )

    return VapiChatCompletionResponse(
        id=chat_id,
        created=int(time.time()),
        model=model_name,
        choices=[
            VapiChatCompletionChoice(
                message=VapiResponseMessage(content=response_text)
            )
        ],
    )
