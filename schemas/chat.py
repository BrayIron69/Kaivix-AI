from pydantic import BaseModel, Field


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
        description="Customer message.",
        examples=["Hi, I'm interested in AI automation."],
    )


class ChatResponse(BaseModel):
    """
    AI chat response.
    """

    success: bool = True

    conversation_id: str

    response: str