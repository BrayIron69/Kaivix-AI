from fastapi import APIRouter

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.api_route("", methods=["GET", "HEAD"])
def health_check():
    return {
        "status": "healthy",
        "service": "Kaivix Labs AI Sales Agent API",
        "version": "1.0.0"
    }