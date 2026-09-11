"""
The narrow factual-lookup tool: enough that Bray doesn't say "I can't
search the web" to something trivial, and deliberately no more.

Date and time are answered from the clock with no network call and no
API key, which is most of the real value here -- "what's today's date"
was the reported example, and a search API would be a slow, billable,
failure-prone way to read a clock the process already has.
"""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from core_ai.planning_engine import PlanningEngine
from tools.factual_lookup_tool import FactualLookupTool

CONTEXT = {"business_id": "kaivix", "timezone": "UTC"}


class TestAnswersDateAndTimeFromTheClock(unittest.TestCase):
    def setUp(self):
        self.tool = FactualLookupTool()

    def test_recognises_the_reported_example_and_its_variants(self):
        for question in [
            "what's today's date",
            "what is the date",
            "what day is it",
            "what day is today",
            "what year is it",
            "what time is it",
        ]:
            with self.subTest(question=question):
                self.assertTrue(FactualLookupTool.is_simple_date_question(question))

    def test_does_not_claim_every_question_is_a_date_question(self):
        for question in [
            "what do you charge",
            "how long does setup take",
            "can you handle inbound calls",
            "who is the CEO of Stripe",
        ]:
            with self.subTest(question=question):
                self.assertFalse(FactualLookupTool.is_simple_date_question(question))

    def test_answers_with_the_real_current_date_and_no_network_call(self):
        with patch("tools.factual_lookup_tool.requests") as mock_requests:
            result = self.tool.run({"question": "what's today's date"}, CONTEXT)

        self.assertTrue(result.success)
        today = datetime.now(ZoneInfo("UTC"))
        self.assertIn(str(today.year), result.summary)
        self.assertIn(today.strftime("%A"), result.summary)
        mock_requests.get.assert_not_called()

    def test_uses_the_businesss_own_timezone(self):
        result = self.tool.run(
            {"question": "what day is it"},
            {"business_id": "kaivix", "timezone": "Asia/Karachi"},
        )

        expected = datetime.now(ZoneInfo("Asia/Karachi"))
        self.assertTrue(result.success)
        self.assertIn(expected.strftime("%A"), result.summary)

    def test_an_unknown_timezone_still_answers_rather_than_refusing(self):
        """
        A config typo is not a reason to refuse to say what day it is.
        """
        result = self.tool.run({"question": "what day is it"}, {"timezone": "Mars/Olympus"})
        self.assertTrue(result.success)

    def test_a_time_question_includes_a_clock_time(self):
        result = self.tool.run({"question": "what time is it"}, CONTEXT)

        self.assertTrue(result.success)
        self.assertRegex(result.summary, r"\d{1,2}:\d{2}\s*(AM|PM)")


class TestWebSearchTierIsHonestWhenUnconfigured(unittest.TestCase):
    def setUp(self):
        self.tool = FactualLookupTool()

    @patch.dict("os.environ", {}, clear=True)
    def test_declines_rather_than_guessing_without_an_api_key(self):
        """
        Failure here means Bray says nothing about it, which is the
        whole point: an unconfigured capability must not become a
        confidently wrong answer.
        """
        result = self.tool.run({"question": "who is the CEO of Stripe"}, CONTEXT)

        self.assertFalse(result.success)
        self.assertIn("WEB_SEARCH_API_KEY", result.error)

    @patch.dict("os.environ", {"WEB_SEARCH_API_KEY": "test-key"}, clear=True)
    @patch("tools.factual_lookup_tool.requests")
    def test_returns_the_top_snippet_when_configured(self, mock_requests):
        mock_requests.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "web": {"results": [{"description": "Patrick Collison.", "url": "https://x"}]}
            },
        )

        result = self.tool.run({"question": "who is the CEO of Stripe"}, CONTEXT)

        self.assertTrue(result.success)
        self.assertEqual(result.summary, "Patrick Collison.")

    @patch.dict("os.environ", {"WEB_SEARCH_API_KEY": "test-key"}, clear=True)
    @patch("tools.factual_lookup_tool.requests")
    def test_a_search_failure_never_raises(self, mock_requests):
        mock_requests.get.side_effect = ConnectionError("down")

        result = self.tool.run({"question": "who is the CEO of Stripe"}, CONTEXT)

        self.assertFalse(result.success)

    def test_an_empty_question_is_refused(self):
        self.assertFalse(self.tool.run({}, CONTEXT).success)


def _config(enabled_tools):
    return SimpleNamespace(
        qualification=SimpleNamespace(fields=[]),
        tools=SimpleNamespace(enabled_tools=enabled_tools),
    )


class TestPlanningEngineRequestsItWithoutDerailingTheConversation(unittest.TestCase):
    def _plan(self, user_message, enabled_tools=("factual_lookup",)):
        engine = PlanningEngine(business_config=_config(list(enabled_tools)))
        lead = SimpleNamespace(
            email="", temperature="Cold", score=5, objections=[], buying_signals=[]
        )
        return engine.plan(
            stage="discovery",
            intent="question",
            goal="qualify",
            lead=lead,
            qualification={"missing": ["name", "company"], "qualified": False},
            user_message=user_message,
        )

    def test_requests_the_lookup_for_a_date_question(self):
        plan = self._plan("quick one, what's today's date?")

        self.assertEqual(plan.tool_request["name"], "factual_lookup")
        self.assertIn("date", plan.tool_request["args"]["question"])

    def test_the_conversational_plan_survives_the_tool_request(self):
        """
        A visitor asking what day it is has not stopped being
        mid-qualification. Returning a special "factual" plan would
        throw away the strategy and next question this turn still needs.
        """
        plan = self._plan("what's today's date")

        self.assertTrue(plan.strategy)
        self.assertTrue(plan.next_question)

    def test_no_request_for_an_ordinary_message(self):
        self.assertIsNone(self._plan("we run a dental clinic").tool_request)

    def test_no_request_when_the_business_has_not_enabled_it(self):
        plan = self._plan("what's today's date", enabled_tools=("calendar_booking",))
        self.assertIsNone(plan.tool_request)


if __name__ == "__main__":
    unittest.main()
