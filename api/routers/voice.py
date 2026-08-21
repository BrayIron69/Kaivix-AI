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
scheme and the SAME APIKeyStore already protecting
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
existing X-API-Key-against-APIKeyStore logic; only the header read would
change.

NOT DONE HERE, on purpose (see item 5): no real Vapi account, phone
number, or assistant is configured against this endpoint. This is the
backend contract existing and working correctly against a simulated
request -- wiring a real assistant to a real business_id's real URL and
real key is a founder-account step, not a code step.

STREAMING: not implemented. Vapi's request sets `stream: true`, and this
route always returns a single non-streaming JSON chat.completion, which
Vapi's own docs state explicitly it is "equipped to handle" alongside
SSE -- so this is documented as correct, not merely tolerated. The real
cost is latency: ConversationEngine.process_message is one synchronous
call that returns a complete string, there is no intermediate token
stream to forward, and building one would mean re-architecting how
process_message produces output -- exactly the "new logic" this build was
told not to add. On a live phone call (unlike a text chat widow) time-to-
first-word is what a caller actually perceives while waiting in silence,
so this is a real, known limitation of this foundation, not a hidden one.
"""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from api.routers import chat as chat_router
from core_ai.business_config import BusinessConfigError
from schemas.voice import (
    VapiChatCompletionChoice,
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


@router.post(
    "/{business_id}/chat/completions",
    response_model=VapiChatCompletionResponse,
    dependencies=[Depends(chat_router.require_business_api_key)],
)
def voice_chat_completions(
    business_id: str, request: VapiChatCompletionRequest
) -> VapiChatCompletionResponse:
    """
    Vapi's custom-LLM webhook target for one business.

    Translates Vapi's OpenAI-shaped request into ConversationEngine's
    existing contract, calls it, and translates the plain string response
    back into an OpenAI-shaped chat.completion -- no qualification,
    booking, or gate logic lives here; see this module's docstring.
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
        )
    except BusinessConfigError as error:
        # Same mapping api/routers/chat.py's _handle uses: an unknown or
        # misconfigured business_id is a client error (a mistyped
        # business_id in the Vapi assistant's server URL), not a 500.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown or misconfigured business_id: {business_id!r}",
        ) from error

    return VapiChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=request.model or "kaivix-voice",
        choices=[
            VapiChatCompletionChoice(
                message=VapiResponseMessage(content=response_text)
            )
        ],
    )
