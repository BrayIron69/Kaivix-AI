"""
Asking about the product is not an objection.

Found in production. A fully qualified, Hot lead replied "patient
support mainly" -- naming the thing they wanted to buy -- and the turn
logged:

    Stage: objection_handling    Intent: support

PlanningEngine's first branch is objections, and it outranks everything
else, so drive_to_booking never ran, the real calendar was never
consulted, and Bray fell back to the generic Calendly link instead of
offering real times.

The cause is specific to what this business SELLS. _OBJECTION_HANDLING_
INTENTS contained "support", and "support" is an intent keyword
(core_ai/intent_detector.py) -- so the single most likely word a
prospect uses to describe the product ("we want support automated",
"patient support", "customer support") forced the objection stage.
"pricing" was in there too, though a pricing question from a qualified
buyer is a buying signal, not a complaint.

Genuine objections are unaffected: PlanningEngine's branch checks
`objections or stage == OBJECTION_HANDLING or intent == OBJECTION`, and
both the objections list and the objection intent still route there.
"""

import unittest

from core_ai.intents import Intent
from core_ai.stages import ConversationStage


def _history(turns: int):
    return [{"role": "user", "content": "..."} for _ in range(turns)]


class _StageMixin:
    def _stage(self, intent, qualified=True, completion=100.0):
        from core_ai.conversation_engine import ConversationEngine

        return ConversationEngine._detect_stage(
            ConversationEngine,
            _history(10),
            intent,
            {"qualified": qualified, "completion_percentage": completion},
        )


class TestProductQuestionsAreNotObjections(_StageMixin, unittest.TestCase):
    def test_naming_the_product_does_not_force_objection_handling(self):
        """
        The verbatim production case: "patient support mainly" from a
        qualified lead.
        """
        self.assertNotEqual(
            self._stage(Intent.SUPPORT), ConversationStage.OBJECTION_HANDLING
        )

    def test_a_qualified_lead_asking_about_support_reaches_closing(self):
        self.assertEqual(self._stage(Intent.SUPPORT), ConversationStage.CLOSING)

    def test_a_pricing_question_is_not_an_objection(self):
        """
        A qualified buyer asking what it costs is the strongest buying
        signal there is.
        """
        self.assertNotEqual(
            self._stage(Intent.PRICING), ConversationStage.OBJECTION_HANDLING
        )

    def test_an_unqualified_pricing_question_still_qualifies_rather_than_deflects(self):
        self.assertEqual(
            self._stage(Intent.PRICING, qualified=False, completion=20.0),
            ConversationStage.QUALIFICATION,
        )


class TestRealObjectionsStillHandled(_StageMixin, unittest.TestCase):
    def test_an_objection_intent_still_forces_objection_handling(self):
        self.assertEqual(
            self._stage(Intent.OBJECTION), ConversationStage.OBJECTION_HANDLING
        )

    def test_a_recorded_objection_still_wins_in_the_planner(self):
        """
        Stage is only one of three routes into the objection branch. A
        visitor who actually objected is caught by the objections list
        regardless of stage, which is what keeps this fix from
        weakening objection handling.
        """
        from types import SimpleNamespace

        from core_ai.planning_engine import PlanningEngine

        engine = PlanningEngine(
            business_config=SimpleNamespace(
                qualification=SimpleNamespace(fields=[]),
                tools=SimpleNamespace(enabled_tools=[]),
            )
        )
        lead = SimpleNamespace(
            email="n@example.com",
            temperature="Hot",
            score=90,
            objections=["too expensive"],
            buying_signals=[],
        )

        plan = engine.plan(
            stage=ConversationStage.CLOSING,
            intent=Intent.SUPPORT,
            goal="book_meeting",
            lead=lead,
            qualification={"missing": [], "qualified": True},
        )

        self.assertEqual(plan.strategy, "acknowledge_and_reframe_objection")


class TestQualifiedLeadNamingTheProductGetsDrivenToBooking(unittest.TestCase):
    def test_the_end_to_end_routing_that_broke(self):
        from types import SimpleNamespace

        from core_ai.planning_engine import PlanningEngine

        engine = PlanningEngine(
            business_config=SimpleNamespace(
                qualification=SimpleNamespace(fields=[]),
                tools=SimpleNamespace(enabled_tools=[]),
            )
        )
        lead = SimpleNamespace(
            email="val@example.com",
            temperature="Hot",
            score=90,
            objections=[],
            buying_signals=["budget"],
        )

        from core_ai.conversation_engine import ConversationEngine

        stage = ConversationEngine._detect_stage(
            ConversationEngine,
            _history(10),
            Intent.SUPPORT,
            {"qualified": True, "completion_percentage": 100.0},
        )

        plan = engine.plan(
            stage=stage,
            intent=Intent.SUPPORT,
            goal="book_meeting",
            lead=lead,
            qualification={"missing": [], "qualified": True},
        )

        self.assertEqual(plan.strategy, "drive_to_booking")


if __name__ == "__main__":
    unittest.main()
