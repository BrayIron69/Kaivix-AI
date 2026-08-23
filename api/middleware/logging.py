import time

from fastapi import FastAPI, Request

from utils.logger import Logger


def register_logging_middleware(app: FastAPI):

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.perf_counter()

        response = await call_next(request)

        duration = (time.perf_counter() - start_time) * 1000

        line = (
            f"{request.method} {request.url.path} - "
            f"{response.status_code} - {duration:.2f}ms"
        )

        # Render has no persistent disk, and its Logs view is stdout/stderr
        # only -- a plain `logging.getLogger(__name__)` with no handler
        # attached is invisible there, which is exactly what silently
        # discarded this line's real, computed duration for as long as
        # this middleware has existed. print() is what actually reaches
        # the captured log stream; Logger() keeps the same line in the
        # local file too. Same pairing ConversationEngine._log_turn and
        # require_business_api_key's auth diagnostic already use.
        print(line)
        Logger().info(line)

        return response
