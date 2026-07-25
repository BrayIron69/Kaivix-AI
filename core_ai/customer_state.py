from dataclasses import dataclass, asdict, field


@dataclass
class CustomerState:
    """
    Canonical state object for everything known about a customer.

    This is the long-term replacement for LeadProfile.
    """

    # Identity
    name: str = ""
    email: str = ""
    phone: str = ""

    # Canonical field
    company: str = ""

    # Legacy compatibility
    business: str = ""

    industry: str = ""
    role: str = ""

    # Business
    employees: str = ""
    locations: str = ""
    revenue: str = ""

    # Needs
    pain_points: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    desired_outcomes: list[str] = field(default_factory=list)

    # Qualification
    budget: str = ""
    timeline: str = ""
    authority: str = ""
    urgency: str = ""

    # Sales intelligence
    temperature: str = "Cold"
    confidence: float = 0.0
    score: int = 0
    score_reasons: list[str] = field(default_factory=list)
    buying_signals: list[str] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)

    # Conversation
    stage: str = "greeting"
    intent: str = "unknown"
    summary: str = ""
    last_questions: list[str] = field(default_factory=list)
    recommended_action: str = ""

    # Memory / CRM
    known_facts: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    status: str = "New"
    priority: str = "Cold"
    notes: str = ""
    last_contacted: str | None = None
    created_at: str | None = None

    def update(self, **kwargs):
        """
        Update only meaningful values.
        Empty strings, None, and empty lists are ignored.
        """
        for key, value in kwargs.items():
            if not hasattr(self, key):
                continue

            if value in (None, "", [], {}):
                continue

            current = getattr(self, key)

            if isinstance(current, list):
                if isinstance(value, list):
                    if value:
                        setattr(self, key, value)
                else:
                    setattr(self, key, [value])
            else:
                setattr(self, key, value)

    def to_dict(self):
        return asdict(self)

    def is_empty(self):
        for value in self.to_dict().values():
            if value not in ("", None, [], {}, 0, 0.0, "Cold", "New", "greeting", "unknown"):
                return False
        return True