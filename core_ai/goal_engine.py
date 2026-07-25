from core_ai.intents import Intent
from core_ai.stages import ConversationStage


class GoalEngine:
    """
    Determines the AI's immediate conversational goal
    based on the current stage, detected intent, and
    (optionally) the lead's computed sales intelligence.
    """

    STAGE_GOAL_MAP = {
        ConversationStage.GREETING:           Intent.GREETING,
        ConversationStage.DISCOVERY:          Intent.PRODUCT_QUESTION,
        ConversationStage.QUALIFICATION:      Intent.QUALIFICATION,
        ConversationStage.PRESENTATION:       Intent.PRODUCT_QUESTION,
        ConversationStage.OBJECTION_HANDLING: Intent.OBJECTION,
        ConversationStage.CLOSING:            Intent.MEETING_REQUEST,
        ConversationStage.FOLLOW_UP:          Intent.MEETING_REQUEST,
    }

    INTENT_OVERRIDE = {
        Intent.OBJECTION,
        Intent.BUYING_SIGNAL,
        Intent.PRICING,
        Intent.MEETING_REQUEST,
        Intent.GOODBYE,
    }

    # Lead-intelligence temperature that, once reached, steers the
    # conversation toward closing regardless of the stage-based default.
    HOT_LEAD_TEMPERATURE = "Hot"
    HOT_LEAD_GOAL = Intent.MEETING_REQUEST

    def determine_goal(
        self,
        stage: ConversationStage,
        intent: Intent,
        lead=None,
    ) -> Intent:
        """
        Determine the AI's current goal.

        Priority order:
        1. High-priority intents always win (unchanged).
        2. A lead already classified as "Hot" by LeadIntelligenceEngine
           is steered toward closing, even on a neutral intent.
        3. Otherwise fall back to the stage-based goal map (unchanged).

        `lead` is optional and backward compatible: passing nothing
        preserves the original stage/intent-only behavior.
        """
        if intent in self.INTENT_OVERRIDE:
            return intent

        if lead is not None and getattr(lead, "temperature", None) == self.HOT_LEAD_TEMPERATURE:
            return self.HOT_LEAD_GOAL

        return self.STAGE_GOAL_MAP.get(stage, intent)