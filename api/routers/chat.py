from fastapi import APIRouter

from schemas.chat import ChatRequest, ChatResponse
from services.chat_service import ChatService

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

chat_service = ChatService()


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest):

    response = chat_service.chat(
        conversation_id=request.conversation_id,
        message=request.message,
    )

    return ChatResponse(
        success=True,
        conversation_id=request.conversation_id,
        response=response,
    )