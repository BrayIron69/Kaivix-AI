import unittest
from types import SimpleNamespace

from core_ai.business_config import QualificationField, QualificationSchema
from core_ai.lead_profile import LeadProfile
from core_ai.qualification_engine import QualificationEngine


class TestQualificationEngineDefault(unittest.TestCase):
    """No-args construction must still produce Kaivix's original 5-field
    schema, in the same order, with identical qualification_progress
    behavior to before this milestone."""

    def test_default_required_fields_match_kaivix_schema_order(self):
        engine = QualificationEngine()
        self.assertEqual(
            engine.required_fields,
            ["name", "email", "company", "budget", "timeline"],
        )

    def test_qualification_progress_matches_prior_behavior(self):
        engine = QualificationEngine()
        lead = LeadProfile(name="Alice", email="alice@example.com", company="Acme")
        # budget/timeline left blank -> still missing

        progress = engine.qualification_progress(lead)

        self.assertEqual(progress["collected"], 3)
        self.assertEqual(progress["total"], 5)
        self.assertEqual(progress["missing"], ["budget", "timeline"])
        self.assertFalse(progress["qualified"])
        self.assertEqual(progress["completion_percentage"], 60.0)

        self.assertFalse(engine.is_qualified(lead))
        self.assertEqual(engine.get_missing_fields(lead), ["budget", "timeline"])


class TestQualificationEngineSchemaDriven(unittest.TestCase):
    """Proves required_fields is actually derived from business_config,
    not still hardcoded, by passing a schema with a different field set."""

    def test_custom_schema_overrides_default_fields(self):
        custom_schema = QualificationSchema(
            fields=[
                QualificationField(id="name", prompt_hint="Ask for their name.", required=True),
                QualificationField(id="email", prompt_hint="Ask for their email.", required=True),
            ]
        )
        business_config = SimpleNamespace(qualification=custom_schema)

        engine = QualificationEngine(business_config=business_config)

        self.assertEqual(engine.required_fields, ["name", "email"])

        lead = LeadProfile(name="Bob", email="", company="Acme", budget="10k", timeline="Q3")
        progress = engine.qualification_progress(lead)

        self.assertEqual(progress["collected"], 1)
        self.assertEqual(progress["total"], 2)
        self.assertEqual(progress["missing"], ["email"])
        self.assertFalse(progress["qualified"])
        self.assertEqual(progress["completion_percentage"], 50.0)


if __name__ == "__main__":
    unittest.main()
