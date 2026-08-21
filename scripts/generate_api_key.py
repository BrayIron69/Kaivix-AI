#!/usr/bin/env python
"""
Generate the API key a business needs to call POST /chat/{business_id}
and POST /voice/{business_id}/chat/completions.

THIS SCRIPT WRITES NOTHING. That is the whole point of the change it
belongs to. Its predecessor (scripts/issue_api_key.py) wrote to a local
SQLite database that is excluded from both the repo and the production
image, on a host with no persistent disk -- so a key it "issued" existed
only on the machine that ran it, and production could never hold one. See
auth/business_api_keys.py for the full reasoning.

The real issuing process is now a manual step on Render, the same one
already used for every other production secret (ADMIN_PASSWORD,
GROQ_API_KEY, GOOGLE_CLIENT_SECRET):

    1. Run this script.
    2. Copy the BUSINESS_API_KEYS value it prints into Render ->
       Environment -> Environment Variables. If the variable already
       exists, MERGE the new entry into the existing JSON rather than
       replacing it, or every other business's key stops working -- pass
       --merge-with to have this script do that correctly for you.
    3. Redeploy (or let the env-var save trigger one) so the new value is
       live.
    4. Give the KEY (not the hash) to whoever calls the endpoint -- for
       voice, that is the Vapi assistant's custom-LLM header config.

The key is printed ONCE and stored nowhere, by design: only its SHA-256
hash goes into the environment variable, so there is no way to recover it
afterwards. If it is lost, run this again to replace it.

Run from the repo root:
    python scripts/generate_api_key.py <business_id>
    python scripts/generate_api_key.py kaivix
    python scripts/generate_api_key.py acme --merge-with '{"kaivix":"<hash>"}'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the repo root importable regardless of how this script is invoked
# (direct execution puts only scripts/ on sys.path by default) -- same
# preamble as evals/run_conversation_evals.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from auth.business_api_keys import (  # noqa: E402
    ENV_VAR,
    generate_key,
    hash_key,
)
from core_ai.business_config import (  # noqa: E402
    BusinessConfigError,
    BusinessConfigRepository,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate an API key for a business's authenticated endpoints, "
            "and print the environment-variable value to set on the host."
        )
    )
    parser.add_argument(
        "business_id",
        help="The business_id, matching config/businesses/<business_id>/.",
    )
    parser.add_argument(
        "--merge-with",
        metavar="JSON",
        default=None,
        help=(
            "The CURRENT value of "
            + ENV_VAR
            + ", so the new entry is merged into it instead of replacing "
            "every other business's key. Paste what the host already has."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Generate even if the business_id has no valid config. Only "
            "useful for provisioning ahead of the config being written."
        ),
    )
    args = parser.parse_args()

    business_id = args.business_id

    # Refuse a typo'd business_id by default: a key generated for
    # "kaivx" would be silently useless, since the route resolves config
    # by the same id it authenticates.
    if not args.force:
        try:
            BusinessConfigRepository().load(business_id)
        except BusinessConfigError as error:
            print(
                f"No valid config for business_id={business_id!r}:\n"
                f"  {error}\n"
                f"Check the spelling against config/businesses/, or pass "
                f"--force to generate anyway.",
                file=sys.stderr,
            )
            return 2

    existing: dict[str, str] = {}
    if args.merge_with:
        try:
            parsed = json.loads(args.merge_with)
        except json.JSONDecodeError as error:
            print(f"--merge-with is not valid JSON: {error}", file=sys.stderr)
            return 2
        if not isinstance(parsed, dict):
            print("--merge-with must be a JSON object.", file=sys.stderr)
            return 2
        existing = {str(k): str(v) for k, v in parsed.items()}

    rotating = business_id in existing

    key = generate_key()
    existing[business_id] = hash_key(key)

    # Compact separators so the value pastes into a dashboard field as one
    # line with no stray whitespace. Sorted so the same set of businesses
    # always renders identically, which makes a diff between two values
    # readable.
    env_value = json.dumps(existing, separators=(",", ":"), sort_keys=True)

    action = "Rotated" if rotating else "Generated"
    print(f"{action} API key for business_id={business_id!r}.")
    if rotating:
        print("The previous key for this business will stop working once "
              "the new value below is live.")
    if not args.merge_with:
        print()
        print("  NOTE: no --merge-with given, so the value below contains "
              "ONLY this business.")
        print("  If the host already has other businesses configured, "
              "re-run with --merge-with")
        print("  set to the current value, or their keys will be wiped.")
    print()
    print("  1. Give this KEY to the caller (Vapi header, integration "
          "config). Not recoverable:")
    print()
    print(f"     {key}")
    print()
    print(f"  2. Set this on the host (Render -> Environment). This is the "
          f"HASH, not the key:")
    print()
    print(f"     {ENV_VAR}={env_value}")
    print()
    print("  3. Redeploy so the new value is live.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
