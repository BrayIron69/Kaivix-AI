"""
CORS origin policy (api/main.py).

Was allow_origins=["*"] with allow_credentials=True, so Starlette echoed
back any Origin header it was given -- every site on the internet was an
allowed origin. These tests pin the allowlist to the two real ones.
"""

import unittest

from fastapi.testclient import TestClient

from api.main import ALLOWED_ORIGINS, app


DISALLOWED_ORIGINS = [
    "https://evil.example.com",
    "http://kaivixlab.com",           # wrong scheme
    "http://www.kaivixlab.com",       # wrong scheme
    "https://kaivixlab.com.evil.io",  # suffix attack
    "https://sub.kaivixlab.com",      # a subdomain, but not www
    "null",
]


class TestCorsAllowlist(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_allowlist_is_the_three_known_origins(self):
        self.assertEqual(
            ALLOWED_ORIGINS,
            [
                "https://kaivixlab.com",
                "https://www.kaivixlab.com",
                "https://kaivix-ai.onrender.com",
            ],
        )

    def test_www_marketing_origin_is_allowed(self):
        """
        The marketing site is served from www (the apex 308-redirects to
        it), so www is the Origin real visitors' browsers send. Omitting
        it silently breaks the embedded chat widget for everyone --
        preflight is rejected and fetch fails in the browser with no
        server-side error to notice.
        """
        response = self.client.get(
            "/health", headers={"Origin": "https://www.kaivixlab.com"}
        )

        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://www.kaivixlab.com",
        )

    def test_chat_endpoint_preflight_succeeds_from_the_www_widget_origin(self):
        """End-to-end shape of the actual widget call: chat_widget.html
        POSTs JSON to /chat from the marketing site."""
        response = self.client.options(
            "/chat",
            headers={
                "Origin": "https://www.kaivixlab.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://www.kaivixlab.com",
        )

    def test_www_is_allowed_by_exact_match_not_subdomain_wildcard(self):
        """www being allowed must not mean *.kaivixlab.com is allowed."""
        response = self.client.get(
            "/health", headers={"Origin": "https://sub.kaivixlab.com"}
        )

        self.assertIsNone(response.headers.get("access-control-allow-origin"))

    def test_allowed_origins_get_a_matching_allow_origin_header(self):
        for origin in ALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                response = self.client.get("/health", headers={"Origin": origin})

                self.assertEqual(
                    response.headers.get("access-control-allow-origin"),
                    origin,
                )

    def test_disallowed_origins_get_no_allow_origin_header(self):
        for origin in DISALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                response = self.client.get("/health", headers={"Origin": origin})

                self.assertIsNone(
                    response.headers.get("access-control-allow-origin"),
                    f"{origin} was granted CORS access",
                )

    def test_wildcard_is_never_returned(self):
        for origin in ALLOWED_ORIGINS + DISALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                response = self.client.get("/health", headers={"Origin": origin})

                self.assertNotEqual(
                    response.headers.get("access-control-allow-origin"),
                    "*",
                )


class TestCorsPreflight(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _preflight(self, origin):
        return self.client.options(
            "/chat",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    def test_allowed_origin_preflight_succeeds(self):
        for origin in ALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                response = self._preflight(origin)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers.get("access-control-allow-origin"),
                    origin,
                )

    def test_disallowed_origin_preflight_is_rejected(self):
        for origin in DISALLOWED_ORIGINS:
            with self.subTest(origin=origin):
                response = self._preflight(origin)

                self.assertIsNone(
                    response.headers.get("access-control-allow-origin"),
                    f"{origin} was granted a CORS preflight",
                )

    def test_same_origin_requests_are_unaffected(self):
        """No Origin header at all -- server-to-server and same-origin
        callers must not be touched by the allowlist."""
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
