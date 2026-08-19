"""
A lead's FULL conversation history -- not just the most recent one.

leads.conversation_id is overwritten on every sync, so before
crm/lead_conversations.py a returning visitor's earlier conversations
stayed in memory/conversation_memory.db with nothing pointing at them.
Two consequences, one cosmetic and one not:

  - The admin dashboard could only ever show the latest transcript.
  - Deleting a lead cleared only the conversation the lead still named.
    Every earlier transcript survived a delete that claimed to remove
    the lead and its conversation.

The second is the one that matters, and it is what
TestDeleteRemovesEveryConversation covers.
"""

import os
import secrets
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import crm.database as database
from api.main import app
from crm.lead_conversations import LeadConversationLinks
from crm.sqlite_crm import SQLiteCRM
from memory.conversation_memory import ConversationMemory
from memory.conversation_store import SQLiteConversationStore

TEST_USERNAME = "admin-" + secrets.token_hex(4)
TEST_PASSWORD = secrets.token_urlsafe(24)
GOOD_AUTH = (TEST_USERNAME, TEST_PASSWORD)

LEAD_EMAIL = "returning@example.com"
BUSINESS = "kaivix"
OTHER_BUSINESS = "other-co"


class _HistoryTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        self._original_db = database.DATABASE_NAME
        database.DATABASE_NAME = self.db_path
        self.addCleanup(self._restore_crm)

        fd, self.conversation_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.conversation_db)
        self._original_conv_db = SQLiteConversationStore.DB_PATH
        SQLiteConversationStore.DB_PATH = self.conversation_db
        self.addCleanup(self._restore_conv)

        self.crm = SQLiteCRM()
        self.links = LeadConversationLinks()
        self.client = TestClient(app)

        env = patch.dict(
            os.environ,
            {"ADMIN_USERNAME": TEST_USERNAME, "ADMIN_PASSWORD": TEST_PASSWORD},
        )
        env.start()
        self.addCleanup(env.stop)

    def _restore_crm(self):
        database.DATABASE_NAME = self._original_db
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _restore_conv(self):
        SQLiteConversationStore.DB_PATH = self._original_conv_db
        if os.path.exists(self.conversation_db):
            os.remove(self.conversation_db)

    def _seed_conversation(self, conversation_id, text, business_id=BUSINESS):
        ConversationMemory(business_id=business_id).add_user_message(
            conversation_id, text
        )

    def _seed_returning_visitor(self):
        """Three sessions for one lead, as a returning visitor produces."""
        for index, conversation_id in enumerate(
            ("session_one", "session_two", "session_three"), start=1
        ):
            self._seed_conversation(conversation_id, f"VISIT-{index}-TEXT")
            self.links.link(LEAD_EMAIL, conversation_id, business_id=BUSINESS)

        # leads.conversation_id holds only the latest, as in production.
        self.crm.save_lead(
            {
                "name": "Returning Visitor",
                "email": LEAD_EMAIL,
                "conversation_id": "session_three",
                "score": 0,
                "priority": "Cold",
                "status": "New",
            },
            business_id=BUSINESS,
        )


class TestLinkStore(_HistoryTestCase):
    def test_links_are_returned_oldest_first(self):
        self._seed_returning_visitor()

        self.assertEqual(
            self.links.conversation_ids_for(LEAD_EMAIL, business_id=BUSINESS),
            ["session_one", "session_two", "session_three"],
        )

    def test_relinking_the_same_conversation_is_a_no_op(self):
        """link() runs on every turn, so repeats must not accumulate."""
        for _ in range(5):
            self.links.link(LEAD_EMAIL, "session_one", business_id=BUSINESS)

        self.assertEqual(
            self.links.conversation_ids_for(LEAD_EMAIL, business_id=BUSINESS),
            ["session_one"],
        )

    def test_links_are_scoped_by_business(self):
        self.links.link(LEAD_EMAIL, "session_mine", business_id=BUSINESS)
        self.links.link(LEAD_EMAIL, "session_theirs", business_id=OTHER_BUSINESS)

        self.assertEqual(
            self.links.conversation_ids_for(LEAD_EMAIL, business_id=BUSINESS),
            ["session_mine"],
        )
        self.assertEqual(
            self.links.conversation_ids_for(LEAD_EMAIL, business_id=OTHER_BUSINESS),
            ["session_theirs"],
        )

    def test_blank_inputs_are_ignored_rather_than_stored(self):
        self.links.link("", "session_x", business_id=BUSINESS)
        self.links.link(LEAD_EMAIL, "", business_id=BUSINESS)

        self.assertEqual(
            self.links.conversation_ids_for(LEAD_EMAIL, business_id=BUSINESS), []
        )
        self.assertEqual(self.links.conversation_ids_for("", business_id=BUSINESS), [])


class TestAdminShowsEveryConversation(_HistoryTestCase):
    def _detail(self):
        return self.client.get(f"/admin/leads/{LEAD_EMAIL}", auth=GOOD_AUTH)

    def test_all_three_transcripts_are_rendered_oldest_first(self):
        self._seed_returning_visitor()

        body = self._detail().text

        for marker in ("VISIT-1-TEXT", "VISIT-2-TEXT", "VISIT-3-TEXT"):
            self.assertIn(marker, body)

        self.assertLess(body.index("VISIT-1-TEXT"), body.index("VISIT-2-TEXT"))
        self.assertLess(body.index("VISIT-2-TEXT"), body.index("VISIT-3-TEXT"))
        self.assertIn("Conversation 1 of 3", body)
        self.assertIn("Conversation 3 of 3", body)

    def test_a_single_conversation_is_not_numbered(self):
        self._seed_conversation("session_only", "ONLY-TEXT")
        self.links.link(LEAD_EMAIL, "session_only", business_id=BUSINESS)
        self.crm.save_lead(
            {"name": "Solo", "email": LEAD_EMAIL, "conversation_id": "session_only"},
            business_id=BUSINESS,
        )

        body = self._detail().text

        self.assertIn("ONLY-TEXT", body)
        self.assertNotIn("Conversation 1 of 1", body)

    def test_legacy_lead_with_no_links_falls_back_to_its_column(self):
        """
        Leads captured before the join table existed have no link rows.
        Their one stored conversation must still appear, or the feature
        would look like it deleted history it never had.
        """
        self._seed_conversation("session_legacy", "LEGACY-TEXT")
        self.crm.save_lead(
            {
                "name": "Legacy",
                "email": LEAD_EMAIL,
                "conversation_id": "session_legacy",
            },
            business_id=BUSINESS,
        )
        self.assertEqual(
            self.links.conversation_ids_for(LEAD_EMAIL, business_id=BUSINESS), []
        )

        self.assertIn("LEGACY-TEXT", self._detail().text)

    def test_another_businesss_conversation_never_appears(self):
        self._seed_returning_visitor()
        self._seed_conversation(
            "session_one", "OTHER-TENANT-SECRET", business_id=OTHER_BUSINESS
        )

        self.assertNotIn("OTHER-TENANT-SECRET", self._detail().text)


class TestDeleteRemovesEveryConversation(_HistoryTestCase):
    """
    The data-retention half. This is the bug that mattered: a delete that
    left earlier transcripts on disk.
    """

    def _delete(self):
        return self.client.post(
            f"/admin/leads/{LEAD_EMAIL}/delete",
            auth=GOOD_AUTH,
            follow_redirects=False,
        )

    def _stored(self, conversation_id, business_id=BUSINESS):
        return ConversationMemory(business_id=business_id).get_conversation(
            conversation_id
        )

    def test_all_three_conversations_are_deleted_not_just_the_latest(self):
        self._seed_returning_visitor()

        for conversation_id in ("session_one", "session_two", "session_three"):
            self.assertEqual(len(self._stored(conversation_id)), 1)

        response = self._delete()
        self.assertEqual(response.status_code, 303)

        for conversation_id in ("session_one", "session_two", "session_three"):
            with self.subTest(conversation_id=conversation_id):
                self.assertEqual(
                    self._stored(conversation_id), [],
                    f"{conversation_id} survived the delete -- the visitor's "
                    f"own words are still on disk.",
                )

    def test_link_rows_are_removed_too(self):
        self._seed_returning_visitor()

        self._delete()

        self.assertEqual(
            self.links.conversation_ids_for(LEAD_EMAIL, business_id=BUSINESS), []
        )

    def test_the_lead_record_is_removed(self):
        self._seed_returning_visitor()

        self._delete()

        self.assertIsNone(self.crm.get_lead_by_email(LEAD_EMAIL, business_id=BUSINESS))

    def test_another_businesss_conversation_is_not_deleted(self):
        self._seed_returning_visitor()
        self._seed_conversation(
            "session_one", "not yours to delete", business_id=OTHER_BUSINESS
        )

        self._delete()

        self.assertEqual(
            self._stored("session_one", business_id=OTHER_BUSINESS),
            [{"role": "user", "content": "not yours to delete"}],
        )

    def test_unauthenticated_delete_removes_nothing(self):
        self._seed_returning_visitor()

        response = self.client.post(
            f"/admin/leads/{LEAD_EMAIL}/delete", follow_redirects=False
        )

        self.assertEqual(response.status_code, 401)
        for conversation_id in ("session_one", "session_two", "session_three"):
            self.assertEqual(len(self._stored(conversation_id)), 1)
        self.assertIsNotNone(
            self.crm.get_lead_by_email(LEAD_EMAIL, business_id=BUSINESS)
        )


if __name__ == "__main__":
    unittest.main()
