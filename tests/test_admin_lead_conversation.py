"""
Admin dashboard: real conversation transcript on the lead detail view,
and deletion that removes BOTH the CRM record and the stored
conversation.

Same runtime-generated credentials pattern as
tests/test_admin_dashboard.py -- no password-shaped string is ever
committed. Both databases (crm/leads.db and
memory/conversation_memory.db) are redirected to temp files, so nothing
here touches real data.
"""

import os
import secrets
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

from fastapi.testclient import TestClient

import crm.database as database
from api.main import app
from crm.sqlite_crm import SQLiteCRM
from memory.conversation_memory import ConversationMemory
from memory.conversation_store import SQLiteConversationStore

TEST_USERNAME = "admin-" + secrets.token_hex(4)
TEST_PASSWORD = secrets.token_urlsafe(24)
GOOD_AUTH = (TEST_USERNAME, TEST_PASSWORD)

LEAD_EMAIL = "transcript@example.com"
CONVERSATION_ID = "session_abc123"
OTHER_BUSINESS = "other-co"


class _AdminConversationTestCase(unittest.TestCase):
    def setUp(self):
        # --- CRM database ---
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        self._original_db_name = database.DATABASE_NAME
        database.DATABASE_NAME = self.db_path
        self.addCleanup(self._restore_crm_db)

        # --- conversation store database ---
        fd, self.conversation_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.conversation_db_path)
        self._original_conversation_db = SQLiteConversationStore.DB_PATH
        SQLiteConversationStore.DB_PATH = self.conversation_db_path
        self.addCleanup(self._restore_conversation_db)

        self.crm = SQLiteCRM()
        self.client = TestClient(app)

        env = patch.dict(
            os.environ,
            {"ADMIN_USERNAME": TEST_USERNAME, "ADMIN_PASSWORD": TEST_PASSWORD},
        )
        env.start()
        self.addCleanup(env.stop)

    def _restore_crm_db(self):
        database.DATABASE_NAME = self._original_db_name
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _restore_conversation_db(self):
        SQLiteConversationStore.DB_PATH = self._original_conversation_db
        if os.path.exists(self.conversation_db_path):
            os.remove(self.conversation_db_path)

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def _seed_lead(self, email=LEAD_EMAIL, conversation_id=CONVERSATION_ID,
                   business_id="kaivix", name="Transcript Tester"):
        self.crm.save_lead(
            {
                "name": name,
                "email": email,
                "conversation_id": conversation_id,
                "score": 0,
                "priority": "Cold",
                "status": "New",
            },
            business_id=business_id,
        )

    def _seed_conversation(self, conversation_id=CONVERSATION_ID,
                           business_id="kaivix", messages=None):
        memory = ConversationMemory(business_id=business_id)
        for role, content in messages or []:
            if role == "user":
                memory.add_user_message(conversation_id, content)
            else:
                memory.add_assistant_message(conversation_id, content)
        return memory

    def _detail(self, email=LEAD_EMAIL, auth=GOOD_AUTH):
        return self.client.get(f"/admin/leads/{email}", auth=auth)


class TestTranscriptDisplay(_AdminConversationTestCase):
    def test_real_transcript_is_shown_on_the_lead_detail_view(self):
        self._seed_lead()
        self._seed_conversation(
            messages=[
                ("user", "do you integrate with HubSpot?"),
                ("assistant", "Yes, we do. What are you using it for today?"),
                ("user", "lead routing mostly"),
            ]
        )

        response = self._detail()
        self.assertEqual(response.status_code, 200)
        body = response.text

        # Real message content, in order.
        self.assertIn("do you integrate with HubSpot?", body)
        self.assertIn("Yes, we do. What are you using it for today?", body)
        self.assertIn("lead routing mostly", body)
        self.assertLess(
            body.index("do you integrate with HubSpot?"),
            body.index("lead routing mostly"),
            "Transcript must render oldest message first.",
        )

        # Speakers are labelled in the dashboard's own vocabulary.
        self.assertIn("Visitor", body)
        self.assertIn("Bray", body)
        self.assertIn("3 messages", body)

    def test_lead_with_no_conversation_id_says_so_instead_of_failing(self):
        self._seed_lead(conversation_id=None)

        response = self._detail()

        self.assertEqual(response.status_code, 200)
        self.assertIn("No conversation is linked to this lead", response.text)

    def test_conversation_id_present_but_no_stored_messages(self):
        self._seed_lead()  # conversation_id set, but nothing stored for it

        response = self._detail()

        self.assertEqual(response.status_code, 200)
        self.assertIn("No stored messages", response.text)
        self.assertIn(CONVERSATION_ID, response.text)

    def test_visitor_text_is_html_escaped(self):
        """
        Transcript content is raw visitor input. Rendering it unescaped
        into the admin page would be stored XSS against the one user who
        can see every lead.
        """
        self._seed_lead()
        self._seed_conversation(
            messages=[("user", "<script>alert('xss')</script>")]
        )

        body = self._detail().text

        self.assertNotIn("<script>alert('xss')</script>", body)
        self.assertIn("&lt;script&gt;", body)


class TestTranscriptScoping(_AdminConversationTestCase):
    def test_transcript_is_scoped_to_the_leads_own_business(self):
        """
        conversation_ids are generated client-side ('session_' + random in
        chat_widget.html) and are not globally unique, so an identical id
        under a different business must never surface on this lead.
        """
        self._seed_lead(business_id="kaivix")
        self._seed_conversation(
            business_id="kaivix",
            messages=[("user", "KAIVIX-TENANT-MESSAGE")],
        )
        # Same conversation_id, different tenant, different content.
        self._seed_conversation(
            business_id=OTHER_BUSINESS,
            messages=[("user", "OTHER-TENANT-SECRET")],
        )

        body = self._detail().text

        self.assertIn("KAIVIX-TENANT-MESSAGE", body)
        self.assertNotIn(
            "OTHER-TENANT-SECRET", body,
            "Another business's conversation leaked onto this lead's page.",
        )

    def test_transcript_is_scoped_to_the_right_conversation(self):
        self._seed_lead(conversation_id="session_wanted")
        self._seed_conversation(
            conversation_id="session_wanted",
            messages=[("user", "WANTED-CONVERSATION")],
        )
        self._seed_conversation(
            conversation_id="session_unwanted",
            messages=[("user", "UNWANTED-CONVERSATION")],
        )

        body = self._detail().text

        self.assertIn("WANTED-CONVERSATION", body)
        self.assertNotIn("UNWANTED-CONVERSATION", body)


class TestDeleteRemovesBoth(_AdminConversationTestCase):
    def _delete(self, email=LEAD_EMAIL, auth=GOOD_AUTH):
        return self.client.post(
            f"/admin/leads/{email}/delete", auth=auth, follow_redirects=False
        )

    def test_delete_removes_the_crm_record_and_the_conversation(self):
        self._seed_lead()
        self._seed_conversation(
            messages=[("user", "please delete my data"), ("assistant", "Understood.")]
        )

        # Both exist first -- otherwise the assertions below prove nothing.
        self.assertIsNotNone(self.crm.get_lead_by_email(LEAD_EMAIL, business_id="kaivix"))
        self.assertEqual(
            len(ConversationMemory(business_id="kaivix").get_conversation(CONVERSATION_ID)),
            2,
        )

        response = self._delete()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin")

        self.assertIsNone(
            self.crm.get_lead_by_email(LEAD_EMAIL, business_id="kaivix"),
            "CRM lead record survived the delete.",
        )
        self.assertEqual(
            ConversationMemory(business_id="kaivix").get_conversation(CONVERSATION_ID),
            [],
            "Stored conversation survived the delete -- the visitor's own "
            "words are still on disk with nothing pointing at them.",
        )

    def test_delete_does_not_touch_another_businesss_conversation(self):
        self._seed_lead(business_id="kaivix")
        self._seed_conversation(
            business_id="kaivix", messages=[("user", "mine")]
        )
        self._seed_conversation(
            business_id=OTHER_BUSINESS, messages=[("user", "not yours to delete")]
        )

        self._delete()

        self.assertEqual(
            ConversationMemory(business_id=OTHER_BUSINESS).get_conversation(CONVERSATION_ID),
            [{"role": "user", "content": "not yours to delete"}],
            "Deleting one business's lead deleted another business's "
            "conversation with a colliding conversation_id.",
        )

    def test_delete_does_not_touch_other_leads(self):
        self._seed_lead()
        self._seed_lead(email="keepme@example.com", conversation_id="session_keep")
        self._seed_conversation(
            conversation_id="session_keep", messages=[("user", "keep this")]
        )

        self._delete()

        self.assertIsNotNone(
            self.crm.get_lead_by_email("keepme@example.com", business_id="kaivix")
        )
        self.assertEqual(
            len(ConversationMemory(business_id="kaivix").get_conversation("session_keep")),
            1,
        )

    def test_deleting_a_lead_with_no_conversation_still_removes_the_lead(self):
        self._seed_lead(conversation_id=None)

        response = self._delete()

        self.assertEqual(response.status_code, 303)
        self.assertIsNone(self.crm.get_lead_by_email(LEAD_EMAIL, business_id="kaivix"))

    def test_deleting_an_unknown_lead_is_404(self):
        response = self._delete(email="nobody@example.com")

        self.assertEqual(response.status_code, 404)

    def test_detail_page_offers_delete_as_a_post_not_a_link(self):
        """
        A GET-triggered destructive action is reachable by prefetching,
        crawling, or simply pasting a URL.
        """
        self._seed_lead()

        body = self._detail().text

        self.assertIn('method="post"', body)
        # The email is URL-encoded in the action ("@" -> "%40"), since it
        # is a path segment built with quote(safe="").
        self.assertIn(
            "/admin/leads/" + quote(LEAD_EMAIL, safe="") + "/delete", body
        )
        self.assertNotIn(
            f'href="/admin/leads/{LEAD_EMAIL}/delete"', body,
            "Delete must not also be exposed as a plain GET link.",
        )


class TestConversationRoutesRequireAdminAuth(_AdminConversationTestCase):
    """
    2c: this is real customer data -- confirm the existing admin
    credential actually protects it, rather than assuming the router
    dependency applies.
    """

    def test_transcript_view_rejects_missing_credentials(self):
        self._seed_lead()
        self._seed_conversation(messages=[("user", "SENSITIVE-VISITOR-TEXT")])

        response = self.client.get(f"/admin/leads/{LEAD_EMAIL}")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("SENSITIVE-VISITOR-TEXT", response.text)

    def test_transcript_view_rejects_wrong_credentials(self):
        self._seed_lead()
        self._seed_conversation(messages=[("user", "SENSITIVE-VISITOR-TEXT")])

        response = self._detail(auth=(TEST_USERNAME, "wrong-" + TEST_PASSWORD))

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("SENSITIVE-VISITOR-TEXT", response.text)

    def test_delete_rejects_missing_credentials_and_deletes_nothing(self):
        self._seed_lead()
        self._seed_conversation(messages=[("user", "still here")])

        response = self.client.post(
            f"/admin/leads/{LEAD_EMAIL}/delete", follow_redirects=False
        )

        self.assertEqual(response.status_code, 401)
        self.assertIsNotNone(
            self.crm.get_lead_by_email(LEAD_EMAIL, business_id="kaivix"),
            "An unauthenticated request deleted a lead.",
        )
        self.assertEqual(
            len(ConversationMemory(business_id="kaivix").get_conversation(CONVERSATION_ID)),
            1,
            "An unauthenticated request deleted a stored conversation.",
        )

    def test_delete_rejects_wrong_credentials_and_deletes_nothing(self):
        self._seed_lead()
        self._seed_conversation(messages=[("user", "still here")])

        response = self.client.post(
            f"/admin/leads/{LEAD_EMAIL}/delete",
            auth=(TEST_USERNAME, "wrong-" + TEST_PASSWORD),
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 401)
        self.assertIsNotNone(
            self.crm.get_lead_by_email(LEAD_EMAIL, business_id="kaivix")
        )

    def test_delete_is_closed_when_admin_credentials_are_unconfigured(self):
        """Unconfigured means closed, never open -- same stance as the
        rest of the dashboard."""
        self._seed_lead()

        with patch.dict(os.environ):
            os.environ.pop("ADMIN_USERNAME", None)
            os.environ.pop("ADMIN_PASSWORD", None)

            response = self.client.post(
                f"/admin/leads/{LEAD_EMAIL}/delete",
                auth=GOOD_AUTH,
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 503)
        self.assertIsNotNone(
            self.crm.get_lead_by_email(LEAD_EMAIL, business_id="kaivix")
        )


if __name__ == "__main__":
    unittest.main()
