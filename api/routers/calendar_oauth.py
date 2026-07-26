from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from scheduling.google_calendar_provider import GoogleCalendarProvider

router = APIRouter(
    prefix="/oauth/google",
    tags=["Calendar OAuth"],
)

provider = GoogleCalendarProvider()


@router.get("/connect")
def connect(business_id: str):
    auth_url = provider.get_authorization_url(business_id)
    return RedirectResponse(auth_url)


@router.get("/callback")
def callback(request: Request):
    # business_id was encoded into the OAuth `state` param by
    # get_authorization_url() above -- this is how the callback (a
    # separate request, with no other context) knows which business
    # this authorization belongs to.
    business_id = request.query_params.get("state")
    if not business_id:
        raise HTTPException(
            status_code=400,
            detail="Missing state (business_id) in Google's OAuth callback.",
        )

    provider.handle_oauth_callback(business_id, str(request.url))

    return HTMLResponse(
        "<html><body><h3>Google Calendar connected successfully.</h3>"
        "<p>You can close this tab.</p></body></html>"
    )
