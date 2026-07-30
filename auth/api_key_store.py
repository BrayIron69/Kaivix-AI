import hashlib
import secrets
import sqlite3
from datetime import datetime, timezone

# Prefix on every issued key. Makes a leaked key identifiable as ours in a
# log or a secret scanner, and makes it obvious what someone is holding.
# Deliberately not a known vendor's prefix -- see commit d32001d, where a
# test sentinel that looked like a Groq key was renamed for the same reason.
KEY_PREFIX = "kvx_"

# 32 bytes of os.urandom, URL-safe base64 encoded (~43 characters). Well
# beyond guessing range, and safe to send in an HTTP header unencoded.
_KEY_ENTROPY_BYTES = 32


class APIKeyStore:
    """
    Tenant-scoped SQLite storage for per-business API keys.

    Mirrors scheduling/calendar_token_store.py: this class owns nothing but
    "issue a key for a business_id" / "verify a presented key" / "revoke it".
    The route dependency in api/routers/chat.py is the only production
    caller; scripts/issue_api_key.py is the only writer.

    business_id is the PRIMARY KEY: one active key per business. Re-issuing
    replaces the previous row rather than accumulating history, exactly like
    CalendarTokenStore treats reconnecting a calendar -- there is one
    "current" credential per business at a time. That means issuing a new
    key immediately invalidates the old one, which is the desired behaviour
    for rotation-by-replacement.

    Only a SHA-256 hash of the key is stored, never the key itself. A read
    of this database (backup, stolen disk, careless copy) yields nothing an
    attacker can present to /chat/{business_id}.

    Why a plain SHA-256 and not bcrypt/argon2: those exist to make brute
    force expensive against LOW-entropy human-chosen passwords. These keys
    are 32 bytes of os.urandom, so there is no dictionary to run and no
    guessing surface for a slow KDF to protect. A deliberately slow KDF
    would instead add latency to every single /chat request, which is the
    hot path. Constant-time comparison (secrets.compare_digest, the same
    discipline as api/routers/admin.py's Basic Auth check) is what matters
    here, and that is used below.
    """

    DB_PATH = "auth/api_keys.db"

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or self.DB_PATH
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                business_id TEXT PRIMARY KEY,
                key_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    @staticmethod
    def hash_key(key: str) -> str:
        """
        The one definition of how a key maps to its stored form. Issuing and
        verifying both go through this, so they cannot drift apart.
        """
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def issue_key(self, business_id: str) -> str:
        """
        Generate a new key for business_id, store only its hash, and return
        the plaintext.

        This is the ONLY time the plaintext exists. It is not recoverable
        afterwards -- a caller that loses it must issue a replacement.
        """
        key = KEY_PREFIX + secrets.token_urlsafe(_KEY_ENTROPY_BYTES)
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO api_keys (business_id, key_hash, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(business_id) DO UPDATE SET
                key_hash = excluded.key_hash,
                updated_at = excluded.updated_at
            """,
            (business_id, self.hash_key(key), now),
        )
        conn.commit()
        conn.close()

        return key

    def verify_key(self, business_id: str, presented_key: str | None) -> bool:
        """
        True only if presented_key is the current key for business_id.

        False for every other case -- no key presented, no key on record for
        that business, or a key belonging to a different business. A key
        issued for business-a can never satisfy business-b, because the
        lookup is scoped by business_id before any comparison happens.
        """
        if not presented_key:
            return False

        conn = self._get_connection()
        row = conn.execute(
            "SELECT key_hash FROM api_keys WHERE business_id = ?",
            (business_id,),
        ).fetchone()
        conn.close()

        if row is None:
            return False

        return secrets.compare_digest(
            self.hash_key(presented_key),
            row["key_hash"],
        )

    def has_key(self, business_id: str) -> bool:
        """Whether a key has been issued for business_id. Never used to
        authorize anything -- only for the issuing script's own reporting."""
        conn = self._get_connection()
        row = conn.execute(
            "SELECT 1 FROM api_keys WHERE business_id = ?",
            (business_id,),
        ).fetchone()
        conn.close()

        return row is not None

    def revoke_key(self, business_id: str) -> None:
        conn = self._get_connection()
        conn.execute(
            "DELETE FROM api_keys WHERE business_id = ?",
            (business_id,),
        )
        conn.commit()
        conn.close()
