"""
Tests for the Basic-Auth-protected admin lead dashboard
(api/routers/admin.py).

The credentials used here are generated at runtime, so no
password-shaped string is ever committed to the repo.
"""

import os
import secrets
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import crm.database as database
from api.main import app
from crm.sqlite_crm import SQLiteCRM


TEST_USERNAME = "admin-" + secrets.token_hex(4)
TEST_PASSWORD = secrets.token_urlsafe(24)

GOOD_AUTH = (TEST_USERNAME, TEST_PASSWORD)


class AdminDashboardTestCase(unittest.TestCase):
    """Temp DB + configured admin credentials, seeded with two leads."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)

        self._original_db_name = database.DATABASE_NAME
        database.DATABASE_NAME = self.db_path

        self.crm = SQLiteCRM()
        self.client = TestClient(app)

        env = patch.dict(
            os.environ,
            {
                "ADMIN_USERNAME": TEST_USERNAME,
                "ADMIN_PASSWORD": TEST_PASSWORD,
            },
        )
        env.start()
        self.addCleanup(env.stop)

        self._seed_leads()

    def tearDown(self):
        database.DATABASE_NAME = self._original_db_name

        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _seed_leads(self):
        self.crm.save_lead(
            {
                "name": "Alice Nguyen",
                "email": "alice@example.com",
                "company": "Northwind Labs",
                "phone": "555-0101",
                "industry": "Logistics software",
                "budget": "10k-25k",
                "timeline": "this quarter",
                "pain_point": "manual lead follow-up",
                "decision_maker": "yes",
                "score": 82,
                "priority": "Hot",
                "status": "Qualified",
                "notes": "Asked for a proposal.",
            }
        )
        self.crm.save_lead(
            {
                "name": "Bob Ortiz",
                "email": "bob@example.com",
                "company": "Cobalt Freight",
                "budget": "under 5k",
                "timeline": "next year",
                "score": 24,
                "priority": "Cold",
            }
        )

        # created_at defaults to CURRENT_TIMESTAMP, so both rows land in the
        # same second and "most recent first" would be untestable. Pin them.
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE leads SET created_at = ? WHERE email = ?",
            ("2026-07-01 09:00:00", "bob@example.com"),
        )
        cursor.execute(
            "UPDATE leads SET created_at = ? WHERE email = ?",
            ("2026-07-20 09:00:00", "alice@example.com"),
        )
        conn.commit()
        conn.close()


class TestAdminAuth(AdminDashboardTestCase):
    def test_dashboard_returns_401_without_credentials(self):
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 401)

    def test_401_carries_basic_auth_challenge_header(self):
        response = self.client.get("/admin")

        self.assertEqual(
            response.headers.get("www-authenticate", "").lower(),
            "basic",
        )

    def test_dashboard_returns_401_with_wrong_password(self):
        response = self.client.get(
            "/admin",
            auth=(TEST_USERNAME, TEST_PASSWORD + "-wrong"),
        )

        self.assertEqual(response.status_code, 401)

    def test_dashboard_returns_401_with_wrong_username(self):
        response = self.client.get(
            "/admin",
            auth=("not-" + TEST_USERNAME, TEST_PASSWORD),
        )

        self.assertEqual(response.status_code, 401)

    def test_detail_view_returns_401_without_credentials(self):
        response = self.client.get("/admin/leads/alice@example.com")

        self.assertEqual(response.status_code, 401)

    def test_no_lead_data_leaks_in_an_unauthenticated_response(self):
        response = self.client.get("/admin")

        self.assertNotIn("Alice Nguyen", response.text)
        self.assertNotIn("alice@example.com", response.text)


class TestAdminUnconfiguredCredentials(AdminDashboardTestCase):
    """
    With ADMIN_USERNAME/ADMIN_PASSWORD unset the dashboard must fail
    loudly -- never fall back to an open or guessable default.
    """

    def setUp(self):
        super().setUp()

        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)

        os.environ.pop("ADMIN_USERNAME", None)
        os.environ.pop("ADMIN_PASSWORD", None)

    def test_valid_looking_credentials_are_rejected_when_unconfigured(self):
        response = self.client.get("/admin", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Alice Nguyen", response.text)

    def test_empty_credentials_are_rejected_when_unconfigured(self):
        response = self.client.get("/admin", auth=("", ""))

        self.assertEqual(response.status_code, 503)

    def test_detail_view_rejected_when_unconfigured(self):
        response = self.client.get(
            "/admin/leads/alice@example.com",
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Northwind Labs", response.text)

    def test_username_only_is_not_enough(self):
        os.environ["ADMIN_USERNAME"] = TEST_USERNAME

        response = self.client.get("/admin", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 503)

    def test_password_only_is_not_enough(self):
        os.environ["ADMIN_PASSWORD"] = TEST_PASSWORD

        response = self.client.get("/admin", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 503)


class TestAdminLeadList(AdminDashboardTestCase):
    def test_returns_200_html_with_valid_credentials(self):
        response = self.client.get("/admin", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_lists_every_lead_with_the_required_columns(self):
        response = self.client.get("/admin", auth=GOOD_AUTH)
        body = response.text

        for expected in [
            "Alice Nguyen",
            "alice@example.com",
            "Northwind Labs",
            "10k-25k",
            "this quarter",
            "82",
            "Hot",
            "2026-07-20",
            "Bob Ortiz",
            "bob@example.com",
            "Cobalt Freight",
            "under 5k",
            "next year",
            "24",
            "Cold",
        ]:
            self.assertIn(expected, body, f"missing {expected!r} in /admin")

    def test_leads_are_sorted_most_recent_first(self):
        body = self.client.get("/admin", auth=GOOD_AUTH).text

        self.assertLess(
            body.index("Alice Nguyen"),
            body.index("Bob Ortiz"),
        )

    def test_each_row_links_to_its_detail_view(self):
        body = self.client.get("/admin", auth=GOOD_AUTH).text

        self.assertIn("/admin/leads/alice%40example.com", body)
        self.assertIn("/admin/leads/bob%40example.com", body)

    def test_renders_search_box_and_sortable_headers(self):
        body = self.client.get("/admin", auth=GOOD_AUTH).text

        self.assertIn('id="search"', body)
        self.assertIn('data-index="0"', body)
        self.assertIn("data-search=", body)

    def test_empty_database_renders_an_empty_state(self):
        self.crm.delete_lead("alice@example.com")
        self.crm.delete_lead("bob@example.com")

        response = self.client.get("/admin", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 200)
        self.assertIn("No leads captured yet.", response.text)

    def test_lead_values_are_html_escaped(self):
        self.crm.save_lead(
            {
                "name": "<script>alert(1)</script>",
                "email": "xss@example.com",
                "company": "Evil & Co",
            }
        )

        body = self.client.get("/admin", auth=GOOD_AUTH).text

        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertIn("Evil &amp; Co", body)


class TestAdminLeadDetail(AdminDashboardTestCase):
    def test_returns_200_html_with_valid_credentials(self):
        response = self.client.get(
            "/admin/leads/alice@example.com",
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_shows_every_captured_field(self):
        body = self.client.get(
            "/admin/leads/alice@example.com",
            auth=GOOD_AUTH,
        ).text

        for expected in [
            "Alice Nguyen",
            "alice@example.com",
            "555-0101",
            "Northwind Labs",
            "Logistics software",
            "10k-25k",
            "this quarter",
            "manual lead follow-up",
            "Qualified",
            "Asked for a proposal.",
            "82",
            "Hot",
            "2026-07-20",
            "kaivix",
        ]:
            self.assertIn(expected, body, f"missing {expected!r} in detail view")

    def test_does_not_show_a_different_lead(self):
        body = self.client.get(
            "/admin/leads/alice@example.com",
            auth=GOOD_AUTH,
        ).text

        self.assertNotIn("Cobalt Freight", body)

    def test_unknown_email_returns_404(self):
        response = self.client.get(
            "/admin/leads/nobody@example.com",
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 404)

    def test_url_encoded_email_resolves(self):
        response = self.client.get(
            "/admin/leads/alice%40example.com",
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Alice Nguyen", response.text)


if __name__ == "__main__":
    unittest.main()
