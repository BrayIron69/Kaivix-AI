from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.handlers.exceptions import register_exception_handlers
from api.middleware.logging import register_logging_middleware

from api.routers.health import router as health_router
from api.routers.leads import router as leads_router
from api.routers.chat import router as chat_router


app = FastAPI(
    title="Kaivix Labs AI Sales Agent API",
    version="1.0.0",
    description="Backend API for the Kaivix Labs AI Sales Agent CRM",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
register_logging_middleware(app)


@app.get("/")
def root():
    return {
        "message": "Kaivix Labs AI Sales Agent API"
    }


app.include_router(health_router)
app.include_router(leads_router)
app.include_router(chat_router)