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


class ChatRequest(BaseModel):
    """
    Incoming chat request.
    """

    conversation_id: str = Field(
        ...,
        description="Unique conversation identifier.",
        examples=["conv_001"],
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