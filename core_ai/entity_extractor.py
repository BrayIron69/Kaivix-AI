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

    # Where a captured company value has to stop.
    #
    # COMPANY_PATTERNS capture "everything up to sentence punctuation"
    # ([^.,!?]+), which is right for "my company is Acme Co" but swallows
    # any trailing clause. A real visitor answering "we run a dental
    # clinic and need help with missed calls" had that entire phrase
    # stored as their company name and it reached both the CRM and the
    # admin dashboard that way -- the same over-capture already fixed for
    # NAME_PATTERNS, in the other place it occurs.
    #
    # Capitalization cannot be the boundary here the way it is for names:
    # "dental clinic" is a perfectly good lowercase answer to "we run
    # a ___". The boundary that works for a company is the start of the
    # next CLAUSE, and the two kinds are deliberately different in
    # strictness:
    #
    #   - Subordinators and relative pronouns (because, which, that, ...)
    #     cut unconditionally. These effectively never appear inside a
    #     real company name.
    #   - Coordinators (and, but, so, ...) cut ONLY when what follows
    #     looks like a new clause -- a pronoun, an auxiliary, or a
    #     need/want/looking-style verb. A bare "and" must NOT cut, or
    #     "Smith and Sons" becomes "Smith".
    #
    # The pre-existing hand-off phrases (email/budget/contact) live here
    # too, so there is one boundary definition rather than two that can
    # drift apart.
    #
    # Known trade-off: an unconditional "that"/"while" clips a company
    # genuinely containing the word (e.g. "All That Jazz" -> "All").
    # Truncating a rare real name is preferred over storing a whole
    # sentence as a company, which is what happens today.
    _COMPANY_STOP_PATTERN = re.compile(
        r"\b(?:"
        # Hand-offs to another field (pre-existing behavior)
        r"my email is\b|email is\b|we want\b|i want\b|our budget\b|budget\b"
        r"|phone\b|contact\b"
        # Subordinators / relative pronouns -- always start a new clause
        r"|because\b|since\b|although\b|though\b|whilst\b|while\b"
        r"|which\b|who\b|that\b"
        # Coordinators -- only when a new clause plainly follows
        r"|(?:and|but|so|plus|yet)\s+(?:"
        r"i|we|they|he|she|it|you"
        r"|am|are|is|was|were|be|been"
        r"|have|has|had|do|does|did"
        r"|need|needs|want|wants|look|looks|looking"
        r"|try|tries|trying|hope|hopes|hoping|require|requires"
        r"|would|could|should|will|can|might|must"
        r"|really|just|also|currently|now|still"
        r")\b"
        r")",
        re.IGNORECASE,
    )

    # Belt-and-braces cap for a phrasing the clause boundaries above do
    # not anticipate (a long run-on with no conjunction at all, e.g.
    # "we run a clinic in downtown Boston serving 200 patients weekly").
    # Deliberately generous -- "The Law Offices of Smith and Associates
    # LLP" is 7 words -- so it only rejects values no real company name
    # reaches. Rejecting outright rather than truncating: an arbitrary
    # mid-phrase cut would store something the visitor never said.
    _COMPANY_MAX_WORDS = 8

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

                # Stop at the first clause boundary, so a trailing
                # "... and need help with missed calls" is not stored as
                # part of the company name -- see _COMPANY_STOP_PATTERN.
                company = self._COMPANY_STOP_PATTERN.split(company, maxsplit=1)[0]

                company = company.strip().rstrip(".,!? ")

                if len(company) < 2:
                    continue

                # Still sentence-shaped despite the boundaries above:
                # take nothing rather than record a sentence as a company
                # (an under-extraction, not a fabrication -- the same
                # stance NAME_PATTERNS takes).
                if len(company.split()) > self._COMPANY_MAX_WORDS:
                    continue

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