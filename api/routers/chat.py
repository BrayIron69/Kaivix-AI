from fastapi import APIRouter, HTTPException, status

from core_ai.business_config import BusinessConfigError, DEFAULT_BUSINESS_ID
from schemas.chat import MAX_MESSAGE_LENGTH, ChatRequest, ChatResponse
from services.chat_service import ChatService

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

chat_service = ChatService()


def _reject_oversized_message(message: str) -> None:
    """
    Cap the customer message length.

    There was no cap, so a single request could push an arbitrarily large
    body into the prompt and burn a large amount of Groq token budget in one
    call. Enforced here rather than as a pydantic max_length so the caller
    gets a 400 stating the limit, instead of a generic 422 validation blob.

    Shared by both chat routes so a new route cannot quietly skip it.
    """
    if len(message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Message is too long: {len(message)} characters. "
                f"The maximum is {MAX_MESSAGE_LENGTH}."
            ),
        )


def _handle(request: ChatRequest, business_id: str) -> ChatResponse:
    """
    The single implementation both routes delegate to, so the plain /chat
    endpoint and the per-business one cannot drift apart.
    """
    _reject_oversized_message(request.message)

    try:
        response = chat_service.chat(
            conversation_id=request.conversation_id,
            message=request.message,
            business_id=business_id,
        )
    except BusinessConfigError as error:
        # An unknown/misconfigured business_id in the URL is a client error,
        # not a server fault -- without this it would surface as a bare 500
        # via the catch-all handler.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown or misconfigured business_id: {business_id!r}",
        ) from error

    return ChatResponse(
        success=True,
        conversation_id=request.conversation_id,
        response=response,
    )


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    The original endpoint, unchanged in behaviour.

    Serves DEFAULT_BUSINESS_ID. chat_widget.html and every existing
    integration call this and must keep working with zero changes -- the
    per-business route below is purely additive.
    """
    return _handle(request, DEFAULT_BUSINESS_ID)


@router.post("/{business_id}", response_model=ChatResponse)
def chat_for_business(business_id: str, request: ChatRequest):
    """
    Same request/response shape as POST /chat, routed to the engine for
    business_id.
    """
    return _handle(request, business_id)
