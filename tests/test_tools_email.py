"""
The Tool layer: a real capability invoked deterministically, whose
result is the only thing that lets Bray claim it happened.

The property under test throughout is the one that matters: a claim
that an email was sent is downstream of an email actually being sent,
never downstream of the conversation feeling like it should have been.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core_ai.conversation_plan import ConversationPlan
from core_ai.planning_engine import PlanningEngine
from core_ai.prompt_builder import PromptBuilder
from tools.base_tool import ToolResult
from tools.email_tool import SendOverviewEmailTool
from tools.registry import ToolRegistry

CONTEXT = {
    "business_id": "kaivix",
    "business_name": "Kaivix Labs",
    "booking_link": "https://calendly.com/example/30min",
    "lead_email": "nadia@ridgeline.com",
    "lead_name": "Nadia",
}


class TestSendOverviewEmailTool(unittest.TestCase):
    def _tool(self, connected=True, send_result=None):
        provider = MagicMock()
        provider.is_connected.return_value = connected
        provider.send_email.return_value = send_result or {"success": True, "error": None}
        return SendOverviewEmailTool(email_provider=provider), provider

    def test_sends_and_reports_success(self):
        tool, provider = self._tool()

        result = tool.run({}, CONTEXT)

        self.assertTrue(result.success)
        self.assertIn("nadia@ridgeline.com", result.summary)
        provider.send_email.assert_called_once()
        self.assertEqual(provider.send_email.call_args.kwargs["to"], "nadia@ridgeline.com")

    def test_body_contains_the_booking_link_and_the_leads_name(self):
        tool, provider = self._tool()
        tool.run({}, CONTEXT)

        body = provider.send_email.call_args.kwargs["body_text"]
        self.assertIn("https://calendly.com/example/30min", body)
        self.assertIn("Nadia", body)

    def test_refuses_with_no_recipient_and_sends_nothing(self):
        tool, provider = self._tool()

        result = tool.run({}, {**CONTEXT, "lead_email": ""})

        self.assertFalse(result.success)
        provider.send_email.assert_not_called()

    def test_refuses_when_provider_not_connected_and_sends_nothing(self):
        tool, provider = self._tool(connected=False)

        result = tool.run({}, CONTEXT)

        self.assertFalse(result.success)
        provider.send_email.assert_not_called()

    def test_a_failed_send_is_reported_as_failure_not_success(self):
        tool, _ = self._tool(send_result={"success": False, "error": "scope missing"})

        result = tool.run({}, CONTEXT)

        self.assertFalse(result.success)
        self.assertEqual(result.summary, "")

    def test_the_visitor_facing_summary_never_carries_the_raw_error(self):
        tool, _ = self._tool(
            send_result={"success": False, "error": "gmail.send not granted for brayiron@..."}
        )

        result = tool.run({}, CONTEXT)

        self.assertNotIn("gmail.send", result.summary)


class TestRegistryGating(unittest.TestCase):
    def setUp(self):
        self.tool = MagicMock()
        self.tool.run.return_value = ToolResult(success=True, summary="done")
        self.registry = ToolRegistry(tools={"send_overview_email": self.tool})

    def test_runs_when_the_business_enabled_it(self):
        result = self.registry.run("send_overview_email", {}, CONTEXT, ["send_overview_email"])

        self.assertTrue(result.success)
        self.tool.run.assert_called_once()

    def test_fails_closed_when_the_business_has_not_enabled_it(self):
        """
        Same gate calendar booking already has, and for the same reason:
        a real side effect must be switched on deliberately, never
        acquired by upgrading.
        """
        result = self.registry.run("send_overview_email", {}, CONTEXT, ["calendar_booking"])

        self.assertFalse(result.success)
        self.tool.run.assert_not_called()

    def test_fails_closed_for_an_unknown_tool_name(self):
        result = self.registry.run("rm_rf", {}, CONTEXT, ["rm_rf"])
        self.assertFalse(result.success)

    def test_a_tool_that_raises_never_takes_down_the_turn(self):
        self.tool.run.side_effect = RuntimeError("boom")

        result = self.registry.run("send_overview_email", {}, CONTEXT, ["send_overview_email"])

        self.assertFalse(result.success)
        self.assertIn("boom", result.error)


def _config(enabled_tools):
    return SimpleNamespace(
        qualification=SimpleNamespace(fields=[]),
        tools=SimpleNamespace(enabled_tools=enabled_tools),
    )


class TestPlanningEngineRequestsTheToolDeterministically(unittest.TestCase):
    """
    PlanningEngine RECORDS the request and performs no I/O, exactly as
    it does for nothing-else-in-the-plan. These assert on the request,
    never on a send.
    """

    def _closing_plan(self, enabled_tools, email="nadia@ridgeline.com"):
        engine = PlanningEngine(business_config=_config(enabled_tools))
        lead = SimpleNamespace(
            email=email, temperature="Hot", score=90, objections=[], buying_signals=["pricing"]
        )
        return engine.plan(
            stage="closing",
            intent="buying_signal",
            goal="book_meeting",
            lead=lead,
            qualification={"missing": [], "qualified": True},
        )

    def test_requests_the_email_at_the_closing_moment(self):
        plan = self._closing_plan(["send_overview_email"])

        self.assertEqual(plan.strategy, "drive_to_booking")
        self.assertEqual(plan.tool_request["name"], "send_overview_email")

    def test_no_request_when_the_business_has_not_enabled_the_tool(self):
        plan = self._closing_plan(["calendar_booking"])
        self.assertIsNone(plan.tool_request)

    def test_no_request_without_a_real_address_to_send_to(self):
        plan = self._closing_plan(["send_overview_email"], email="")
        self.assertIsNone(plan.tool_request)

    def test_a_fully_qualified_lead_closes_even_without_urgency_language(self):
        """
        The five fields kaivix's qualification.yaml asks for are worth
        at most 65 in LeadIntelligenceEngine and HOT starts at 75, so
        before this the temperature test was structurally unreachable
        from qualification alone: a perfectly qualified buyer who never
        happened to say "urgent" stayed Warm and Bray never asked for
        the meeting.
        """
        engine = PlanningEngine(business_config=_config(["send_overview_email"]))
        lead = SimpleNamespace(
            email="nadia@ridgeline.com",
            temperature="Warm",
            score=65,
            objections=[],
            buying_signals=[],
        )

        plan = engine.plan(
            stage="discovery",
            intent="question",
            goal="qualify",
            lead=lead,
            qualification={"missing": [], "qualified": True},
        )

        self.assertEqual(plan.strategy, "drive_to_booking")

    def test_no_request_while_still_qualifying(self):
        """
        The trigger is the closing moment specifically, not "any turn
        where an address happens to be known".
        """
        engine = PlanningEngine(business_config=_config(["send_overview_email"]))
        lead = SimpleNamespace(
            email="nadia@ridgeline.com",
            temperature="Cold",
            score=10,
            objections=[],
            buying_signals=[],
        )

        plan = engine.plan(
            stage="discovery",
            intent="question",
            goal="qualify",
            lead=lead,
            qualification={"missing": ["name", "company", "budget"], "qualified": False},
        )

        self.assertIsNone(plan.tool_request)


class TestPromptOnlyAuthorisesAClaimAfterARealSuccess(unittest.TestCase):
    def _prompt(self, tool_result):
        return PromptBuilder().build(
            stage="closing",
            intent="buying_signal",
            goal="book_meeting",
            knowledge="",
            plan=ConversationPlan(strategy="drive_to_booking", tool_result=tool_result),
        )

    def test_success_authorises_the_claim(self):
        prompt = self._prompt(
            {"name": "send_overview_email", "success": True, "summary": "Sent the overview email to nadia@ridgeline.com."}
        )

        self.assertIn("ACTION ALREADY COMPLETED", prompt)
        self.assertIn("nadia@ridgeline.com", prompt)

    def test_failure_renders_nothing_at_all(self):
        """
        With no section present, ENGINE_RULES rule 12 already produces
        the right behaviour: don't mention it. Describing the failure
        would invite an apology for something the visitor never asked
        for.
        """
        prompt = self._prompt(
            {"name": "send_overview_email", "success": False, "summary": ""}
        )

        self.assertNotIn("ACTION ALREADY COMPLETED", prompt)

    def test_no_tool_run_renders_nothing(self):
        prompt = self._prompt(None)
        self.assertNotIn("ACTION ALREADY COMPLETED", prompt)


class TestEngineRunsItOnceAndOnlyOnRealSuccess(unittest.TestCase):
    """
    ConversationEngine owns the ledger of what has already been done,
    because PlanningEngine is stateless and re-requests the email on
    every closing turn. Without this, a visitor lingering in the closing
    stage gets mailed on every single message.
    """

    def setUp(self):
        from tests.test_ai_disclosure import _IsolatedDatabasesMixin

        _IsolatedDatabasesMixin._isolate_databases(self)

        from core_ai.conversation_engine import ConversationEngine

        self.engine = ConversationEngine()
        self.engine.llm = MagicMock()
        self.engine.llm.generate.return_value = "Great, talk soon."
        self.engine.calendar_provider = MagicMock()
        self.engine.calendar_provider.is_connected.return_value = False

        self.sent = []

        def _send(business_id, to="", subject="", body_text=""):
            self.sent.append(to)
            return {"success": True, "error": None}

        self.engine.email_provider.is_connected = MagicMock(return_value=True)
        self.engine.email_provider.send_email = MagicMock(side_effect=_send)

    def _closing_plan(self):
        return ConversationPlan(
            strategy="drive_to_booking",
            tool_request={"name": "send_overview_email", "args": {}},
        )

    def _lead(self):
        from core_ai.lead_profile import LeadProfile

        return LeadProfile(name="Nadia", email="nadia@ridgeline.com")

    def test_runs_once_and_attaches_a_successful_result(self):
        plan = self.engine._maybe_run_requested_tool("conv-1", self._closing_plan(), self._lead())

        self.assertTrue(plan.tool_result["success"])
        self.assertEqual(self.sent, ["nadia@ridgeline.com"])

    def test_a_second_closing_turn_does_not_send_again(self):
        lead = self._lead()
        self.engine._maybe_run_requested_tool("conv-1", self._closing_plan(), lead)
        second = self.engine._maybe_run_requested_tool("conv-1", self._closing_plan(), lead)

        self.assertEqual(self.sent, ["nadia@ridgeline.com"])
        # No result attached the second time, so nothing re-authorises
        # the claim -- Bray does not announce the same email twice.
        self.assertIsNone(second.tool_result)

    def test_a_different_conversation_still_gets_its_own_email(self):
        lead = self._lead()
        self.engine._maybe_run_requested_tool("conv-1", self._closing_plan(), lead)
        self.engine._maybe_run_requested_tool("conv-2", self._closing_plan(), lead)

        self.assertEqual(len(self.sent), 2)

    def test_a_failed_send_is_not_recorded_so_a_later_turn_can_retry(self):
        """
        The address may have only just been corrected. A failure must
        not permanently burn the one chance to follow up.
        """
        self.engine.email_provider.send_email = MagicMock(
            return_value={"success": False, "error": "temporary failure"}
        )
        lead = self._lead()

        first = self.engine._maybe_run_requested_tool("conv-1", self._closing_plan(), lead)
        self.assertFalse(first.tool_result["success"])

        self.engine.email_provider.send_email = MagicMock(
            return_value={"success": True, "error": None}
        )
        second = self.engine._maybe_run_requested_tool("conv-1", self._closing_plan(), lead)

        self.assertTrue(second.tool_result["success"])

    def test_no_request_means_no_tool_and_no_result(self):
        plan = self.engine._maybe_run_requested_tool("conv-1", ConversationPlan(), self._lead())

        self.assertIsNone(plan.tool_result)
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
