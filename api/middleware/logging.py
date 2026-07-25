import time
import logging

from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)


def register_logging_middleware(app: FastAPI):

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.perf_counter()

        response = await call_next(request)

        duration = (time.perf_counter() - start_time) * 1000

        logger.info(
            "%s %s - %s - %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )

        return response