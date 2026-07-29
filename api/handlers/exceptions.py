from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException

from utils.exceptions import LLMUnavailableError


# Shown to the visitor when the LLM provider is down. Deliberately says the
# fault is ours, gives a retry hint, and offers a channel that does not
# depend on the AI working -- an outage should cost a slow reply, not a lead.
LLM_UNAVAILABLE_MESSAGE = (
    "Bray is temporarily unavailable — this is a problem on our side, "
    "not yours. Please try again in a moment, or email "
    "brayiron@kaivixlab.com and we'll pick it up from there."
)


def register_exception_handlers(app: FastAPI):

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": exc.status_code,
                    "message": exc.detail,
                },
            },
            # Starlette's default handler forwards exc.headers; this one has
            # to as well, or a 401 loses its WWW-Authenticate challenge and
            # browsers never prompt for credentials (api/routers/admin.py).
            headers=getattr(exc, "headers", None),
        )

    # Registered ahead of the catch-all below. Starlette resolves handlers by
    # walking type(exc).__mro__ and taking the first match, so this specific
    # handler wins over the Exception one -- an LLM outage becomes a
    # retryable 503 instead of being flattened into "Internal Server Error".
    #
    # Registering it centrally means every chat route is covered without each
    # one needing its own try/except.
    @app.exception_handler(LLMUnavailableError)
    async def llm_unavailable_handler(
        request: Request,
        exc: LLMUnavailableError,
    ):
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": {
                    "code": 503,
                    "message": LLM_UNAVAILABLE_MESSAGE,
                },
            },
            # Tells well-behaved clients this is worth retrying, and stops
            # any cache from holding on to the failure.
            headers={"Retry-After": "30"},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request,
        exc: Exception,
    ):
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": 500,
                    "message": "Internal Server Error",
                },
            },
        )