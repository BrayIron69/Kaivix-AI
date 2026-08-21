"""
Per-business API keys, resolved from the environment rather than from a
local database.

Why this replaced auth/api_key_store.py
---------------------------------------
The SQLite store worked correctly and was never wrong about anything it
was asked -- but its entire value proposition was persistence, and it had
none where it mattered. `auth/api_keys.db` is excluded by BOTH .gitignore
and .dockerignore, so it is not in the repo and not in the production
image; Render has no persistent disk configured (no render.yaml), so its
filesystem is wiped on every deploy. The net effect was that NO
business-scoped credential could survive in production at all: a key
issued by the old script existed only on the machine that ran it.

This was found by checking the real deployment rather than assuming --
`POST /voice/kaivix/chat/completions` on the live instance returns 401 for
every key, because production has never held one.

Environment variables are the mechanism that already demonstrably
survives deploys here: ADMIN_USERNAME / ADMIN_PASSWORD / GROQ_API_KEY /
GOOGLE_CLIENT_ID are all real, working production secrets set exactly
this way.

Why ONE variable holding a mapping, not one variable per business
-----------------------------------------------------------------
The obvious alternative is a naming convention -- BUSINESS_API_KEY_KAIVIX,
BUSINESS_API_KEY_ACME. It was rejected because business_id is used
verbatim everywhere else in this codebase (config/businesses/<id>/, the
CRM's business_id column, ConversationMemory's scoping) and can contain
characters an environment variable name cannot: `test-business-b` would
have to be normalised to TEST_BUSINESS_B, at which point `test-business-b`
and `test_business_b` collide into the same variable and silently
authenticate each other. A collision in an auth path is exactly the
"looks like it works" failure Decision #024 called out for a single shared
secret. A JSON mapping sidesteps normalisation entirely: keys are compared
as the literal business_id string.

It is also one manual step on Render regardless of how many businesses
exist, which matters because adding it is a human action taken rarely and
under no automation.

Why the mapping holds HASHES, not the keys themselves
------------------------------------------------------
Decision #024 chose to store only a SHA-256 hash, reasoning that "a stolen
database read must not yield a usable credential." Moving the store should
not quietly drop that property, so it did not: the variable holds
business_id -> SHA-256 hex, and verification hashes the presented value
and compares in constant time. An env dump, a screenshot of the Render
dashboard, or a leaked process listing therefore still yields nothing
directly presentable.

SHA-256 rather than bcrypt/argon2, unchanged and for the unchanged reason:
these keys are 32 bytes of os.urandom, so there is no dictionary to run,
and a deliberately slow KDF would tax every authenticated request on the
hot path. Constant-time comparison is the property that matters.
"""

import hashlib
import json
import os
import secrets

# Imported for its side effect (load_dotenv at import time), so a local
# .env supplies BUSINESS_API_KEYS the same way Render's dashboard does in
# production -- see utils/env.py. This is what lets local development and
# production run the SAME code path rather than two different ones.
import utils.env  # noqa: F401

from utils.logger import Logger

# The single environment variable holding every business's key hash, as a
# JSON object: {"<business_id>": "<sha256-hex-of-key>"}.
ENV_VAR = "BUSINESS_API_KEYS"

# Prefix on every generated key. Makes a leaked key identifiable as ours
# in a log or a secret scanner, and makes it obvious what someone is
# holding. Deliberately not a known vendor's prefix -- see commit d32001d,
# where a test sentinel that looked like a Groq key was renamed for the
# same reason.
KEY_PREFIX = "kvx_"

# 32 bytes of os.urandom, URL-safe base64 encoded (~43 characters). Well
# beyond guessing range, and safe to send in an HTTP header unencoded.
_KEY_ENTROPY_BYTES = 32


def generate_key() -> str:
    """
    A new, strong API key. Generated only -- never stored anywhere by this
    module, because nothing here writes. See scripts/generate_api_key.py
    for the real issuing process.
    """
    return KEY_PREFIX + secrets.token_urlsafe(_KEY_ENTROPY_BYTES)


def hash_key(key: str) -> str:
    """
    The one definition of how a key maps to its stored form. Generating
    and verifying both go through this, so they cannot drift apart.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _load_key_hashes() -> dict[str, str]:
    """
    Parse ENV_VAR into {business_id: key_hash}.

    Read at CALL time, not import time, so rotating the value on Render
    takes effect on restart without a code change and tests can override
    it -- the same discipline api/routers/admin.py's require_admin already
    uses for ADMIN_USERNAME / ADMIN_PASSWORD.

    Every failure mode returns {} (deny everything) rather than raising.
    An unparseable value must not become a 500 on an auth path, and it
    must never fail open: "unconfigured means closed" is the stance
    Decision #024 set and admin.py already follows. Malformed input is
    logged at error level because it means a real, currently-authenticated
    integration has just stopped working, and nothing else would say so.
    """
    raw = (os.getenv(ENV_VAR) or "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        Logger().error(
            f"[BusinessAPIKeys] {ENV_VAR} is not valid JSON, so every "
            f"business-scoped request will be rejected: {error}"
        )
        return {}

    if not isinstance(parsed, dict):
        Logger().error(
            f"[BusinessAPIKeys] {ENV_VAR} must be a JSON object mapping "
            f"business_id to key hash, got {type(parsed).__name__}. Every "
            f"business-scoped request will be rejected."
        )
        return {}

    hashes: dict[str, str] = {}
    for business_id, key_hash in parsed.items():
        if isinstance(key_hash, str) and key_hash.strip():
            hashes[str(business_id)] = key_hash.strip()
        else:
            # One bad entry must not deny every OTHER business too, so
            # this skips rather than returning {} -- but it is still
            # logged, because that business's own callers are now locked
            # out and this is the only signal.
            Logger().error(
                f"[BusinessAPIKeys] {ENV_VAR} entry for "
                f"business_id={business_id!r} is not a non-empty string; "
                f"that business's requests will be rejected."
            )

    return hashes


def verify_key(business_id: str, presented_key: str | None) -> bool:
    """
    True only if presented_key is the current key for business_id.

    False for every other case -- no key presented, no key on record for
    that business, or a key belonging to a different business. The lookup
    is scoped by business_id BEFORE any comparison happens, so a key
    issued for business-a can never satisfy business-b. That is the
    property that makes this authenticate the *business* and not merely
    the caller (Decision #024).
    """
    if not presented_key:
        return False

    expected_hash = _load_key_hashes().get(business_id)
    if not expected_hash:
        return False

    return secrets.compare_digest(hash_key(presented_key), expected_hash)


def configured_business_ids() -> list[str]:
    """
    Which businesses currently have a key configured. Never used to
    authorize anything -- only for operational reporting (a startup
    check, a script confirming what is provisioned).
    """
    return sorted(_load_key_hashes())
