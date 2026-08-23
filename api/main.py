from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.handlers.exceptions import register_exception_handlers
from api.middleware.logging import register_logging_middleware

from api.routers.health import router as health_router
from api.routers.leads import router as leads_router
from api.routers.chat import router as chat_router
from api.routers.calendar_oauth import router as calendar_oauth_router
from api.routers.admin import router as admin_router
from api.routers.voice import router as voice_router


app = FastAPI(
    title="Kaivix Labs AI Sales Agent API",
    version="1.0.0",
    description="Backend API for the Kaivix Labs AI Sales Agent CRM",
)

# The only origins that legitimately call this API from a browser: the
# marketing site that embeds the chat widget, and this backend's own
# domain. Previously allow_origins=["*"], which -- combined with
# allow_credentials -- meant Starlette echoed back whatever Origin the
# caller sent, so any site on the internet could call this API with the
# visitor's credentials attached.
#
# These are exact-match origins -- a different scheme, host, or port is a
# different origin, and there is no wildcard/subdomain matching.
#
# Both the apex and www are listed because the marketing site is served
# from www: https://kaivixlab.com returns a 308 to
# https://www.kaivixlab.com (verified against the live Vercel
# deployment), so the Origin real visitors' browsers send is the www one.
# Listing www alone would be enough today; the apex is kept so a direct
# apex-origin request doesn't depend on redirect behavior staying put.
#
# Nothing else is covered. "http://localhost:8000" and any other
# subdomain must be added explicitly if they are ever needed.
ALLOWED_ORIGINS = [
    "https://kaivixlab.com",
    "https://www.kaivixlab.com",
    "https://kaivix-ai.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
register_logging_middleware(app)


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    # FastAPI does not add HEAD automatically for a GET-only route (verified
    # locally, not assumed) -- an uptime monitor probing with HEAD got a
    # bare 405 on every check, which is exactly the repeated
    # "HEAD / HTTP/1.1" 405 pattern seen in every deploy log this session.
    return {
        "message": "Kaivix Labs AI Sales Agent API"
    }


app.include_router(health_router)
app.include_router(leads_router)
app.include_router(chat_router)
app.include_router(calendar_oauth_router)
app.include_router(admin_router)
app.include_router(voice_router)