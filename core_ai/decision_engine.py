from core_ai.intents import Intent
from core_ai.intent_detector import IntentDetector


class DecisionEngine:
    """
    Determines the user's intent using the IntentDetector.
    """

    def __init__(self):
        self.intent_detector = IntentDetector()

    def detect_intent(self, message: str) -> Intent:
        return self.intent_detector.detect(message)

    def should_use_llm_for_intent(self, intent: Intent) -> bool:
        return intent == Intent.UNKNOWN