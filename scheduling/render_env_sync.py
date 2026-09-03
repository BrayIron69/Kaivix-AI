import json
import os

import requests

from utils.logger import Logger

# Mirrors auth/business_api_keys.py's ENV_VAR convention: one variable
# holding a JSON {business_id: value} mapping, not one variable per
# business -- business_id can contain characters an env var name
# cannot, and a naming-convention scheme would risk exactly the
# collision Decision #024 already rejected a shared secret for. See
# that module's docstring for the full reasoning; it applies verbatim
# here.
REFRESH_TOKENS_ENV_VAR = "GOOGLE_CALENDAR_REFRESH_TOKENS"

_RENDER_API_BASE = "https://api.render.com/v1"
_REQUEST_TIMEOUT_SECONDS = 15

# Render's own dashboard/CLI never expose more env vars per service than
# this in practice; one page is enough, but pagination is handled below
# regardless rather than silently truncating a service with more.
_ENV_VARS_PAGE_SIZE = 100


def persist_calendar_refresh_token(business_id: str, refresh_token: str) -> bool:
    """
    Best-effort: write business_id's Google Calendar refresh_token into
    Render's GOOGLE_CALENDAR_REFRESH_TOKENS env var, so it survives the
    next redeploy the same way BUSINESS_API_KEYS/ADMIN_PASSWORD/
    GROQ_API_KEY/GOOGLE_CLIENT_SECRET already do (see
    auth/business_api_keys.py, commit b07ec45).

    Why this is needed at all: scheduling/calendar_tokens.db is excluded
    from both .gitignore and .dockerignore, and Render has no persistent
    disk (no render.yaml) -- the exact same wipe-on-deploy mechanism that
    broke business API keys before b07ec45 also applies to the calendar
    OAuth token, and was never separately fixed. GoogleCalendarProvider
    still writes to that local SQLite file as a same-process cache (see
    its _load_credentials), but this is the copy that actually survives.

    Only the refresh_token is persisted here, never the short-lived
    access token or its expiry -- refresh_token does not rotate on a
    normal google-auth refresh() call (Google returns the same one for
    the life of the grant), so it is the one value that is both durable
    and cheap to keep in sync. A fresh access token is always re-derived
    from it via Credentials.refresh() after a redeploy, which costs one
    real network call to Google, not a second wipe-prone store.

    Render's env-var API is bulk-replace only -- there is no documented
    single-key endpoint (confirmed by scripts/generate_api_key.py's own
    --merge-with dance, which exists for exactly this reason). This
    function therefore reads every existing env var first and PUTs the
    complete set back with only GOOGLE_CALENDAR_REFRESH_TOKENS changed,
    never touching any other variable's value.

    Never raises: this is a durability improvement layered on top of an
    OAuth connect that has already succeeded (handle_oauth_callback has
    a real, working calendar connection for this process's lifetime
    regardless of whether this call succeeds). RENDER_API_KEY/
    RENDER_SERVICE_ID missing, a network error, or a malformed existing
    value are all logged loudly -- both print() and Logger(), the same
    pairing require_business_api_key and the request-timing middleware
    already use, since Render's Logs view is stdout/stderr only and a
    Logger()-only line would be invisible there -- and treated as "this
    business's calendar connection will need to be redone after the next
    redeploy" rather than failing the request the business owner is
    sitting in front of.

    Returns True on confirmed success, False otherwise, so callers and
    tests can assert on the outcome without needing to catch anything.
    """
    logger = Logger()
    api_key = os.getenv("RENDER_API_KEY")
    service_id = os.getenv("RENDER_SERVICE_ID")

    if not api_key or not service_id:
        _log_error(
            logger,
            f"RENDER_API_KEY and/or RENDER_SERVICE_ID not set -- "
            f"refresh_token for business_id={business_id!r} was NOT "
            f"persisted past this process's lifetime and will be lost "
            f"on the next redeploy.",
        )
        return False

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        current_env_vars = _fetch_all_env_vars(service_id, headers)
    except Exception as error:
        _log_error(
            logger,
            f"Failed to read current Render env vars for "
            f"business_id={business_id!r}: {type(error).__name__}: {error}",
        )
        return False

    existing_tokens = _parse_existing_tokens(current_env_vars.get(REFRESH_TOKENS_ENV_VAR), logger)
    existing_tokens[business_id] = refresh_token

    merged_env_vars = dict(current_env_vars)
    merged_env_vars[REFRESH_TOKENS_ENV_VAR] = json.dumps(
        existing_tokens, separators=(",", ":"), sort_keys=True
    )

    try:
        response = requests.put(
            f"{_RENDER_API_BASE}/services/{service_id}/env-vars",
            headers=headers,
            json=[{"key": key, "value": value} for key, value in merged_env_vars.items()],
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except Exception as error:
        _log_error(
            logger,
            f"Failed to write {REFRESH_TOKENS_ENV_VAR} to Render for "
            f"business_id={business_id!r}: {type(error).__name__}: {error}",
        )
        return False

    _log_info(
        logger,
        f"Persisted refresh_token for business_id={business_id!r} to "
        f"Render env vars -- will survive the redeploy this write itself "
        f"triggers.",
    )
    return True


def load_refresh_token(business_id: str) -> str | None:
    """
    Read business_id's refresh_token back out of
    GOOGLE_CALENDAR_REFRESH_TOKENS, or None if unset/malformed/absent
    for this business. Read fresh on every call, never cached at import
    -- same reasoning require_admin/require_business_api_key already
    document: a value changed on the host must take effect on the next
    request, not require a code change.
    """
    raw = (os.getenv(REFRESH_TOKENS_ENV_VAR) or "").strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict):
        return None

    token = parsed.get(business_id)
    return token if isinstance(token, str) and token else None


def _fetch_all_env_vars(service_id: str, headers: dict) -> dict:
    """
    GET every env var currently set on this service, paging via Render's
    cursor param. Returns {key: value}. Raises on any HTTP/network
    failure -- the caller decides how to handle that.
    """
    env_vars: dict = {}
    cursor = None

    while True:
        params = {"limit": _ENV_VARS_PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{_RENDER_API_BASE}/services/{service_id}/env-vars",
            headers=headers,
            params=params,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        page = response.json()

        for item in page:
            env_var = item.get("envVar") or {}
            key = env_var.get("key")
            if key is not None:
                env_vars[key] = env_var.get("value", "")

        if len(page) < _ENV_VARS_PAGE_SIZE:
            break
        cursor = page[-1].get("cursor")
        if not cursor:
            break

    return env_vars


def _parse_existing_tokens(raw_existing, logger: Logger) -> dict:
    """
    Parse the current GOOGLE_CALENDAR_REFRESH_TOKENS value into a dict,
    or {} if unset. A malformed or non-dict existing value is logged and
    treated as empty rather than merged into -- refusing to guess a
    shape here is what keeps a corrupt value from being silently
    perpetuated, at the cost of that write losing whatever the corrupt
    value held (which was already unusable).
    """
    if not raw_existing:
        return {}

    try:
        parsed = json.loads(raw_existing)
    except json.JSONDecodeError:
        _log_error(
            logger,
            f"Existing {REFRESH_TOKENS_ENV_VAR} is not valid JSON -- "
            f"ignoring it rather than risk overwriting an unrelated "
            f"value with a partial merge.",
        )
        return {}

    if not isinstance(parsed, dict):
        _log_error(
            logger,
            f"Existing {REFRESH_TOKENS_ENV_VAR} is not a JSON object -- "
            f"ignoring it rather than risk overwriting an unrelated "
            f"value with a partial merge.",
        )
        return {}

    return {str(k): str(v) for k, v in parsed.items()}


def _log_error(logger: Logger, message: str) -> None:
    line = f"[CalendarTokenRenderSync] {message}"
    print(line)
    logger.error(line)


def _log_info(logger: Logger, message: str) -> None:
    line = f"[CalendarTokenRenderSync] {message}"
    print(line)
    logger.info(line)
