import tempfile
import unittest
from pathlib import Path

from core_ai.business_config import BusinessConfigError, BusinessConfigRepository


def _write_minimal_identity_and_persona(business_dir: Path, business_id: str) -> None:
    business_dir.mkdir(parents=True)
    (business_dir / "identity.yaml").write_text(
        f"business_id: {business_id}\n"
        'business_name: "Business X"\n'
        'industry: "Testing"\n'
        'description: "A test business."\n'
        'timezone: "UTC"\n'
        'locale: "en-US"\n',
        encoding="utf-8",
    )
    (business_dir / "persona.yaml").write_text(
        'ai_name: "Test Agent"\n'
        'role: "Assistant"\n'
        'tone: "Neutral"\n'
        'formality: "Neutral"\n'
        'identity_statement: "You are a test assistant."\n',
        encoding="utf-8",
    )


class TestBusinessConfigRepositoryDefaultFallbackFailure(unittest.TestCase):
    """
    _get_default_sections() falls back to Kaivix's own config files when
    another business is missing an optional file. If Kaivix's own
    directory (under whatever config_root is in use) is ALSO missing that
    file, construction used to fall through to a bare model_cls() call,
    which raised an unhandled pydantic.ValidationError for any model with
    required fields instead of this project's own BusinessConfigError
    pattern used everywhere else in this file. This proves the fix: a
    clear, attributed BusinessConfigError instead of an opaque crash three
    layers removed from the actual cause.

    persona.yaml is now a required-per-business file (no fallback at all),
    so it can no longer exercise this fallback-crash path -- guardrails.yaml
    is used instead, since GuardrailsConfig still goes through
    _get_default_sections() and its bare model_cls() default is fine on its
    own, so the crash only happens with an option that has required fields.
    QualificationSchema has no required fields, so it wouldn't trigger the
    original bug either; a model with a required field is needed here.
    """

    def test_missing_kaivix_default_raises_business_config_error_not_validation_error(self):
        with tempfile.TemporaryDirectory() as tmp_config_root:
            tmp_config_root = Path(tmp_config_root)

            # business-x supplies only identity.yaml and persona.yaml --
            # a real incomplete-onboarding scenario (no knowledge.yaml).
            business_dir = tmp_config_root / "business-x"
            _write_minimal_identity_and_persona(business_dir, "business-x")

            # Deliberately no "kaivix" directory at all under this
            # config_root -- the exact condition that crashed before.
            repo = BusinessConfigRepository(config_root=tmp_config_root)

            with self.assertRaises(BusinessConfigError) as ctx:
                repo.load("business-x")

            message = str(ctx.exception)
            self.assertIn("knowledge.yaml", message)
            self.assertIn("namespace", message)  # KnowledgeConfig's required field


class TestBusinessConfigRepositoryRequiresPersona(unittest.TestCase):
    """
    Decision #014: persona.yaml is required per business, exactly like
    identity.yaml -- no fallback to Kaivix's own persona exists anymore.
    A business with only identity.yaml must fail loudly, whether or not a
    kaivix/ fallback directory happens to be present.
    """

    def test_missing_persona_raises_business_config_error_without_kaivix_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_config_root:
            tmp_config_root = Path(tmp_config_root)

            business_dir = tmp_config_root / "business-x"
            business_dir.mkdir(parents=True)
            (business_dir / "identity.yaml").write_text(
                "business_id: business-x\n"
                'business_name: "Business X"\n'
                'industry: "Testing"\n'
                'description: "A test business with no persona.yaml."\n'
                'timezone: "UTC"\n'
                'locale: "en-US"\n',
                encoding="utf-8",
            )

            # No "kaivix" directory at all -- proves there is no fallback
            # path for persona to reach for, unlike the optional files.
            repo = BusinessConfigRepository(config_root=tmp_config_root)

            with self.assertRaises(BusinessConfigError) as ctx:
                repo.load("business-x")

            message = str(ctx.exception)
            self.assertIn("persona.yaml", message)
            self.assertIn("is required and was not found", message)
            self.assertIn("business-x", message)

    def test_missing_persona_raises_business_config_error_with_kaivix_fallback_present(self):
        with tempfile.TemporaryDirectory() as tmp_config_root:
            tmp_config_root = Path(tmp_config_root)

            business_dir = tmp_config_root / "business-x"
            business_dir.mkdir(parents=True)
            (business_dir / "identity.yaml").write_text(
                "business_id: business-x\n"
                'business_name: "Business X"\n'
                'industry: "Testing"\n'
                'description: "A test business with no persona.yaml."\n'
                'timezone: "UTC"\n'
                'locale: "en-US"\n',
                encoding="utf-8",
            )

            # kaivix/ DOES have its own persona.yaml here -- proves the
            # missing-persona failure happens regardless, since there is
            # no fallback path for persona anymore.
            kaivix_dir = tmp_config_root / "kaivix"
            _write_minimal_identity_and_persona(kaivix_dir, "kaivix")

            repo = BusinessConfigRepository(config_root=tmp_config_root)

            with self.assertRaises(BusinessConfigError) as ctx:
                repo.load("business-x")

            message = str(ctx.exception)
            self.assertIn("persona.yaml", message)
            self.assertIn("is required and was not found", message)
            self.assertIn("business-x", message)


if __name__ == "__main__":
    unittest.main()
