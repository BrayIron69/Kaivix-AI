import re


class AIDisclosureDetector:
    """
    Detects (1) a visitor asking whether they are talking to an AI, and
    (2) a response claiming to be human.

    Built after a real test conversation in which a visitor asked "are
    you ai" and Bray replied "I'm Bray, a real human sales rep here at
    Kaivix Labs", then invented the surname "Iron" when pushed for a
    full name and repeated the human claim again later in the same
    conversation.

    That was not a hallucination. The prompt literally instructed it:
    persona.yaml's identity_statement (and PromptBuilder.AGENT_IDENTITY,
    its verbatim twin) contained the line "You are NOT a bot. You are a
    real human sales rep having a genuine business conversation." Both
    have been corrected, which removes the cause rather than papering
    over it -- this module is the guarantee that survives a future
    persona edit, a model that drifts, or a phrasing nobody anticipated.

    Why a deterministic gate rather than a prompt rule alone: this
    codebase has measured, repeatedly, that "never do X" in a prompt is
    an instruction the model can decline -- ~2.7% of runs quoted invented
    prices despite rule #7 (see core_ai/pricing_guard.py), and rule #12's
    fabricated-action ban held only about half the time in live testing
    (see core_ai/unbacked_action_detector.py). Misrepresenting a bot as a
    human in a sales conversation is a legal exposure, not a quality
    regression: several US states require disclosure on request in a
    sales/persuasion context, California's SB 1001 being the most cited.
    A guarantee that holds "about half the time" is not a guarantee.

    Deliberately does NOT claim the surname check below is a general
    solution to invented biographical detail. It catches the exact,
    reported failure (a fabricated surname attached to the assistant's
    own name) and nothing wider; the broader defense against inventing a
    person is the corrected identity statement itself.
    """

    # A visitor directly asking what they are talking to. Regex rather
    # than a flat phrase list (the style intent_detector.py and
    # unbacked_action_detector.py use) because "in any phrasing" is the
    # actual requirement here: the productive constructions matter more
    # than any list of exact sentences, and a missed phrasing is a
    # response that misrepresents a bot as a person.
    _DIRECT_QUESTION_PATTERNS = [
        # "are you ai", "are you a bot", "are you human", "are you real",
        # "r u a robot"
        re.compile(
            r"\b(?:are|r)\s+(?:you|u)\s+(?:an?\s+)?(?:really\s+|actually\s+)?"
            r"(?:ai|a\.i\.|bot|robot|machine|computer|program|chat\s*bot|"
            r"algorithm|llm|language\s+model|gpt|chat\s*gpt|human|person|"
            r"real\s+person|real\s+human|actual\s+person|actual\s+human|real)\b",
            re.IGNORECASE,
        ),
        # "am i talking to a bot", "am i speaking with a real person",
        # "am i chatting with an ai"
        re.compile(
            r"\bam\s+(?:i|l)\s+(?:talking|speaking|chatting|texting|typing|dealing)\s+"
            r"(?:to|with)\s+(?:an?\s+)?(?:ai|a\.i\.|bot|robot|machine|computer|"
            r"chat\s*bot|algorithm|llm|human|person|real\s+person|real\s+human|"
            r"actual\s+person|actual\s+human)\b",
            re.IGNORECASE,
        ),
        # "is this a bot", "is this ai", "is this automated",
        # "is this a real person"
        re.compile(
            r"\b(?:is|are)\s+(?:this|that|it)\s+(?:an?\s+)?(?:ai|a\.i\.|bot|robot|"
            r"machine|chat\s*bot|automated|auto[-\s]?generated|real\s+person|"
            r"real\s+human|human|person)\b",
            re.IGNORECASE,
        ),
        # "who am i speaking with", "who am i talking to"
        re.compile(
            r"\bwho\s+am\s+(?:i|l)\s+(?:talking|speaking|chatting|dealing)\s+"
            r"(?:to|with)\b",
            re.IGNORECASE,
        ),
        # Statement-form accusation: "you're a bot", "you are an ai".
        # Must disclose the same as a question -- a visitor who has
        # worked it out and says so deserves confirmation, not a dodge.
        re.compile(
            r"\b(?:you're|youre|you\s+are|you\s+r|ur)\s+(?:an?\s+)?(?:ai|a\.i\.|bot|"
            r"robot|machine|chat\s*bot|llm|language\s+model)\b",
            re.IGNORECASE,
        ),
        # "human or bot?", "ai or human?", "person or a machine"
        re.compile(
            r"\b(?:human|person|ai|a\.i\.|bot|robot|machine)\s+or\s+(?:an?\s+)?"
            r"(?:human|person|ai|a\.i\.|bot|robot|machine)\b",
            re.IGNORECASE,
        ),
    ]

    # A response asserting, in the first person, that it is a person.
    # Every pattern is anchored to a first-person self-claim rather than
    # the bare noun: the knowledge base legitimately discusses "your
    # human staff" and "replacing a human employee", and matching those
    # would replace correct, on-topic answers.
    _FALSE_HUMANITY_PATTERNS = [
        # "i'm human", "i am a real human", "i'm a real person",
        # "i am an actual person"
        re.compile(
            r"\bi(?:'m|\s+am)\s+(?:an?\s+)?(?:real|actual|genuine|live)?\s*"
            r"(?:human|person|guy|gal|woman|man)\b",
            re.IGNORECASE,
        ),
        # "i'm not a bot", "i am not an ai", "i'm not a robot"
        re.compile(
            r"\bi(?:'m|\s+am)\s+not\s+(?:an?\s+)?(?:ai|a\.i\.|bot|robot|machine|"
            r"computer|chat\s*bot|program|algorithm)\b",
            re.IGNORECASE,
        ),
        # "you're talking to a human", "you're speaking with a real person"
        re.compile(
            r"\byou(?:'re|\s+are)\s+(?:talking|speaking|chatting|dealing)\s+"
            r"(?:to|with)\s+(?:an?\s+)?(?:real\s+|actual\s+)?(?:human|person)\b",
            re.IGNORECASE,
        ),
        # "yes, a real person here", "definitely a real person"
        re.compile(
            r"\b(?:yes|yep|yeah|indeed|definitely|certainly),?\s+(?:an?\s+)?"
            r"(?:real\s+|actual\s+)?(?:human|person)\b",
            re.IGNORECASE,
        ),
    ]

    # "a real human sales rep" -- the exact incident phrasing, and the
    # one shape the first-person patterns above genuinely cannot catch:
    # in "I'm Bray, a real human sales rep here at Kaivix Labs" the
    # claim is detached from the "I'm" by the agent's own name, so no
    # anchored pattern reaches it.
    #
    # Matched per-sentence and ONLY alongside _SELF_REFERENCE_PATTERN
    # below, never on its own. On its own it is genuinely dangerous
    # here: this product's whole pitch is AI employees replacing human
    # staff, so "our AI can take over what a human agent does today" is
    # a correct, on-topic answer that an unanchored version would
    # replace with an identity disclosure nobody asked for. Caught by
    # tests/test_multi_business_serving.py, which stubs the LLM to echo
    # the system prompt back and tripped an earlier, unanchored draft of
    # this rule.
    _HUMAN_ROLE_PATTERN = re.compile(
        r"\b(?:real\s+|actual\s+|genuine\s+)?human\s+(?:sales\s+)?"
        r"(?:rep|representative|agent|advisor|consultant)\b",
        re.IGNORECASE,
    )

    # What turns a mention of a human role into a claim to BE one.
    _SELF_REFERENCE_PATTERN = re.compile(
        r"\b(?:i'm|i\s+am|my\s+name\s+is|name's|this\s+is\s+\w+|speaking|here\s+at)\b",
        re.IGNORECASE,
    )

    _SENTENCE_SPLIT_PATTERN = re.compile(r"[.!?\n]+")

    def __init__(self, ai_name: str = ""):
        # Used only by claims_invented_surname below. Config-driven
        # rather than the literal "Bray", since this engine serves more
        # than one business (see core_ai/business_config.py).
        self.ai_name = (ai_name or "").strip()

    def asks_whether_ai(self, message: str) -> bool:
        """
        True when the visitor is directly asking what they are talking
        to, in any of the phrasings above.

        Deliberately does NOT match "is there a real person I can talk
        to" or the other UnbackedActionDetector.HUMAN_HANDOFF_PHRASES:
        those are requests to be handed to a person, which already have
        their own honest decline, and stealing them here would replace a
        more useful answer with a less useful one.
        """
        text = message or ""
        return any(pattern.search(text) for pattern in self._DIRECT_QUESTION_PATTERNS)

    def claims_to_be_human(self, response: str) -> bool:
        """True when `response` asserts, in the first person, that it is a person."""
        text = response or ""

        if any(pattern.search(text) for pattern in self._FALSE_HUMANITY_PATTERNS):
            return True

        # The detached-claim case ("I'm <name>, a real human sales rep"),
        # evaluated per sentence so the self-reference and the role
        # claim have to occur together rather than merely both appearing
        # somewhere in a long response.
        for sentence in self._SENTENCE_SPLIT_PATTERN.split(text):
            if self._HUMAN_ROLE_PATTERN.search(sentence) and self._SELF_REFERENCE_PATTERN.search(
                sentence
            ):
                return True

        return False

    def claims_invented_surname(self, response: str) -> bool:
        """
        True when the response attaches a surname to the assistant's own
        name -- "I'm Bray Iron", "my name is Bray Iron".

        The reported incident's invented surname is traceable to real
        text in the prompt: the booking link
        (calendly.com/brayiron-kaivixlab) and the contact address
        (brayiron@kaivixlab.com) both contain "brayiron", which reads as
        a first and last name to a model asked for a full one. Both
        values are legitimately in the prompt and are not being removed,
        so the claim itself is what gets caught.

        Scoped to self-identification contexts only ("I'm X", "my name
        is X") and to a Capitalised following word, so "I'm Bray from
        Kaivix Labs" and "I'm Bray, a sales agent" do not match.
        """
        if not self.ai_name:
            return False

        text = response or ""
        # The self-identification prefix and the agent's own name are
        # matched case-insensitively via an inline (?i:...) group, but
        # the surname itself stays case-SENSITIVE outside it: requiring
        # a Capitalised word is exactly what separates "I'm Bray Iron"
        # from "I'm Bray from Kaivix Labs".
        pattern = re.compile(
            r"(?i:\b(?:i'm|i\s+am|my\s+name\s+is|my\s+full\s+name\s+is|this\s+is|"
            r"it's|name's)\s+"
            + re.escape(self.ai_name)
            + r"\s+)"
            + r"[A-Z][a-z]+\b"
        )
        return bool(pattern.search(text))
