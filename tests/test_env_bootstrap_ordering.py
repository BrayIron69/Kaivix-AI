"""
Proves the environment is loaded BEFORE any OAuth route handler runs.

Regression coverage for a real bug found during live Gmail verification,
not by any prior test: on a freshly started local server, the OAuth
provider was constructed at import time before load_dotenv() had run
anywhere, so GOOGLE_CLIENT_ID read as None and every
/oauth/google/connect redirect sent `client_id=None` to Google, which
answered "401 invalid_client: The OAuth client was not found". The
server stayed broken for the life of the process, or until some
unrelated code path (the first chat message, which reaches utils/llm.py
-> config) happened to trigger dotenv lazily. See utils/env.py.

Why these tests use a subprocess
--------------------------------
The ordering being asserted happens exactly once per interpreter, at
first import. By the time a normal test runs, the app has long since
been imported and dotenv has already run, so an in-process assertion
would pass whether or not the bug exists. Each test below therefore
starts a fresh interpreter.

The child runs with the repo root as its working directory because the
app resolves several paths relatively (auth/api_keys.db, knowledge/,
config/) and cannot be imported from anywhere else.
"""

import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOTENV_FILE = REPO_ROOT / ".env"

GOOGLE_ENV_KEYS = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PUBLIC_BASE_URL")


def _dotenv_supplies_client_id() -> bool:
    """Whether a local .env exists and actually defines GOOGLE_CLIENT_ID."""
    if not DOTENV_FILE.exists():
        return False
    for line in DOTENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("GOOGLE_CLIENT_ID="):
            return bool(line.split("=", 1)[1].strip())
    return False


def _run_child(program: str, env_overrides: dict | None = None) -> dict:
    """
    Run `program` in a fresh interpreter rooted at the repo, with the
    GOOGLE_* variables stripped from the inherited environment first --
    the parent pytest process has already loaded the real .env into its
    own os.environ, and that would otherwise leak in and make these
    assertions meaningless.
    """
    env = dict(os.environ)
    for key in GOOGLE_ENV_KEYS:
        env.pop(key, None)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.update(env_overrides or {})

    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Child interpreter failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


# Hits the real OAuth route on a freshly imported app and reports what the
# handler actually put in the redirect. Redirects are deliberately not
# followed -- the Location header is the thing under test, and following it
# would mean a real network call to accounts.google.com.
_PROBE_OAUTH_ROUTE = textwrap.dedent(
    """
    import json
    from fastapi.testclient import TestClient
    import api.main

    client = TestClient(api.main.app)
    response = client.get(
        "/oauth/google/connect",
        params={"business_id": "kaivix"},
        follow_redirects=False,
    )
    print(json.dumps({
        "status": response.status_code,
        "location": response.headers.get("location", ""),
    }))
    """
)


class TestBootstrapIsWiredIntoTheOAuthImportPath(unittest.TestCase):
    """
    The always-on structural guard: importing the OAuth router must, by
    itself, have run the env bootstrap -- before any handler can execute.

    This needs no .env and no credentials, so unlike the value-level
    tests below it can never silently skip. It is what catches the
    specific regression of someone removing the `import utils.env` line
    from a provider module as an apparently-unused import.
    """

    def test_importing_the_oauth_router_runs_the_bootstrap_first(self):
        program = textwrap.dedent(
            """
            import json, sys

            before = "utils.env" in sys.modules
            import api.routers.calendar_oauth as oauth
            after = "utils.env" in sys.modules

            print(json.dumps({
                "bootstrap_loaded_before_import": before,
                "bootstrap_loaded_after_import": after,
                "provider_exists": oauth.provider is not None,
            }))
            """
        )
        outcome = _run_child(program)

        self.assertFalse(
            outcome["bootstrap_loaded_before_import"],
            "Precondition failed: utils.env was already imported, so this "
            "test proves nothing about the OAuth import path.",
        )
        self.assertTrue(
            outcome["bootstrap_loaded_after_import"],
            "Importing the OAuth router did not run the environment "
            "bootstrap -- the provider is constructed at import time and "
            "would read its credentials as None.",
        )
        self.assertTrue(outcome["provider_exists"])

    def test_bootstrap_runs_before_the_provider_module_reads_the_environment(self):
        """
        google_calendar_provider.py computes REDIRECT_URI from
        PUBLIC_BASE_URL in its module body, so the bootstrap has to have
        run before that line, not merely before the class is constructed.
        """
        program = textwrap.dedent(
            """
            import json, sys
            import scheduling.google_calendar_provider as gcp

            print(json.dumps({
                "bootstrap_loaded": "utils.env" in sys.modules,
                "redirect_uri": gcp.REDIRECT_URI,
            }))
            """
        )
        outcome = _run_child(program, {"PUBLIC_BASE_URL": "https://example-base.test"})

        self.assertTrue(outcome["bootstrap_loaded"])
        self.assertEqual(
            outcome["redirect_uri"],
            "https://example-base.test/oauth/google/callback",
        )


@unittest.skipUnless(
    _dotenv_supplies_client_id(),
    "No local .env defining GOOGLE_CLIENT_ID; nothing for dotenv to supply.",
)
class TestOAuthRouteSeesDotenvCredentialsOnAFreshServer(unittest.TestCase):
    """
    The value-level proof, against the real .env: a freshly started
    server must build a usable consent URL on its very first request.

    Skips when there is no local .env (the file is gitignored), since
    there would then be nothing for the bootstrap to load -- the
    structural guard above is the always-on protection.
    """

    def test_connect_redirect_carries_a_real_client_id_not_none(self):
        outcome = _run_child(_PROBE_OAUTH_ROUTE)

        self.assertEqual(outcome["status"], 307)
        location = outcome["location"]

        self.assertNotIn(
            "client_id=None", location,
            "The OAuth handler ran before the environment was loaded -- this "
            "is the exact bug that produced Google's 401 invalid_client.",
        )
        self.assertRegex(location, r"client_id=[^&]+\.apps\.googleusercontent\.com")

    def test_gmail_send_scope_is_requested_on_that_same_fresh_server(self):
        """
        The other half of what makes the redirect usable: the consent
        screen must request gmail.send, or a reconnect silently fails to
        grant email sending.
        """
        self.assertIn("gmail.send", _run_child(_PROBE_OAUTH_ROUTE)["location"])


class TestProductionEnvironmentVariablesAlwaysWin(unittest.TestCase):
    """
    The production-safety half of the fix. Render sets real environment
    variables and ships no .env (env files are excluded by
    .dockerignore). load_dotenv() defaults to override=False, so a real
    platform value must survive even when a .env exists beside it -- if
    that ever regressed, the bootstrap could silently replace production
    credentials with stale local ones.

    Valid whether or not a .env is present: with one, this proves the
    override rule; without one, it proves the plain no-op path.
    """

    def test_platform_env_var_is_not_overridden_by_a_dotenv_file(self):
        platform_client_id = "real-platform-client-id.apps.googleusercontent.com"

        outcome = _run_child(
            _PROBE_OAUTH_ROUTE, {"GOOGLE_CLIENT_ID": platform_client_id}
        )

        self.assertIn(f"client_id={platform_client_id}", outcome["location"])

    def test_bootstrap_never_mutates_an_already_set_variable(self):
        """
        Stated directly against os.environ, independent of any route, so
        the guarantee is legible on its own terms.
        """
        program = textwrap.dedent(
            """
            import json, os
            sentinel = os.environ["GOOGLE_CLIENT_ID"]
            import utils.env  # noqa: F401  -- the bootstrap under test
            print(json.dumps({
                "before": sentinel,
                "after": os.environ["GOOGLE_CLIENT_ID"],
            }))
            """
        )
        sentinel = "platform-value-must-survive"
        outcome = _run_child(program, {"GOOGLE_CLIENT_ID": sentinel})

        self.assertEqual(outcome["before"], sentinel)
        self.assertEqual(
            outcome["after"], sentinel,
            "The env bootstrap overwrote a real platform-provided variable.",
        )


if __name__ == "__main__":
    unittest.main()
