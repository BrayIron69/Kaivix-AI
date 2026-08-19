import re

from core_ai.customer_state import CustomerState


class EntityExtractor:
    """
    Extracts structured information from user messages.

    This version is intentionally deterministic.
    Later this extractor can be upgraded to an LLM-assisted
    extractor without changing the rest of the platform.
    """

    EMAIL_PATTERN = re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    )

    PHONE_PATTERN = re.compile(
        r"(\+?\d[\d\s().-]{7,}\d)"
    )

    BUDGET_PATTERN = re.compile(
        r"(\$ ?[\d,]+(?:\.\d+)?(?:\s*/\s*month)?|\d+\s*(?:usd|dollars|pkr|rs))",
        re.IGNORECASE,
    )

    NAME_PATTERNS = [
        r"\bmy name is\s+([A-Za-z]+)",
        r"\bi am\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
        r"\bi'm\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
        r"\bthis is\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
    ]

    COMPANY_PATTERNS = [
        r"\bmy company is\s+([^.,!?]+)",
        r"\bour company is\s+([^.,!?]+)",
        r"\bcompany is\s+([^.,!?]+)",

        r"\bi run\s+(?:a|an|the)?\s*([^.,!?]+)",
        r"\bi own\s+(?:a|an|the)?\s*([^.,!?]+)",

        r"\bwe run\s+(?:a|an|the)?\s*([^.,!?]+)",
        r"\bwe own\s+(?:a|an|the)?\s*([^.,!?]+)",

        r"\bi work at\s+([^.,!?]+)",
        r"\bwe work at\s+([^.,!?]+)",

        r"\bmy business is\s+([^.,!?]+)",
    ]

    ROLE_PATTERNS = [
        r"\b(founder|owner|ceo|director|manager|doctor|dentist|lawyer|principal|president)\b",
    ]

    TIMELINE_PATTERNS = [
        "today",
        "this week",
        "next week",
        "this month",
        "next month",
        "few months",
        "ready now",
        "asap",
        "immediately",
        "this quarter",
        "next quarter",
    ]

    INDUSTRY_KEYWORDS = {
        "dental": "Dental",
        "clinic": "Healthcare",
        "medical": "Healthcare",
        "healthcare": "Healthcare",
        "agency": "Agency",
        "marketing": "Marketing",
        "software": "Software",
        "saas": "Software",
        "law": "Legal",
        "lawyer": "Legal",
        "construction": "Construction",
        "restaurant": "Hospitality",
        "real estate": "Real Estate",
        "retail": "Retail",
        "ecommerce": "Ecommerce",
        "manufacturing": "Manufacturing",
    }

    PAIN_POINT_KEYWORDS = [
        "missed calls",
        "reduce missed calls",
        "missing calls",
        "too many calls",
        "customer inquiries",
        "manual follow up",
        "manual follow-up",
        "lead qualification",
        "support tickets",
        "customer support",
        "booking appointments",
        "missed appointments",
        "book more appointments",
        "save time",
        "increase efficiency",
        "reduce workload",
    ]

    GOAL_KEYWORDS = [
        "grow",
        "increase sales",
        "more leads",
        "book more appointments",
        "improve conversions",
        "scale",
        "save time",
        "reduce costs",
        "improve customer experience",
    ]

    BUYING_SIGNAL_KEYWORDS = [
        "pricing",
        "proposal",
        "book a demo",
        "schedule a demo",
        "next steps",
        "how soon",
        "when can we start",
        "budget",
        "implement",
        "integration",
        "sounds good",
        "let's do it",
    ]

    OBJECTION_KEYWORDS = [
        "too expensive",
        "expensive",
        "already have",
        "need more info",
        "not sure",
        "concerned",
        "worry",
        "maybe later",
    ]

    URGENCY_KEYWORDS = [
        "urgent",
        "today",
        "asap",
        "immediately",
        "this week",
        "next week",
        "ready now",
    ]

    def extract(
        self,
        message: str,
        state: CustomerState | None = None,
    ) -> CustomerState:

        if state is None:
            state = CustomerState()

        text = message.strip()
        lower = text.lower()

        # -----------------------------
        # Email
        # -----------------------------
        email = self.EMAIL_PATTERN.search(text)
        if email:
            state.email = email.group(0)

        # -----------------------------
        # Phone
        # -----------------------------
        phone = self.PHONE_PATTERN.search(text)
        if phone:
            state.phone = phone.group(1).strip()

        # -----------------------------
        # Name
        # -----------------------------
        # NAME_PATTERNS capture up to three words after the lead-in
        # phrase, which is right for "I'm Alice Smith" but over-captures
        # everything else: "I'm interested in learning about..." yielded
        # the name "Interested In Learning" (which reached a real
        # visitor's inbox as "Hi Interested In Learning,"), and even a
        # genuine name ran on into the rest of the sentence -- "I am Dana
        # from WidgetCo" yielded "Dana From Widgetco".
        #
        # Matching stays case-insensitive so the lead-in phrase still
        # matches however it was typed, but the captured group is a
        # literal slice of `text` (never lowercased), so its real casing
        # survives -- and only the *leading run of capitalized words* is
        # kept. A real typed name is capitalized; the ordinary sentence
        # words that follow it are not, so they stop the run.
        #
        # A visitor who types their name in all lowercase is not picked
        # up here -- an under-extraction, not a fabrication, consistent
        # with this extractor never inventing a value it isn't
        # reasonably sure of.
        for pattern in self.NAME_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue

            name_words = []
            for word in match.group(1).split():
                if not word[:1].isupper():
                    break
                name_words.append(word)

            if name_words:
                state.name = " ".join(name_words).title()
                break

        # -----------------------------
        # Company
        # -----------------------------
        for pattern in self.COMPANY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                company = match.group(1).strip()

                company = re.split(
                    r"\b(my email is|email is|we want|i want|our budget|budget|phone|contact)\b",
                    company,
                    flags=re.IGNORECASE,
                )[0].strip()

                company = company.rstrip(".,!? ")

                if len(company) >= 2:
                    state.company = company
                    state.business = company
                    break
        # -----------------------------
        # Role
        # -----------------------------
        role_match = re.search(
            self.ROLE_PATTERNS[0],
            lower,
            re.IGNORECASE,
        )

        if role_match:
            state.role = role_match.group(1).title()

        # -----------------------------
        # Budget
        # -----------------------------
        budget = self.BUDGET_PATTERN.search(text)
        if budget:
            state.budget = budget.group(1).strip()

        # -----------------------------
        # Timeline
        # -----------------------------
        for keyword in self.TIMELINE_PATTERNS:
            if keyword in lower:
                state.timeline = keyword
                break

        # -----------------------------
        # Industry
        # -----------------------------
        for keyword, industry in self.INDUSTRY_KEYWORDS.items():
            if keyword in lower:
                state.industry = industry
                break

        # -----------------------------
        # Pain Points
        # -----------------------------
        for keyword in self.PAIN_POINT_KEYWORDS:
            if keyword in lower:
                if keyword not in state.pain_points:
                    state.pain_points.append(keyword)

        # -----------------------------
        # Goals
        # -----------------------------
        for keyword in self.GOAL_KEYWORDS:
            if keyword in lower:
                if keyword not in state.goals:
                    state.goals.append(keyword)

        # -----------------------------
        # Desired Outcomes
        # -----------------------------
        if any(
            phrase in lower
            for phrase in [
                "want",
                "need",
                "looking for",
            ]
        ):
            if "needs automation" not in state.desired_outcomes:
                state.desired_outcomes.append("needs automation")

        # -----------------------------
        # Buying Signals
        # -----------------------------
        for keyword in self.BUYING_SIGNAL_KEYWORDS:
            if keyword in lower:
                if keyword not in state.buying_signals:
                    state.buying_signals.append(keyword)

        # -----------------------------
        # Objections
        # -----------------------------
        for keyword in self.OBJECTION_KEYWORDS:
            if keyword in lower:
                if keyword not in state.objections:
                    state.objections.append(keyword)

        # -----------------------------
        # Urgency
        # -----------------------------
        for keyword in self.URGENCY_KEYWORDS:
            if keyword in lower:
                state.urgency = "High"
                break

        # -----------------------------
        # Known Facts
        # -----------------------------
        facts = [
            ("email", state.email),
            ("company", state.company),
            ("budget", state.budget),
            ("timeline", state.timeline),
            ("industry", state.industry),
            ("role", state.role),
        ]

        for key, value in facts:
            if value:
                fact = f"{key}:{value}"
                if fact not in state.known_facts:
                    state.known_facts.append(fact)

        return state