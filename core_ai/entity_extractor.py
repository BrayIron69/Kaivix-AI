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

    # Spelled-out number words this extractor recognizes as part of a
    # magnitude-word budget answer ("one billion dollars", "a hundred
    # thousand"). Not exhaustive of every English number word -- covers
    # the range a real spoken budget answer plausibly uses; repeated via
    # BUDGET_MAGNITUDE_PATTERN's own grouping below so compounds like "a
    # hundred" or "twenty five" (before a magnitude word) are covered
    # too.
    _BUDGET_NUMBER_WORD = (
        r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten"
        r"|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen"
        r"|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy"
        r"|eighty|ninety|hundred)"
    )

    _BUDGET_MAGNITUDE_WORD = r"(?:thousand|million|billion)"

    # Joins two words of a spelled-out budget answer. Plain `\s+` is not
    # enough: a real call's transcript had the visitor's speech pause
    # transcribed as a stray period -- "How about one. Billion dollars?"
    # -- which `\s+` alone would refuse to bridge. Voice transcription
    # commonly inserts a comma or period at a pause with no real clause
    # break intended, so this tolerates one alongside whitespace.
    _BUDGET_WORD_JOIN = r"(?:[\s.,]+)"

    # A budget stated with a spelled-out magnitude word -- digits or
    # words on either side: "one billion dollars", "1 billion dollars",
    # "50 thousand", "a hundred thousand dollars". BUDGET_PATTERN above
    # never matches any of these: it requires either a literal `$` or a
    # digit run directly adjacent to a currency word, and "billion" /
    # "thousand" / "million" is neither a currency word nor a digit --
    # confirmed against a real call where a visitor said "one billion
    # dollars" twice and it was never captured (budget stayed in
    # QualificationEngine's missing-fields list for the rest of the
    # call).
    #
    # The currency word is optional here (unlike BUDGET_PATTERN's
    # digit-only branch, where it is required) so a bare "50 thousand"
    # still counts -- a real spoken answer to "what's your budget?" that
    # never says "dollars" out loud is common, and this extractor is
    # already context-blind everywhere else (BUDGET_PATTERN itself
    # matches "$500" wherever it appears, regardless of whether the
    # sentence is actually about budget); this is the same accepted
    # trade-off, not a new one.
    BUDGET_MAGNITUDE_PATTERN = re.compile(
        rf"\b(?:\$?\s*[\d,]+(?:\.\d+)?|{_BUDGET_NUMBER_WORD}(?:{_BUDGET_WORD_JOIN}{_BUDGET_NUMBER_WORD})*)"
        rf"{_BUDGET_WORD_JOIN}{_BUDGET_MAGNITUDE_WORD}"
        rf"(?:{_BUDGET_WORD_JOIN}(?:usd|dollars|pkr|rs))?\b",
        re.IGNORECASE,
    )

    # Normalizes a stray mid-phrase punctuation mark caught by
    # _BUDGET_WORD_JOIN (see above) back to a plain space once a match is
    # found, so a real transcription artifact like "one. Billion
    # dollars" is stored as "one Billion dollars" rather than carrying
    # the stray period into LeadProfile/the CRM verbatim.
    _BUDGET_STRAY_PUNCTUATION = re.compile(r"[.,]+(?=\s|$)")

    NAME_PATTERNS = [
        r"\bmy name is\s+([A-Za-z]+)",
        r"\bi am\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
        r"\bi'm\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
        r"\bthis is\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})",
    ]

    # (pattern, kind). The two kinds capture genuinely different things
    # and need different bounds, which is why one shared word cap left a
    # gap:
    #
    #   NAME       -- "my company is X", "I work at X". The visitor is
    #                 stating a proper name, which can legitimately be
    #                 long ("The Law Offices of Smith and Associates
    #                 LLP" is 7 words).
    #   DESCRIPTOR -- "we run a X", "I own a X". The visitor is
    #                 describing a business TYPE. Real answers are short
    #                 noun phrases ("dental clinic", "small law firm"),
    #                 and this is where run-on sentences actually arrive,
    #                 because the phrasing invites a narrative answer.
    #
    # Bounding them separately means the descriptor case can be held to a
    # tight limit without truncating a genuinely long stated name.
    _COMPANY_KIND_NAME = "name"
    _COMPANY_KIND_DESCRIPTOR = "descriptor"

    COMPANY_PATTERNS = [
        (r"\bmy company is\s+([^.,!?]+)", _COMPANY_KIND_NAME),
        (r"\bour company is\s+([^.,!?]+)", _COMPANY_KIND_NAME),
        (r"\bcompany is\s+([^.,!?]+)", _COMPANY_KIND_NAME),

        (r"\bi run\s+(?:a|an|the)?\s*([^.,!?]+)", _COMPANY_KIND_DESCRIPTOR),
        (r"\bi own\s+(?:a|an|the)?\s*([^.,!?]+)", _COMPANY_KIND_DESCRIPTOR),

        (r"\bwe run\s+(?:a|an|the)?\s*([^.,!?]+)", _COMPANY_KIND_DESCRIPTOR),
        (r"\bwe own\s+(?:a|an|the)?\s*([^.,!?]+)", _COMPANY_KIND_DESCRIPTOR),

        (r"\bi work at\s+([^.,!?]+)", _COMPANY_KIND_NAME),
        (r"\bwe work at\s+([^.,!?]+)", _COMPANY_KIND_NAME),

        (r"\bmy business is\s+([^.,!?]+)", _COMPANY_KIND_NAME),
    ]

    # Descriptive continuations that only ever follow a business type,
    # never form part of one: "a clinic IN downtown Boston", "a clinic
    # SERVING 200 patients". Applied to DESCRIPTOR captures only, so a
    # stated name is never cut on them -- "Made in Chelsea" survives
    # "my company is Made in Chelsea", and would only be clipped by
    # "we run Made in Chelsea", which is both rare and still yields the
    # recognisable "Made".
    #
    # This is what turns the run-on into a useful value rather than a
    # rejection: "we run a clinic in downtown Boston serving 200 patients
    # weekly" now extracts "clinic" instead of being discarded whole.
    _COMPANY_DESCRIPTOR_STOP_PATTERN = re.compile(
        r"\b(?:in|near|around|serving|offering|providing|specialising"
        r"|specializing|based|located|doing|handling|focused|focusing)\b",
        re.IGNORECASE,
    )

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

    # Word caps, as a last backstop for a phrasing none of the
    # boundaries above anticipate. Rejecting outright rather than
    # truncating: an arbitrary mid-phrase cut would store something the
    # visitor never said.
    #
    # A single shared cap used to sit at 8 to accommodate long stated
    # names, which left the descriptor case unguarded -- "clinic in
    # downtown Boston serving 200 patients weekly" is exactly 8 words and
    # slipped straight through. Splitting the cap by kind closes that
    # without clipping real names.
    _COMPANY_MAX_WORDS = {
        # "The Law Offices of Smith and Associates LLP" is 7.
        _COMPANY_KIND_NAME: 8,
        # Real answers here are 1-3 words ("dental clinic", "small law
        # firm"); 5 leaves room for "Smith and Sons Plumbing" arriving
        # via "we run ...".
        _COMPANY_KIND_DESCRIPTOR: 5,
    }

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
        for pattern, kind in self.COMPANY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                company = match.group(1).strip()

                # Stop at the first clause boundary, so a trailing
                # "... and need help with missed calls" is not stored as
                # part of the company name -- see _COMPANY_STOP_PATTERN.
                company = self._COMPANY_STOP_PATTERN.split(company, maxsplit=1)[0]

                # A business TYPE additionally stops at a descriptive
                # continuation ("clinic IN downtown Boston", "clinic
                # SERVING 200 patients"). Not applied to a stated name,
                # where those words can legitimately be part of it.
                if kind == self._COMPANY_KIND_DESCRIPTOR:
                    company = self._COMPANY_DESCRIPTOR_STOP_PATTERN.split(
                        company, maxsplit=1
                    )[0]

                company = company.strip().rstrip(".,!? ")

                if len(company) < 2:
                    continue

                # Still sentence-shaped despite every boundary above:
                # take nothing rather than record a sentence as a company
                # (an under-extraction, not a fabrication -- the same
                # stance NAME_PATTERNS takes).
                if len(company.split()) > self._COMPANY_MAX_WORDS[kind]:
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
        else:
            budget_magnitude = self.BUDGET_MAGNITUDE_PATTERN.search(text)
            if budget_magnitude:
                cleaned = self._BUDGET_STRAY_PUNCTUATION.sub("", budget_magnitude.group(0))
                state.budget = " ".join(cleaned.split())

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