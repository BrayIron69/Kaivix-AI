from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from auth import business_api_keys
from core_ai.business_config import BusinessConfigError, DEFAULT_BUSINESS_ID
from schemas.chat import (
    MAX_MESSAGE_LENGTH,
    VISITOR_ID_PATTERN,
    ChatRequest,
    ChatResponse,
    ConversationListResponse,
    ConversationMessagesResponse,
)
from services.chat_service import ChatService
from utils.logger import Logger

# Most threads one request may ask for. The store has its own default
# (see DEFAULT_CONVERSATION_LIMIT); this is the ceiling a caller cannot
# exceed, so a crafted limit cannot turn one request into an unbounded
# read.
MAX_CONVERSATION_LIMIT = 100

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

chat_service = ChatService()

# Plain `X-API-Key`, rather than `Authorization: Bearer`. Bearer implies a
# token the server can introspect for a subject; here the header's value IS
# the identity assertion for the business_id already named in the path, and
# the admin dashboard on this same app already uses `Authorization` for
# Basic Auth. Keeping them on separate headers avoids one scheme's
# middleware ever seeing the other's credential.
API_KEY_HEADER = "X-API-Key"


def require_business_api_key(
    business_id: str,
    request: Request,
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

    Keys come from the BUSINESS_API_KEYS environment variable, not from a
    local database -- see auth/business_api_keys.py for why that changed.
    The verification logic itself (scoped by business_id before any
    comparison, constant-time, hash-at-rest) is unchanged.

    Called as a module attribute rather than a `from ... import`, so tests
    that patch the environment see their patch take effect -- the value is
    read on every call, never cached at import.
    """
    if not business_api_keys.verify_key(business_id, x_api_key):
        # --- TEMPORARY DEBUG LOGGING -- remove once the live Vapi 401 is
        # diagnosed (see chat log ~2026-08-22, "isolate the real 401").
        # Never logs the raw key -- only lengths and SHA-256 hashes, same
        # non-echo discipline as test_401_does_not_echo_the_presented_key.
        # `x_api_key` is what FastAPI bound from the header; `raw_header`
        # is read directly off the ASGI request, independent of FastAPI's
        # own parsing, to catch anything upstream altering the value
        # before it reaches the comparison. `expected_hash` is already a
        # one-way SHA-256 hash at rest in BUSINESS_API_KEYS, so logging it
        # exposes nothing the env var doesn't already hold.
        raw_header = request.headers.get(API_KEY_HEADER)
        expected_hash = business_api_keys._load_key_hashes().get(business_id)
        debug_line = (
            "[AuthDebug-TEMP] "
            f"path={request.url.path!r} business_id={business_id!r} | "
            f"parsed_key len={len(x_api_key) if x_api_key else 0} "
            f"sha256={business_api_keys.hash_key(x_api_key) if x_api_key else None} | "
            f"raw_header len={len(raw_header) if raw_header else 0} "
            f"sha256={business_api_keys.hash_key(raw_header) if raw_header else None} | "
            f"expected_hash_configured={expected_hash is not None} "
            f"expected_hash={expected_hash}"
        )
        # Logger() alone writes only to logs/app.log on local disk -- on
        # Render (no persistent disk, and the dashboard's Logs view is
        # stdout/stderr only) that file is invisible and gets wiped on
        # the next deploy. print() is what actually reaches the captured
        # log stream, same reasoning ConversationEngine._log_turn_summary
        # already documents ("stdout is not a safer destination than the
        # log file -- under a container runtime it is collected the same
        # way"). Both are kept: print for Render's Logs view, Logger for
        # local/file-based debugging.
        print(debug_line)
        Logger().error(debug_line)
        # --- END TEMPORARY DEBUG LOGGING ---

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
            visitor_id=request.visitor_id,
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


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    visitor_id: str = Query(
        ...,
        pattern=VISITOR_ID_PATTERN,
        description="The browser's stable visitor identifier.",
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=MAX_CONVERSATION_LIMIT,
        description="Maximum threads to return.",
    ),
):
    """
    This visitor's past conversations for DEFAULT_BUSINESS_ID, most
    recently active first. Backs the widget's Messages tab.

    Unauthenticated, for exactly the reason plain POST /chat is: the
    caller is an anonymous visitor on the public marketing site with no
    credential to present. The visitor_id itself is the authorization --
    it is high-entropy, minted in the visitor's own browser, and never
    guessable from outside (see VISITOR_ID_PATTERN for why the length
    floor is the security-relevant part).

    That makes this endpoint exactly as strong as the visitor_id is
    secret, which is the same trust model as an unguessable share link.
    It is scoped to that: a visitor's own chat threads with a sales bot
    on a public website. Anything more sensitive than that does not
    belong behind this kind of identifier.

    An unknown visitor_id returns an empty list rather than a 404 -- a
    first-time visitor and a made-up id are indistinguishable, and they
    should be.
    """
    conversations = chat_service.list_conversations(
        visitor_id=visitor_id,
        business_id=DEFAULT_BUSINESS_ID,
        limit=limit,
    )

    return ConversationListResponse(conversations=conversations)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationMessagesResponse,
)
def get_conversation(
    conversation_id: str,
    visitor_id: str = Query(
        ...,
        pattern=VISITOR_ID_PATTERN,
        description="The browser's stable visitor identifier.",
    ),
):
    """
    One past conversation's full history, oldest first, so the widget
    can reopen it and continue it.

    Returns 404 unless this visitor owns this conversation. The
    ownership check lives in ChatService.get_conversation -- see there
    for why it is mandatory rather than best-effort.

    "Not yours" and "does not exist" deliberately return the same 404
    with the same message. Distinguishing them would turn this route
    into an oracle for which conversation ids exist, and those ids are
    currently low-entropy enough to enumerate.
    """
    messages = chat_service.get_conversation(
        conversation_id=conversation_id,
        visitor_id=visitor_id,
        business_id=DEFAULT_BUSINESS_ID,
    )

    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such conversation for this visitor.",
        )

    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        messages=messages,
    )


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
