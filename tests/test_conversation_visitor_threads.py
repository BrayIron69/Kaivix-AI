import os
import tempfile
import unittest

from memory.conversation_memory import ConversationMemory
from memory.conversation_store import (
    PREVIEW_MAX_LENGTH,
    SQLiteConversationStore,
    build_preview,
    normalize_timestamp,
)
from services.chat_service import ChatService


class VisitorThreadTestCase(unittest.TestCase):
    """
    Shared fixture: one real SQLite store on a real temp file.

    A real file rather than :memory: because half of what is being
    tested is that this data outlives the object that wrote it.
    """

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        self.store = SQLiteConversationStore(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def memory_for(self, business_id="kaivix"):
        return ConversationMemory(business_id=business_id, store=self.store)


class TestVisitorLinking(VisitorThreadTestCase):
    def test_conversation_is_listed_for_the_visitor_that_owns_it(self):
        memory = self.memory_for()
        memory.link_visitor("conv-1", "visitor-aaaaaaaaaaaaaaa")
        memory.add_user_message("conv-1", "Do you work with dentists?")
        memory.add_assistant_message("conv-1", "Yes, we do.")

        threads = memory.list_conversations("visitor-aaaaaaaaaaaaaaa")

        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["conversation_id"], "conv-1")
        self.assertEqual(threads[0]["message_count"], 2)
        self.assertEqual(threads[0]["preview"], "Yes, we do.")
        self.assertTrue(threads[0]["last_message_at"].endswith("Z"))

    def test_linking_is_idempotent_across_repeated_turns(self):
        memory = self.memory_for()

        for _ in range(5):
            memory.link_visitor("conv-1", "visitor-aaaaaaaaaaaaaaa")

        memory.add_user_message("conv-1", "Hello")

        threads = memory.list_conversations("visitor-aaaaaaaaaaaaaaa")

        # Five links, one thread -- not five duplicate rows.
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["message_count"], 1)

    def test_a_second_visitor_cannot_take_over_an_existing_thread(self):
        """
        The whole point of ON CONFLICT DO NOTHING: a later request
        naming a different visitor must not reassign someone else's
        conversation to the caller.
        """
        memory = self.memory_for()
        memory.link_visitor("conv-1", "visitor-original-aaaaa")
        memory.add_user_message("conv-1", "My budget is $4000.")

        memory.link_visitor("conv-1", "visitor-attacker-bbbbb")

        self.assertEqual(
            memory.get_visitor_id("conv-1"), "visitor-original-aaaaa"
        )
        self.assertEqual(memory.list_conversations("visitor-attacker-bbbbb"), [])
        self.assertEqual(len(memory.list_conversations("visitor-original-aaaaa")), 1)

    def test_unowned_conversation_has_no_visitor(self):
        memory = self.memory_for()
        memory.add_user_message("conv-orphan", "Sent by an older widget build.")

        self.assertIsNone(memory.get_visitor_id("conv-orphan"))


class TestThreadListing(VisitorThreadTestCase):
    def test_threads_are_returned_most_recently_active_first(self):
        memory = self.memory_for()

        for conversation_id in ("conv-old", "conv-middle", "conv-newest"):
            memory.link_visitor(conversation_id, "visitor-aaaaaaaaaaaaaaa")
            memory.add_user_message(conversation_id, f"message in {conversation_id}")

        threads = memory.list_conversations("visitor-aaaaaaaaaaaaaaa")

        # SQLite's CURRENT_TIMESTAMP is only second-granular, so all
        # three rows can share a timestamp -- the id tie-break is what
        # makes this ordering deterministic rather than incidental.
        self.assertEqual(
            [thread["conversation_id"] for thread in threads],
            ["conv-newest", "conv-middle", "conv-old"],
        )

    def test_a_thread_rises_when_it_receives_a_new_message(self):
        memory = self.memory_for()
        memory.link_visitor("conv-a", "visitor-aaaaaaaaaaaaaaa")
        memory.add_user_message("conv-a", "first")
        memory.link_visitor("conv-b", "visitor-aaaaaaaaaaaaaaa")
        memory.add_user_message("conv-b", "second")

        # conv-a was older, then gets new activity.
        memory.add_user_message("conv-a", "back again")

        threads = memory.list_conversations("visitor-aaaaaaaaaaaaaaa")

        self.assertEqual(threads[0]["conversation_id"], "conv-a")
        self.assertEqual(threads[0]["preview"], "back again")

    def test_message_less_conversations_are_not_listed(self):
        memory = self.memory_for()
        memory.link_visitor("conv-empty", "visitor-aaaaaaaaaaaaaaa")

        self.assertEqual(memory.list_conversations("visitor-aaaaaaaaaaaaaaa"), [])

    def test_one_visitor_never_sees_another_visitors_threads(self):
        memory = self.memory_for()
        memory.link_visitor("conv-a", "visitor-aaaaaaaaaaaaaaa")
        memory.add_user_message("conv-a", "Visitor A's private message")
        memory.link_visitor("conv-b", "visitor-bbbbbbbbbbbbbbb")
        memory.add_user_message("conv-b", "Visitor B's private message")

        threads_a = memory.list_conversations("visitor-aaaaaaaaaaaaaaa")
        threads_b = memory.list_conversations("visitor-bbbbbbbbbbbbbbb")

        self.assertEqual([t["conversation_id"] for t in threads_a], ["conv-a"])
        self.assertEqual([t["conversation_id"] for t in threads_b], ["conv-b"])

    def test_one_business_never_sees_another_businesses_threads(self):
        """
        Same visitor id, two businesses, one shared store. Mirrors the
        tenant-isolation guarantee conversation_messages already has.
        """
        memory_a = self.memory_for(business_id="business-a")
        memory_b = self.memory_for(business_id="business-b")

        memory_a.link_visitor("conv-shared", "visitor-aaaaaaaaaaaaaaa")
        memory_a.add_user_message("conv-shared", "Message for business A")
        memory_b.link_visitor("conv-shared", "visitor-aaaaaaaaaaaaaaa")
        memory_b.add_user_message("conv-shared", "Message for business B")

        threads_a = memory_a.list_conversations("visitor-aaaaaaaaaaaaaaa")
        threads_b = memory_b.list_conversations("visitor-aaaaaaaaaaaaaaa")

        self.assertEqual(len(threads_a), 1)
        self.assertEqual(threads_a[0]["preview"], "Message for business A")
        self.assertEqual(len(threads_b), 1)
        self.assertEqual(threads_b[0]["preview"], "Message for business B")

    def test_limit_caps_how_many_threads_come_back(self):
        memory = self.memory_for()

        for index in range(10):
            memory.link_visitor(f"conv-{index}", "visitor-aaaaaaaaaaaaaaa")
            memory.add_user_message(f"conv-{index}", f"message {index}")

        self.assertEqual(len(memory.list_conversations("visitor-aaaaaaaaaaaaaaa", 3)), 3)
        self.assertEqual(len(memory.list_conversations("visitor-aaaaaaaaaaaaaaa")), 10)

    def test_threads_survive_a_new_store_against_the_same_file(self):
        """A restart must not lose the visitor->thread association."""
        memory = self.memory_for()
        memory.link_visitor("conv-1", "visitor-aaaaaaaaaaaaaaa")
        memory.add_user_message("conv-1", "Before the restart")

        restarted = ConversationMemory(
            business_id="kaivix",
            store=SQLiteConversationStore(db_path=self.db_path),
        )

        threads = restarted.list_conversations("visitor-aaaaaaaaaaaaaaa")
        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0]["preview"], "Before the restart")

    def test_clearing_a_conversation_also_unlists_it(self):
        memory = self.memory_for()
        memory.link_visitor("conv-1", "visitor-aaaaaaaaaaaaaaa")
        memory.add_user_message("conv-1", "Delete me")

        memory.clear("conv-1")

        self.assertEqual(memory.list_conversations("visitor-aaaaaaaaaaaaaaa"), [])
        self.assertIsNone(memory.get_visitor_id("conv-1"))


class TestPreviewAndTimestampFormatting(unittest.TestCase):
    def test_preview_flattens_whitespace(self):
        self.assertEqual(build_preview("line one\n\nline  two"), "line one line two")

    def test_preview_truncates_long_messages(self):
        preview = build_preview("x" * 500)

        self.assertEqual(len(preview), PREVIEW_MAX_LENGTH)
        self.assertTrue(preview.endswith("…"))

    def test_preview_handles_empty_content(self):
        self.assertEqual(build_preview(""), "")
        self.assertEqual(build_preview(None), "")

    def test_naive_timestamps_are_labelled_utc(self):
        self.assertEqual(
            normalize_timestamp("2026-09-11 14:22:05"), "2026-09-11T14:22:05Z"
        )

    def test_unparseable_timestamp_passes_through_instead_of_raising(self):
        self.assertEqual(normalize_timestamp("not a date"), "not a date")


class _StubEngine:
    """Minimal stand-in so ChatService can be tested without an LLM."""

    def __init__(self, memory):
        self.memory = memory


class TestChatServiceOwnershipEnforcement(VisitorThreadTestCase):
    """
    The authorization boundary itself: reopening a thread must require
    owning it, because conversation ids are guessable.
    """

    def setUp(self):
        super().setUp()
        memory = self.memory_for()
        memory.link_visitor("conv-1", "visitor-owner-aaaaaaaa")
        memory.add_user_message("conv-1", "My budget is $4000.")
        memory.add_assistant_message("conv-1", "Noted.")

        self.service = ChatService(engine_factory=lambda business_id: _StubEngine(memory))

    def test_owner_can_read_the_thread(self):
        messages = self.service.get_conversation(
            conversation_id="conv-1",
            visitor_id="visitor-owner-aaaaaaaa",
            business_id="kaivix",
        )

        self.assertEqual(
            messages,
            [
                {"role": "user", "content": "My budget is $4000."},
                {"role": "assistant", "content": "Noted."},
            ],
        )

    def test_a_different_visitor_is_refused(self):
        self.assertIsNone(
            self.service.get_conversation(
                conversation_id="conv-1",
                visitor_id="visitor-somebody-else",
                business_id="kaivix",
            )
        )

    def test_a_missing_visitor_id_is_refused(self):
        self.assertIsNone(
            self.service.get_conversation(
                conversation_id="conv-1",
                visitor_id="",
                business_id="kaivix",
            )
        )

    def test_unknown_conversation_is_refused_the_same_way(self):
        """
        Indistinguishable from "not yours" -- the route must not become
        an oracle for which conversation ids exist.
        """
        self.assertIsNone(
            self.service.get_conversation(
                conversation_id="conv-does-not-exist",
                visitor_id="visitor-owner-aaaaaaaa",
                business_id="kaivix",
            )
        )


if __name__ == "__main__":
    unittest.main()
