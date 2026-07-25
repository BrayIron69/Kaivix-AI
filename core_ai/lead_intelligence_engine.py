from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core_ai.customer_state import CustomerState


@dataclass
class LeadIntelligenceResult:
    temperature: str
    confidence: float
    score: int
    score_reasons: List[str]
    next_best_action: str
    summary: str


class LeadIntelligenceEngine:
    """
    Converts a CustomerState into sales intelligence.

    This is deterministic and rule-based for now.
    Later it can be augmented with AI or ML without changing
    the public interface.
    """

    def analyze(self, state: CustomerState) -> LeadIntelligenceResult:
        score = 0
        reasons: List[str] = []

        # Identity / contactability
        if state.email:
            score += 15
            reasons.append("email collected")
        if state.phone:
            score += 5
            reasons.append("phone collected")
        if state.name:
            score += 5
            reasons.append("name collected")
        if state.company:
            score += 10
            reasons.append("company identified")
        if state.industry:
            score += 5
            reasons.append("industry identified")
        if state.role:
            score += 5
            reasons.append("role identified")

        # Qualification
        if state.budget:
            score += 20
            reasons.append("budget mentioned")
        if state.timeline:
            score += 15
            reasons.append("timeline mentioned")
        if state.authority:
            score += 10
            reasons.append("authority known")
        if state.urgency:
            score += 10
            reasons.append("urgency detected")

        # Needs / intent
        if state.pain_points:
            score += 10
            reasons.append("pain points identified")
        if state.goals:
            score += 5
            reasons.append("business goals identified")
        if state.desired_outcomes:
            score += 5
            reasons.append("desired outcomes identified")

        # Sales signals
        if state.buying_signals:
            score += min(20, 5 * len(state.buying_signals))
            reasons.append("buying signals detected")

        if state.objections:
            score += 0
            reasons.append("objections present")

        # Temperature
        if score >= 75:
            temperature = "Hot"
        elif score >= 45:
            temperature = "Warm"
        else:
            temperature = "Cold"

        # Confidence
        confidence = min(1.0, round(score / 100.0, 2))

        # Next best action
        next_best_action = self._determine_next_best_action(state, temperature)

        # Summary
        summary = self._build_summary(state, temperature, next_best_action)

        return LeadIntelligenceResult(
            temperature=temperature,
            confidence=confidence,
            score=score,
            score_reasons=reasons,
            next_best_action=next_best_action,
            summary=summary,
        )

    def apply(self, state: CustomerState) -> CustomerState:
        """
        Analyze the state and write the intelligence fields back
        into the same object.
        """
        result = self.analyze(state)

        state.temperature = result.temperature
        state.confidence = result.confidence
        state.score = result.score
        state.score_reasons = result.score_reasons
        state.recommended_action = result.next_best_action
        state.summary = result.summary

        return state

    def _determine_next_best_action(
        self,
        state: CustomerState,
        temperature: str,
    ) -> str:
        missing = self._missing_high_value_fields(state)

        if state.objections:
            return "Address objections before continuing qualification."

        if temperature == "Hot" and len(missing) <= 1:
            return "Move toward booking a meeting or demo."

        if "budget" in missing:
            return "Ask about budget."
        if "timeline" in missing:
            return "Ask about timeline."
        if "company" in missing:
            return "Ask about company or business name."
        if "email" in missing:
            return "Collect an email address."

        if state.pain_points:
            return "Explore the pain point in more detail."

        if state.buying_signals:
            return "Present the solution and suggest the next step."

        return "Continue qualification naturally."

    def _missing_high_value_fields(self, state: CustomerState) -> List[str]:
        missing = []

        if not state.company:
            missing.append("company")
        if not state.email:
            missing.append("email")
        if not state.budget:
            missing.append("budget")
        if not state.timeline:
            missing.append("timeline")

        return missing

    def _build_summary(
        self,
        state: CustomerState,
        temperature: str,
        next_best_action: str,
    ) -> str:
        parts = []

        if state.name:
            parts.append(f"Name: {state.name}")
        if state.company:
            parts.append(f"Company: {state.company}")
        if state.industry:
            parts.append(f"Industry: {state.industry}")
        if state.budget:
            parts.append(f"Budget: {state.budget}")
        if state.timeline:
            parts.append(f"Timeline: {state.timeline}")

        if state.pain_points:
            parts.append(f"Pain points: {', '.join(state.pain_points)}")
        if state.goals:
            parts.append(f"Goals: {', '.join(state.goals)}")
        if state.buying_signals:
            parts.append(f"Buying signals: {', '.join(state.buying_signals)}")
        if state.objections:
            parts.append(f"Objections: {', '.join(state.objections)}")

        parts.append(f"Temperature: {temperature}")
        parts.append(f"Next action: {next_best_action}")

        return " | ".join(parts)