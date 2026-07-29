"""
PlanningEngine's next-question hints come from the business's own
qualification schema, not a hardcoded dict.

_FIELD_QUESTIONS used to hold five entries that were byte-identical
copies of config/businesses/kaivix/qualification.yaml's prompt_hints --
one fact in two places. It also meant every non-Kaivix business got
Kaivix's wording, or the generic fallback for any field Kaivix does not
define.
"""

import unittest
from types import SimpleNamespace

import yaml

from core_ai.business_config import CONFIG_ROOT, BusinessConfigRepository, DEFAULT_BUSINESS_ID
from core_ai.planning_engine import PlanningEngine
from core_ai.stages import ConversationStage


def _stub_config(fields):
    return SimpleNamespace(
        qualification=SimpleNamespace(
            fields=[
                SimpleNamespace(id=field_id, prompt_hint=hint, required=True)
                for field_id, hint in fields
            ]
        )
    )


def _plan_for_missing(engine, missing_fields, last_assistant_message=""):
    return engine.plan(
        stage=ConversationStage.QUALIFICATION,
        intent="unknown",
        goal="qualification",
        lead=SimpleNamespace(objections=[], buying_signals=[], temperature="Cold", score=0),
        qualification={"missing": missing_fields, "qualified": False},
        working_memory=SimpleNamespace(last_assistant_message=last_assistant_message),
    )


class TestFieldQuestionsComeFromQualificationYaml(unittest.TestCase):
    def test_default_hints_match_kaivix_qualification_yaml_exactly(self):
        """
        The single-source-of-truth assertion: read the YAML directly and
        require PlanningEngine's hints to be that same mapping.
        """
        raw = yaml.safe_load(
            (CONFIG_ROOT / DEFAULT_BUSINESS_ID / "qualification.yaml").read_text(
                encoding="utf-8"
            )
        )
        expected = {
            field["id"]: field["prompt_hint"] for field in raw["fields"]
        }

        engine = PlanningEngine()

        self.assertEqual(engine._field_questions, expected)

    def test_hints_match_the_loaded_business_config(self):
        business_config = BusinessConfigRepository().load(DEFAULT_BUSINESS_ID)
        engine = PlanningEngine(business_config=business_config)

        for field in business_config.qualification.fields:
            with self.subTest(field=field.id):
                self.assertEqual(
                    engine._field_questions[field.id], field.prompt_hint
                )

    def test_kaivix_next_question_is_unchanged_by_the_refactor(self):
        """
        Behavior parity: the five hardcoded strings that were removed.
        """
        engine = PlanningEngine()

        for field_id, expected in [
            ("name", "Ask for their name."),
            ("email", "Ask for an email address so we can follow up."),
            ("company", "Ask what company or business they represent."),
            ("budget", "Ask about their budget for this kind of solution."),
            ("timeline", "Ask about their timeline for getting started."),
        ]:
            with self.subTest(field=field_id):
                plan = _plan_for_missing(engine, [field_id])
                self.assertEqual(plan.next_question, expected)
                self.assertEqual(plan.strategy, f"collect_missing_field:{field_id}")


class TestFieldQuestionsFollowTheBusiness(unittest.TestCase):
    def test_another_business_gets_its_own_wording(self):
        engine = PlanningEngine(
            business_config=_stub_config(
                [
                    ("name", "Ask for their name."),
                    ("phone", "Ask for a phone number for delivery updates."),
                ]
            )
        )

        plan = _plan_for_missing(engine, ["phone"])

        self.assertEqual(
            plan.next_question, "Ask for a phone number for delivery updates."
        )

    def test_a_field_kaivix_does_not_define_is_no_longer_a_generic_fallback(self):
        """
        Previously "phone" hit the hardcoded dict, missed, and fell back
        to the generic string even though the business had a real hint.
        """
        engine = PlanningEngine(
            business_config=_stub_config(
                [("phone", "Ask for a phone number for delivery updates.")]
            )
        )

        plan = _plan_for_missing(engine, ["phone"])

        self.assertNotEqual(
            plan.next_question, PlanningEngine._DEFAULT_FIELD_QUESTION
        )

    def test_unknown_field_still_falls_back_to_the_generic_question(self):
        engine = PlanningEngine(business_config=_stub_config([("name", "Ask their name.")]))

        plan = _plan_for_missing(engine, ["something_unmapped"])

        self.assertEqual(plan.next_question, PlanningEngine._DEFAULT_FIELD_QUESTION)

    def test_config_without_a_qualification_section_does_not_break_planning(self):
        engine = PlanningEngine(business_config=SimpleNamespace())

        plan = _plan_for_missing(engine, ["name"])

        self.assertEqual(plan.next_question, PlanningEngine._DEFAULT_FIELD_QUESTION)

    def test_field_without_a_prompt_hint_falls_back(self):
        engine = PlanningEngine(
            business_config=SimpleNamespace(
                qualification=SimpleNamespace(
                    fields=[SimpleNamespace(id="name", prompt_hint="", required=True)]
                )
            )
        )

        plan = _plan_for_missing(engine, ["name"])

        self.assertEqual(plan.next_question, PlanningEngine._DEFAULT_FIELD_QUESTION)


class TestRepeatQuestionAvoidanceStillWorks(unittest.TestCase):
    """
    _plan_qualification compares the candidate hint against the last
    assistant message; that comparison now uses config-derived hints.
    """

    def test_skips_to_the_next_field_when_the_hint_was_just_asked(self):
        engine = PlanningEngine()

        plan = _plan_for_missing(
            engine,
            ["name", "email"],
            last_assistant_message="Ask for their name.",
        )

        self.assertEqual(plan.strategy, "collect_missing_field:email")
        self.assertEqual(
            plan.next_question, "Ask for an email address so we can follow up."
        )

    def test_does_not_skip_when_the_hint_was_not_just_asked(self):
        engine = PlanningEngine()

        plan = _plan_for_missing(
            engine,
            ["name", "email"],
            last_assistant_message="Something entirely unrelated.",
        )

        self.assertEqual(plan.strategy, "collect_missing_field:name")


if __name__ == "__main__":
    unittest.main()
