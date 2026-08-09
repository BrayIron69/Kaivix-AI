"""
Tests for api/routers/leads.py's authentication -- it used to have none
at all. GET /leads (list), GET /leads/{email}, POST /leads, PUT
/leads/{email}, and DELETE /leads/{email} all now sit behind the same
require_admin dependency as the /admin dashboard (api/routers/admin.py).

Same runtime-generated-credentials discipline as
test_admin_dashboard.py, so no password-shaped string is ever committed
to the repo, and the same test patterns (401 without credentials, 401
with wrong credentials, 503 when unconfigured) are reused rather than
rewritten.
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


class LeadsRouterTestCase(unittest.TestCase):
    """Temp DB + configured admin credentials, seeded with one lead."""

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

        self.crm.save_lead(
            {
                "name": "Alice Nguyen",
                "email": "alice@example.com",
                "company": "Northwind Labs",
                "budget": "10k-25k",
                "timeline": "this quarter",
                "score": 82,
                "priority": "Hot",
                "status": "Qualified",
            }
        )

    def tearDown(self):
        database.DATABASE_NAME = self._original_db_name

        if os.path.exists(self.db_path):
            os.remove(self.db_path)


class TestLeadsRouterAuth(LeadsRouterTestCase):
    def test_list_returns_401_without_credentials(self):
        response = self.client.get("/leads")

        self.assertEqual(response.status_code, 401)

    def test_list_401_carries_basic_auth_challenge_header(self):
        response = self.client.get("/leads")

        self.assertEqual(
            response.headers.get("www-authenticate", "").lower(),
            "basic",
        )

    def test_list_returns_401_with_wrong_password(self):
        response = self.client.get(
            "/leads",
            auth=(TEST_USERNAME, TEST_PASSWORD + "-wrong"),
        )

        self.assertEqual(response.status_code, 401)

    def test_list_returns_401_with_wrong_username(self):
        response = self.client.get(
            "/leads",
            auth=("not-" + TEST_USERNAME, TEST_PASSWORD),
        )

        self.assertEqual(response.status_code, 401)

    def test_detail_returns_401_without_credentials(self):
        response = self.client.get("/leads/alice@example.com")

        self.assertEqual(response.status_code, 401)

    def test_create_returns_401_without_credentials(self):
        response = self.client.post(
            "/leads",
            json={"email": "new@example.com", "name": "New Lead"},
        )

        self.assertEqual(response.status_code, 401)

    def test_update_returns_401_without_credentials(self):
        response = self.client.put(
            "/leads/alice@example.com",
            json={"name": "Renamed"},
        )

        self.assertEqual(response.status_code, 401)

    def test_delete_returns_401_without_credentials(self):
        response = self.client.delete("/leads/alice@example.com")

        self.assertEqual(response.status_code, 401)

    def test_no_lead_data_leaks_in_an_unauthenticated_list_response(self):
        response = self.client.get("/leads")

        self.assertNotIn("Alice Nguyen", response.text)
        self.assertNotIn("alice@example.com", response.text)

    def test_no_write_side_effect_happens_without_credentials(self):
        """
        The 401 must be enforced before create_lead()'s body runs -- not
        just hide the response while still writing the record.
        """
        self.client.post(
            "/leads",
            json={"email": "sneaky@example.com", "name": "Should Not Exist"},
        )

        self.assertIsNone(self.crm.get_lead_by_email("sneaky@example.com"))


class TestLeadsRouterUnconfiguredCredentials(LeadsRouterTestCase):
    """
    With ADMIN_USERNAME/ADMIN_PASSWORD unset, every route must fail
    loudly (503) -- never fall back to an open or guessable default.
    Mirrors TestAdminUnconfiguredCredentials in test_admin_dashboard.py.
    """

    def setUp(self):
        super().setUp()

        env = patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)

        os.environ.pop("ADMIN_USERNAME", None)
        os.environ.pop("ADMIN_PASSWORD", None)

    def test_valid_looking_credentials_are_rejected_when_unconfigured(self):
        response = self.client.get("/leads", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Alice Nguyen", response.text)

    def test_empty_credentials_are_rejected_when_unconfigured(self):
        response = self.client.get("/leads", auth=("", ""))

        self.assertEqual(response.status_code, 503)

    def test_detail_rejected_when_unconfigured(self):
        response = self.client.get(
            "/leads/alice@example.com",
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Northwind Labs", response.text)

    def test_create_rejected_when_unconfigured(self):
        response = self.client.post(
            "/leads",
            json={"email": "new@example.com"},
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 503)

    def test_username_only_is_not_enough(self):
        os.environ["ADMIN_USERNAME"] = TEST_USERNAME

        response = self.client.get("/leads", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 503)

    def test_password_only_is_not_enough(self):
        os.environ["ADMIN_PASSWORD"] = TEST_PASSWORD

        response = self.client.get("/leads", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 503)


class TestLeadsRouterWithValidCredentials(LeadsRouterTestCase):
    """
    Confirms the router still works end-to-end once authenticated --
    this fix must not break legitimate, credentialed access.
    """

    def test_list_returns_200_with_seeded_lead(self):
        response = self.client.get("/leads", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 200)
        emails = [lead["email"] for lead in response.json()]
        self.assertIn("alice@example.com", emails)

    def test_detail_returns_200_for_known_email(self):
        response = self.client.get("/leads/alice@example.com", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "alice@example.com")

    def test_detail_returns_404_for_unknown_email(self):
        response = self.client.get("/leads/nobody@example.com", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 404)

    def test_create_returns_201_and_persists(self):
        response = self.client.post(
            "/leads",
            json={"email": "new@example.com", "name": "New Lead"},
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(self.crm.get_lead_by_email("new@example.com"))

    def test_create_rejects_malformed_email(self):
        """
        LeadCreate.email is a pydantic EmailStr -- format is already
        validated before create_lead()'s body runs, same as the
        internal ConversationEngine -> LeadService.save() path expects
        a real address. A manually-callable creation endpoint has more
        abuse surface than internal-only capture, so this is worth
        pinning explicitly rather than assuming pydantic's default wins.
        """
        response = self.client.post(
            "/leads",
            json={"email": "not-an-email", "name": "Bad Email"},
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 422)
        self.assertIsNone(self.crm.get_lead_by_email("not-an-email"))

    def test_update_returns_200_and_persists_change(self):
        response = self.client.put(
            "/leads/alice@example.com",
            json={"name": "Alice Renamed"},
            auth=GOOD_AUTH,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.crm.get_lead_by_email("alice@example.com").name,
            "Alice Renamed",
        )

    def test_delete_returns_200_and_removes_record(self):
        response = self.client.delete("/leads/alice@example.com", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.crm.get_lead_by_email("alice@example.com"))


class TestLeadsRouterBusinessScoping(LeadsRouterTestCase):
    """
    Both api/routers/leads.py and api/routers/admin.py call LeadService
    with no business_id argument, so both implicitly resolve to
    LeadService's default (core_ai.business_config.DEFAULT_BUSINESS_ID,
    "kaivix") -- the same single-tenant scope, not two differently
    -scoped paths to the same data. This pins that equivalence rather
    than just asserting it in review: a lead saved for a different
    business_id is invisible through /leads, exactly like /admin.
    """

    def test_list_only_returns_default_business_leads(self):
        self.crm.save_lead(
            {"name": "Other Tenant Lead", "email": "other@example.com"},
            business_id="some-other-business",
        )

        response = self.client.get("/leads", auth=GOOD_AUTH)
        emails = [lead["email"] for lead in response.json()]

        self.assertIn("alice@example.com", emails)
        self.assertNotIn("other@example.com", emails)

    def test_detail_404s_for_a_lead_under_a_different_business_id(self):
        self.crm.save_lead(
            {"name": "Other Tenant Lead", "email": "other@example.com"},
            business_id="some-other-business",
        )

        response = self.client.get("/leads/other@example.com", auth=GOOD_AUTH)

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
