from fastapi import APIRouter, Depends, Header, HTTPException, status

from auth.api_key_store import APIKeyStore
from core_ai.business_config import BusinessConfigError, DEFAULT_BUSINESS_ID
from schemas.chat import MAX_MESSAGE_LENGTH, ChatRequest, ChatResponse
from services.chat_service import ChatService

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

chat_service = ChatService()

api_key_store = APIKeyStore()

# Plain `X-API-Key`, rather than `Authorization: Bearer`. Bearer implies a
# token the server can introspect for a subject; here the header's value IS
# the identity assertion for the business_id already named in the path, and
# the admin dashboard on this same app already uses `Authorization` for
# Basic Auth. Keeping them on separate headers avoids one scheme's
# middleware ever seeing the other's credential.
API_KEY_HEADER = "X-API-Key"


def require_business_api_key(
    business_id: str,
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
) -> None:
    """
    Authorize a caller for this specific business_id.

    Attached to POST /chat/{business_id} ONLY. Plain POST /chat has no
    authentication and must never gain any -- see the note on that route.

    Runs as a dependency, so it completes before the handler body: an
    unauthorized caller never reaches business-config loading or engine
    construction. That ordering is deliberate on two counts. It keeps
    unauthenticated requests from doing real work (no engine is built, no
    knowledge base is read), and it means an unknown business_id returns the
    same 401 as a known one, so this endpoint cannot be used to enumerate
    which business_ids exist.

    Every failure is the same 401 with the same message -- missing header,
    wrong key, a key belonging to another business, or a business with no
    key issued at all. Distinguishing them would answer questions a caller
    holding no valid credential has no right to ask. In particular an
    unprovisioned business is closed, not open: unconfigured means denied,
    the same stance as api/routers/admin.py's "no default credentials".
    """
    if not api_key_store.verify_key(business_id, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"A valid {API_KEY_HEADER} header is required for this "
                f"business."
            ),
        )


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

    DELIBERATELY UNAUTHENTICATED, and it must stay that way. This is the
    live marketing widget's actual traffic: an anonymous visitor on the
    public site, with no credential to present and nowhere to hide one (the
    widget is client-side JavaScript, so any key shipped to it would be
    readable by anyone viewing source -- authentication here would be
    theatre, not security). Requiring a key on this route is a production
    outage. TestPlainChatEndpointUnchanged in
    tests/test_multi_business_serving.py and TestPlainChatRemainsOpen in
    tests/test_chat_business_auth.py both exist to catch that.
    """
    return _handle(request, DEFAULT_BUSINESS_ID)


@router.post(
    "/{business_id}",
    response_model=ChatResponse,
    dependencies=[Depends(require_business_api_key)],
)
def chat_for_business(business_id: str, request: ChatRequest):
    """
    Same request/response shape as POST /chat, routed to the engine for
    business_id -- but requires a valid X-API-Key issued for that specific
    business (see require_business_api_key).

    The authentication is declared on this route alone rather than on the
    router, because the router also carries plain POST /chat, which must
    remain open.
    """
    return _handle(request, business_id)
