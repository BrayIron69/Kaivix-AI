#!/usr/bin/env python
"""
Issue (or rotate) the API key a business needs to call
POST /chat/{business_id}.

A script rather than an admin-dashboard screen, deliberately. Every
configured business today is our own, and there is exactly one of them, so a
management UI would be scaffolding for a problem that does not exist yet --
and a browser-reachable "mint a credential" button is a larger attack
surface than a command that requires shell access to the host. When a real
second business exists and keys need handing out routinely, that is the
point to reconsider.

Prints the key ONCE. Only its SHA-256 hash is stored, so there is no way to
recover it afterwards -- if it is lost, run this again to replace it.

Run from the repo root:
    python scripts/issue_api_key.py <business_id>
    python scripts/issue_api_key.py kaivix

Re-running for a business that already has a key REPLACES it: the old key
stops working immediately. That is how rotation works here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the repo root importable regardless of how this script is invoked
# (direct execution puts only scripts/ on sys.path by default) -- same
# preamble as evals/run_conversation_evals.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from auth.api_key_store import APIKeyStore  # noqa: E402
from core_ai.business_config import (  # noqa: E402
    BusinessConfigError,
    BusinessConfigRepository,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Issue or rotate the API key for a business's "
            "/chat/{business_id} endpoint."
        )
    )
    parser.add_argument(
        "business_id",
        help="The business_id, matching config/businesses/<business_id>/.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Issue a key even if the business_id has no valid config. Only "
            "useful for provisioning ahead of the config being written."
        ),
    )
    args = parser.parse_args()

    business_id = args.business_id

    # Refuse a typo'd business_id by default: a key issued for
    # "kaivx" would be silently useless, since the route resolves config by
    # the same id it authenticates.
    if not args.force:
        try:
            BusinessConfigRepository().load(business_id)
        except BusinessConfigError as error:
            print(
                f"No valid config for business_id={business_id!r}:\n"
                f"  {error}\n"
                f"Check the spelling against config/businesses/, or pass "
                f"--force to issue anyway.",
                file=sys.stderr,
            )
            return 2

    store = APIKeyStore()
    rotating = store.has_key(business_id)

    key = store.issue_key(business_id)

    action = "Rotated" if rotating else "Issued"
    print(f"{action} API key for business_id={business_id!r}.")
    if rotating:
        print("The previous key for this business no longer works.")
    print()
    print("  Store this now -- it is not recoverable:")
    print()
    print(f"    {key}")
    print()
    print("  Send it as a header on POST /chat/{business_id}:")
    print()
    print(f"    X-API-Key: {key}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
