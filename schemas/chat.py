from pydantic import BaseModel, Field

# Longest customer message the /chat endpoints will accept.
#
# There was no cap at all, so one request could carry an arbitrarily large
# body straight into the prompt and burn a large amount of Groq token budget
# in a single call -- cheap to send, expensive to serve, and repeatable.
#
# 2000 characters is roughly 500 tokens: comfortably more than any real
# customer message on a web chat widget, and small enough that the per-call
# cost stays bounded.
#
# Deliberately NOT enforced as a pydantic max_length here: that raises
# RequestValidationError, which FastAPI renders as 422. The cap is enforced
# in api/routers/chat.py so it can return a 400 with a message that says what
# the limit is, without changing how validation errors are reported for
# every other endpoint.
MAX_MESSAGE_LENGTH = 2000

# Accepted shape of a visitor_id.
#
# The widget mints these with crypto.randomUUID(), so the real traffic is
# always a 36-character UUID. The pattern is a little wider than that
# (unreserved URL characters only) so the id can travel in a path or
# query string unescaped and so a future client is not forced onto one
# exact format -- but it is narrow enough to reject the things that
# matter: no whitespace, no quotes, no path separators, no wildcards.
#
# The length floor is the security-relevant half. A visitor_id is a
# bearer capability -- whoever holds it can list and reopen that
# visitor's threads -- so a short, guessable one is the whole
# vulnerability. 16 characters of the charset below is well past
# brute-forcing, and a real UUID is far past it.
VISITOR_ID_PATTERN = r"^[A-Za-z0-9_-]{16,100}$"


class ChatRequest(BaseModel):
    """
    Incoming chat request.
    """

    conversation_id: str = Field(
        ...,
        description="Unique conversation identifier.",
        examples=["conv_001"],
    )

    visitor_id: str | None = Field(
        default=None,
        pattern=VISITOR_ID_PATTERN,
        description=(
            "Stable per-browser identifier, used to group this visitor's "
            "conversations so they can be listed and reopened later. "
            "Optional: omitting it is supported and simply produces a "
            "conversation that no thread list will show."
        ),
        examples=["3f2b1c8a-9d4e-4f1a-8b7c-2e5d6a0f9c31"],
    )

    message: str = Field(
        ...,
        min_length=1,
        description=(
            f"Customer message. Must be {MAX_MESSAGE_LENGTH} characters or "
            f"fewer; longer messages are rejected with HTTP 400."
        ),
        examples=["Hi, I'm interested in AI automation."],
    )


class ChatResponse(BaseModel):
    """
    AI chat response.
    """

    success: bool = True

    conversation_id: str

    response: str


class ConversationThread(BaseModel):
    """
    One row of the widget's Messages tab.

    Named 'thread' rather than 'conversation summary' to keep it clearly
    distinct from core_ai/conversation_summary.py, which is the engine
    that writes a narrative summary for the prompt and has nothing to do
    with this.
    """

    conversation_id: str

    last_message_at: str = Field(
        description="ISO 8601 UTC timestamp of the most recent message.",
        examples=["2026-09-11T14:22:05Z"],
    )

    message_count: int

    preview: str = Field(
        description="Truncated text of the most recent message.",
        examples=["Yes, we work with dental practices."],
    )


class ConversationListResponse(BaseModel):
    """A visitor's threads, most recently active first."""

    success: bool = True

    conversations: list[ConversationThread]


class ConversationMessage(BaseModel):
    """One stored turn, in the shape the widget renders."""

    role: str = Field(examples=["user", "assistant"])

    content: str


class ConversationMessagesResponse(BaseModel):
    """One reopened thread's full history, oldest first."""

    success: bool = True

    conversation_id: str

    messages: list[ConversationMessage]