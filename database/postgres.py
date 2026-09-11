import os

# Imported for its side effect (load_dotenv at import time), so
# DATABASE_URL is readable regardless of import order -- see utils/env.py.
import utils.env  # noqa: F401

from utils.logger import Logger

ENV_VAR = "DATABASE_URL"


class PostgresNotConfiguredError(RuntimeError):
    """
    Raised when a Postgres-backed store is constructed without
    DATABASE_URL.

    Fatal rather than falling back to SQLite, for the same reason
    crm/registry.py's UnknownCRMProviderError is fatal: silently writing
    a business's leads somewhere other than where its config says is
    worse than refusing to start. A fallback here would also recreate
    the exact failure this whole migration exists to end -- data landing
    on Render's wiped-on-deploy filesystem while everything looks fine.
    """


def is_configured() -> bool:
    """Whether a Postgres connection string is available."""
    return bool((os.getenv(ENV_VAR) or "").strip())


def get_connection():
    """
    A new Postgres connection, with rows returned as dicts.

    dict_row rather than the default tuple row because every existing
    store in this codebase reads columns BY NAME (sqlite3.Row does the
    same), and the admin dashboard, Lead.from_row and the memory stores
    all depend on that. Returning tuples here would make the Postgres
    path silently incompatible with every caller.

    A new connection per call, closed by the caller, matching how
    crm/database.py and every SQLite store here already work. Connection
    pooling is a later concern and not one this traffic level needs;
    Render's free plan also caps connections low enough that a pool
    would need its own care.
    """
    from psycopg import connect
    from psycopg.rows import dict_row

    url = (os.getenv(ENV_VAR) or "").strip()
    if not url:
        raise PostgresNotConfiguredError(
            f"{ENV_VAR} is not set. A Postgres-backed store cannot be used "
            f"without it -- set it to the connection string of the Render "
            f"Postgres instance, or switch the relevant provider back to "
            f"sqlite."
        )

    return connect(url, row_factory=dict_row)


def log_backend_choice(component: str, using_postgres: bool) -> None:
    """
    Record which backend a store actually bound to, at construction.

    Deliberately loud and on both print() and Logger(): Render's Logs
    view is stdout-only, and "which database is this actually writing
    to" is precisely the question nobody thinks to ask until data has
    already gone missing. It went missing here once already.
    """
    backend = "postgres" if using_postgres else "sqlite (EPHEMERAL on Render)"
    line = f"[Storage] {component} -> {backend}"
    print(line)
    Logger().info(line)
