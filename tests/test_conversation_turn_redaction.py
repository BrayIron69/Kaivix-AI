"""
Conversation turns must not write visitor PII to logs/app.log in the clear.

Companion to test_logger_pii_redaction.py, which covers the same rule for
`Logger.log_lead`. Two paths logged whole turns verbatim:

  - `Logger.log_user` / `log_ai`, called from app.py (the local CLI harness)
  - `ConversationEngine._log_turn`, called on every /chat request, which
    embedded a generated narrative containing the lead's name and their
    known facts -- including their email address

The rule these tests enforce: structured, non-identifying fields (stage,
intent, goal, completion, missing field *names*) are kept; narrative and
free-text fields are swept for addresses, bounded, and withheld entirely
unless KAIVIX_LOG_CONVERSATION_BODIES is set.

As in the companion file, the load-bearing tests assert against the line the
logger actually emitted, not against the helpers in isolation.
"""

import contextlib
import io
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core_ai.conversation_engine import ConversationEngine
from core_ai.conversation_summary import ConversationSummary
from core_ai.stages import ConversationStage
from core_ai.working_memory import WorkingMemory
from utils.logger import (
    Logger,
    conversation_bodies_enabled,
    describe_body,
    redact_free_text,
)

# A realistic visitor turn. This is close to a line that is really in the
# existing log: people answer the qualification questions all at once.
VISITOR_TURN = (
    "hi im Nadia Okonkwo, email is nadia.okonkwo@ridgeline-dental.com, "
    "number is 23149389819, budget is 5000$, business is dental"
)

BODIES_ON = {"KAIVIX_LOG_CONVERSATION_BODIES": "1"}
BODIES_OFF = {"KAIVIX_LOG_CONVERSATION_BODIES": ""}


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class _LogCaptureMixin:
    """
    Capture what the logger actually emits, without writing to logs/app.log.

    Same approach as test_logger_pii_redaction.py: Logger attaches a
    FileHandler to a named logger on first construction and reuses it
    afterwards, so these tests add their own handler and drop it again rather
    than disturbing that setup.
    """

    def _capture(self):
        logger = Logger()
        handler = _CapturingHandler()
        logger.logger.addHandler(handler)
        self.addCleanup(logger.logger.removeHandler, handler)
        return logger, handler


# ----------------------------------------------------------------------
# Logger.log_user / log_ai
# ----------------------------------------------------------------------


class TestTurnBodiesAreWithheldByDefault(_LogCaptureMixin, unittest.TestCase):
    """
    The default posture, with no environment variable set at all.
    """

    def setUp(self):
        logger, self.handler = self._capture()

        with patch.dict("os.environ", BODIES_OFF):
            logger.log_user(VISITOR_TURN)
            logger.log_ai(f"Thanks Nadia! I'll follow up at {VISITOR_TURN[:0]}nadia@x.com")

        self.user_line, self.ai_line = self.handler.lines[-2:]

    def test_visitor_email_is_absent(self):
        self.assertNotIn("nadia.okonkwo@ridgeline-dental.com", self.user_line)
        self.assertNotIn("nadia.okonkwo", self.user_line)

    def test_visitor_name_is_absent(self):
        self.assertNotIn("Nadia Okonkwo", self.user_line)
        self.assertNotIn("Okonkwo", self.user_line)

    def test_phone_number_is_absent(self):
        """Not something a sweep could catch -- withholding the body is what
        keeps it out."""
        self.assertNotIn("23149389819", self.user_line)

    def test_assistant_turn_is_withheld_too(self):
        """The reply quotes back what it was told, one turn later."""
        self.assertNotIn("nadia@x.com", self.ai_line)
        self.assertNotIn("Nadia", self.ai_line)

    def test_the_turn_is_still_recorded_as_having_happened(self):
        self.assertIn("Visitor:", self.user_line)
        self.assertIn("Alex:", self.ai_line)

    def test_length_is_still_reported(self):
        """A withheld body should still answer "was there a turn, how big"."""
        self.assertIn(f"<{len(VISITOR_TURN)} chars withheld", self.user_line)

    def test_placeholder_names_the_switch_that_re_enables_bodies(self):
        self.assertIn("KAIVIX_LOG_CONVERSATION_BODIES", self.user_line)


class TestTurnBodiesWhenExplicitlyEnabled(_LogCaptureMixin, unittest.TestCase):
    """
    Switching bodies on is a debugging act, not a bypass: the address sweep
    and the length bound still apply.
    """

    def setUp(self):
        logger, self.handler = self._capture()

        with patch.dict("os.environ", BODIES_ON):
            logger.log_user(VISITOR_TURN)

        self.line = self.handler.lines[-1]

    def test_body_is_present_now(self):
        self.assertIn("hi im Nadia", self.line)

    def test_email_is_still_masked(self):
        self.assertNotIn("nadia.okonkwo@ridgeline-dental.com", self.line)
        self.assertIn("n***@ridgeline-dental.com", self.line)

    def test_a_normal_turn_is_not_needlessly_chopped(self):
        """
        The bound is there to stop a pasted essay, not to make an ordinary
        turn unreadable -- a debugging switch that returns fragments is not
        worth switching on.
        """
        self.assertIn("business is dental", self.line)

    def test_a_very_long_turn_is_still_bounded(self):
        logger, handler = self._capture()

        with patch.dict("os.environ", BODIES_ON):
            logger.log_user("z" * 2000)

        self.assertIn("+1600 chars", handler.lines[-1])
        self.assertLess(len(handler.lines[-1]), 600)


class TestEmptyTurns(_LogCaptureMixin, unittest.TestCase):
    def test_empty_message_logs_without_raising(self):
        logger, handler = self._capture()
        logger.log_user("")
        self.assertIn("<empty>", handler.lines[-1])

    def test_none_message_logs_without_raising(self):
        """A logging call must never be the thing that breaks a request."""
        logger, handler = self._capture()
        logger.log_ai(None)
        self.assertIn("<empty>", handler.lines[-1])


# ----------------------------------------------------------------------
# ConversationEngine._log_turn -- the serving path
# ----------------------------------------------------------------------


def _build_narrative_the_way_production_does():
    """
    Produce a conversation summary through the real ConversationSummary
    engine, so this test breaks if that engine starts embedding something new
    rather than only if the log line changes.
    """
    lead = SimpleNamespace(
        name="Nadia Okonkwo",
        company="Ridgeline Dental",
        known_facts=[
            "email:nadia.okonkwo@ridgeline-dental.com",
            "company:Ridgeline Dental",
            "budget:$2000/month",
        ],
        buying_signals=["budget"],
        temperature="Hot",
        objections=[],
    )

    working_memory = WorkingMemory()
    working_memory.update(
        lead=lead,
        qualification={"missing": []},
        goal=SimpleNamespace(value="buying_signal"),
        history=[],
    )
    working_memory.set_conversation_summary(
        ConversationSummary().build(lead=lead, working_memory=working_memory)
    )

    return working_memory


class _LogTurnMixin(_LogCaptureMixin):
    def _emit_turn(self, working_memory, qualification=None):
        """
        Drive the real _log_turn with a stub `self`. It only reaches for
        `self.logger`, so this exercises the actual method without standing up
        an engine (which would need config, a knowledge base and an LLM).

        stdout is swallowed because _log_turn prints the same block it logs.
        """
        logger, handler = self._capture()

        with contextlib.redirect_stdout(io.StringIO()) as printed:
            ConversationEngine._log_turn(
                SimpleNamespace(logger=logger),
                conversation_id="82698220-b76e-4ef1-81f2-625153732749",
                stage=ConversationStage.CLOSING,
                intent=SimpleNamespace(value="buying_signal"),
                goal=SimpleNamespace(value="buying_signal"),
                qualification=qualification
                or {
                    "missing": [],
                    "progress": {"qualified": True, "completion_percentage": 100.0},
                },
                working_memory=working_memory,
            )

        return handler.lines[-1], printed.getvalue()


class TestServingPathTurnLogDoesNotLeak(_LogTurnMixin, unittest.TestCase):
    def setUp(self):
        working_memory = _build_narrative_the_way_production_does()

        with patch.dict("os.environ", BODIES_OFF):
            self.line, self.printed = self._emit_turn(working_memory)

    def test_the_narrative_email_is_absent(self):
        """This is the regression: three of the four addresses in the existing
        log arrived here, inside the generated summary."""
        self.assertNotIn("nadia.okonkwo@ridgeline-dental.com", self.line)
        self.assertNotIn("nadia.okonkwo", self.line)

    def test_the_lead_name_is_absent(self):
        """The narrative opens with the name, which no sweep can find."""
        self.assertNotIn("Nadia Okonkwo", self.line)
        self.assertNotIn("Okonkwo", self.line)

    def test_stdout_does_not_leak_either(self):
        """Under a container runtime stdout is collected like any log."""
        self.assertNotIn("nadia.okonkwo@ridgeline-dental.com", self.printed)
        self.assertNotIn("Okonkwo", self.printed)

    def test_structured_fields_are_kept(self):
        """Decision #026's rule: non-identifying data stays, or an operator
        will put it back under pressure."""
        self.assertIn("Stage: closing", self.line)
        self.assertIn("Intent: buying_signal", self.line)
        self.assertIn("Qualified: True", self.line)
        self.assertIn("Completion: 100.0%", self.line)

    def test_the_conversation_id_is_kept(self):
        """The correlation handle for the whole turn."""
        self.assertIn("82698220-b76e-4ef1-81f2-625153732749", self.line)

    def test_the_narrative_is_reported_as_withheld_not_dropped(self):
        self.assertIn("Conversation summary (turn 1): <", self.line)
        self.assertIn("chars withheld", self.line)


class TestServingPathTurnLogWithBodiesEnabled(_LogTurnMixin, unittest.TestCase):
    def setUp(self):
        working_memory = _build_narrative_the_way_production_does()

        with patch.dict("os.environ", BODIES_ON):
            self.line, self.printed = self._emit_turn(working_memory)

    def test_narrative_is_present_now(self):
        self.assertIn("is 1 turn(s) into the conversation", self.line)

    def test_email_inside_the_narrative_is_still_masked(self):
        self.assertNotIn("nadia.okonkwo@ridgeline-dental.com", self.line)
        self.assertIn("n***@ridgeline-dental.com", self.line)


class TestMissingFieldNamesAreNotMistakenForValues(_LogTurnMixin, unittest.TestCase):
    """
    "Missing fields: ['name', 'email']" lists which fields are absent. Those
    are field names, not the visitor's name and address, and must survive --
    they are the single most useful thing in the line when debugging why
    qualification stalled.
    """

    def test_missing_field_names_are_kept(self):
        with patch.dict("os.environ", BODIES_OFF):
            line, _ = self._emit_turn(
                WorkingMemory().update(
                    lead=None,
                    qualification={"missing": ["name", "email"]},
                    goal=SimpleNamespace(value="greeting"),
                    history=[],
                ),
                qualification={
                    "missing": ["name", "email"],
                    "progress": {"qualified": False, "completion_percentage": 0.0},
                },
            )

        self.assertIn("Missing fields: ['name', 'email']", line)

    def test_they_survive_in_the_working_memory_summary_too(self):
        """
        The same names appear again in the turn summary, which is swept rather
        than withheld -- the sweep must not eat them.
        """
        with patch.dict("os.environ", BODIES_OFF):
            line, _ = self._emit_turn(
                WorkingMemory().update(
                    lead=None,
                    qualification={"missing": ["name", "email"]},
                    goal=SimpleNamespace(value="greeting"),
                    history=[],
                )
            )

        self.assertIn("missing=name,email", line)


class TestObjectionTextIsSwept(_LogTurnMixin, unittest.TestCase):
    """
    working_memory.summary embeds the visitor's most recent objection
    verbatim. It is structured enough to keep, so it is swept rather than
    withheld.
    """

    def test_email_in_an_objection_is_masked(self):
        lead = SimpleNamespace(
            known_facts=[],
            buying_signals=[],
            temperature="Cold",
            objections=["send it to nadia.okonkwo@ridgeline-dental.com instead"],
        )

        with patch.dict("os.environ", BODIES_OFF):
            line, _ = self._emit_turn(
                WorkingMemory().update(
                    lead=lead,
                    qualification={"missing": []},
                    goal=SimpleNamespace(value="objection_handling"),
                    history=[],
                )
            )

        self.assertNotIn("nadia.okonkwo@ridgeline-dental.com", line)
        self.assertIn("n***@ridgeline-dental.com", line)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


class TestRedactFreeText(unittest.TestCase):
    def test_address_mid_sentence_is_masked(self):
        self.assertEqual(
            redact_free_text("my email is nadia@example.com ok?"),
            "my email is n***@example.com ok?",
        )

    def test_every_address_in_the_text_is_masked(self):
        result = redact_free_text("a@one.com and b@two.com")
        self.assertEqual(result, "a***@one.com and b***@two.com")

    def test_address_in_the_known_facts_format_is_masked(self):
        """The exact shape ConversationSummary emits."""
        self.assertEqual(
            redact_free_text("Known so far: email:nadia@example.com; budget:$500"),
            "Known so far: email:n***@example.com; budget:$500",
        )

    def test_subdomains_are_kept_whole(self):
        self.assertEqual(
            redact_free_text("write to a@mail.corp.example.com now"),
            "write to a***@mail.corp.example.com now",
        )

    def test_text_without_an_address_is_untouched(self):
        self.assertEqual(redact_free_text("no address here"), "no address here")

    def test_masking_runs_before_truncation(self):
        """
        An address straddling the truncation boundary. Truncating first would
        cut it in half and leave the local part -- the identifying half -- in
        the log with the domain gone.
        """
        text = "x" * 390 + " nadia.okonkwo@ridgeline-dental.com"

        self.assertNotIn("nadia.okonkwo", redact_free_text(text))

    def test_long_text_is_still_bounded(self):
        result = redact_free_text("y" * 1000)
        self.assertLess(len(result), 1000)
        self.assertIn("+600 chars", result)

    def test_a_caller_may_ask_for_a_tighter_bound(self):
        """Lead fields keep the original one-field limit."""
        self.assertIn("+140 chars", redact_free_text("y" * 200, limit=60))

    def test_blank_stays_blank(self):
        self.assertEqual(redact_free_text(""), "")
        self.assertEqual(redact_free_text(None), "")
        self.assertEqual(redact_free_text("   "), "")

    def test_non_string_is_accepted(self):
        self.assertEqual(redact_free_text(5000), "5000")

    def test_trailing_punctuation_is_not_swallowed_into_the_domain(self):
        """A sentence-ending period must not be read as part of the domain."""
        self.assertEqual(
            redact_free_text("reach me at nadia@example.com."),
            "reach me at n***@example.com.",
        )


class TestConversationBodiesEnabled(unittest.TestCase):
    def test_unset_is_off(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(conversation_bodies_enabled())

    def test_truthy_values(self):
        for value in ["1", "true", "TRUE", "yes", "on", " on "]:
            with self.subTest(value=value):
                with patch.dict(
                    "os.environ", {"KAIVIX_LOG_CONVERSATION_BODIES": value}
                ):
                    self.assertTrue(conversation_bodies_enabled())

    def test_falsy_values(self):
        for value in ["", "0", "false", "no", "off", "maybe"]:
            with self.subTest(value=value):
                with patch.dict(
                    "os.environ", {"KAIVIX_LOG_CONVERSATION_BODIES": value}
                ):
                    self.assertFalse(conversation_bodies_enabled())

    def test_it_is_read_per_call_not_cached(self):
        """A developer flipping it mid-session should not have to restart."""
        with patch.dict("os.environ", BODIES_OFF):
            self.assertFalse(conversation_bodies_enabled())

        with patch.dict("os.environ", BODIES_ON):
            self.assertTrue(conversation_bodies_enabled())


class TestDescribeBody(unittest.TestCase):
    def test_blank_variants_report_empty(self):
        with patch.dict("os.environ", BODIES_OFF):
            self.assertEqual(describe_body(""), "<empty>")
            self.assertEqual(describe_body(None), "<empty>")
            self.assertEqual(describe_body("   "), "<empty>")

    def test_withheld_placeholder_reports_the_stripped_length(self):
        with patch.dict("os.environ", BODIES_OFF):
            self.assertIn("<5 chars withheld", describe_body("  hello  "))

    def test_no_part_of_the_body_appears_when_withheld(self):
        with patch.dict("os.environ", BODIES_OFF):
            self.assertNotIn("hello", describe_body("hello there"))


if __name__ == "__main__":
    unittest.main()
