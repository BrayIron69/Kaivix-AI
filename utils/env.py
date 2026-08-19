"""
Single, idempotent environment bootstrap for the whole application.

Importing this module guarantees that any values in a local `.env` file
have been loaded into os.environ. Every module that reads an
environment variable should import it, so that module is correct on its
own rather than depending on some *other* import happening first.

Why this exists
---------------
`load_dotenv()` used to live only in config.py, as a side effect of
importing that module. config.py is the LLM configuration
(GROQ_API_KEY / MODEL / MAX_TOKENS), so nothing in the OAuth or admin
code had any reason to import it -- and nothing did.

The result was a real bug, found during live Gmail verification rather
than by any test: on a freshly started local server
(`uvicorn api.main:app`), api/routers/calendar_oauth.py constructs
GoogleCalendarProvider() at import time, which reads GOOGLE_CLIENT_ID
and GOOGLE_CLIENT_SECRET at construction. Nothing had imported config
yet, so load_dotenv() had not run, and both read as None. The server
then sent `client_id=None` to Google on every /oauth/google/connect
request and Google answered "401 invalid_client: The OAuth client was
not found" -- for the entire life of the process, or until some
unrelated code path (the first chat message, which reaches utils/llm.py
-> config) happened to trigger dotenv lazily and fix it by accident.

The same latent bug applied to api/routers/admin.py's ADMIN_USERNAME /
ADMIN_PASSWORD: read at request time, which on a fresh server could
land before anything had triggered dotenv, and that route treats a
missing credential as "denied" -- so admin would have been locked out
rather than merely misconfigured.

Production safety (Render and any other real deployment)
--------------------------------------------------------
This is a no-op wherever real environment variables are set by the
platform, for two independent reasons:

  1. There is no .env file in a production image (.dockerignore excludes
     env files), and load_dotenv() with no file present simply returns
     False without touching os.environ.
  2. load_dotenv() defaults to override=False, so even if a .env file
     somehow were present, it can only fill in variables that are not
     already set -- it can never replace a real platform-provided value.

So this changes local-development behavior (from broken to correct) and
leaves deployed behavior exactly as it was.
"""

from dotenv import load_dotenv

# Runs once, at first import, by normal Python module-caching semantics.
# Deliberately module-level rather than a function callers must remember
# to call: the guarantee this module exists to provide is "importing me
# is sufficient".
load_dotenv()
