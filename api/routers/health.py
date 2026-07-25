from fastapi import APIRouter

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.get("")
def health_check():
    return {
        "status": "healthy",
        "service": "Kaivix Labs AI Sales Agent API",
        "version": "1.0.0"
    }