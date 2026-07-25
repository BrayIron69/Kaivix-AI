from dataclasses import dataclass, field


_PLACEHOLDER_VALUES = {"string", "none", "null"}


def _clean_text(value):
    if value is None:
        return ""

    if not isinstance(value, str):
        return value

    cleaned = value.strip()

    if cleaned.lower() in _PLACEHOLDER_VALUES:
        return ""

    return cleaned


@dataclass
class Lead:
    id: int | None = None
    name: str = ""
    email: str = ""

    company: str = ""
    business: str = ""

    phone: str = ""
    industry: str = ""

    budget: str = ""
    timeline: str = ""
    pain_point: str = ""
    decision_maker: str = ""

    score: int = 0
    priority: str = "Cold"
    status: str = "New"
    notes: str = ""
    last_contacted: str | None = None
    created_at: str | None = None

    score_reasons: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.name = _clean_text(self.name)
        self.email = _clean_text(self.email)

        self.company = _clean_text(self.company)
        self.business = _clean_text(self.business)

        if not self.company and self.business:
            self.company = self.business
        if not self.business and self.company:
            self.business = self.company

        self.phone = _clean_text(self.phone)
        self.industry = _clean_text(self.industry)
        self.budget = _clean_text(self.budget)
        self.timeline = _clean_text(self.timeline)
        self.pain_point = _clean_text(self.pain_point)
        self.decision_maker = _clean_text(self.decision_maker)

        self.priority = _clean_text(self.priority) or "Cold"
        self.status = _clean_text(self.status) or "New"
        self.notes = _clean_text(self.notes)

        if self.last_contacted is not None:
            self.last_contacted = _clean_text(self.last_contacted) or None

        if self.created_at is not None:
            self.created_at = _clean_text(self.created_at) or None

        try:
            self.score = int(self.score or 0)
        except (TypeError, ValueError):
            self.score = 0

        if self.score_reasons is None:
            self.score_reasons = []

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None

        if hasattr(row, "keys"):
            data = {key: row[key] for key in row.keys()}

            return cls(
                id=data.get("id"),
                name=data.get("name", ""),
                email=data.get("email", ""),
                company=data.get("company") or data.get("business", ""),
                business=data.get("business") or data.get("company", ""),
                phone=data.get("phone", ""),
                industry=data.get("industry", ""),
                budget=data.get("budget", ""),
                timeline=data.get("timeline", ""),
                pain_point=data.get("pain_point", ""),
                decision_maker=data.get("decision_maker", ""),
                score=data.get("score", 0) or 0,
                priority=data.get("priority", "Cold") or "Cold",
                status=data.get("status", "New") or "New",
                notes=data.get("notes", ""),
                last_contacted=data.get("last_contacted"),
                created_at=data.get("created_at"),
                score_reasons=data.get("score_reasons", []) or [],
            )

        # Legacy tuple fallback, current schema order first
        if len(row) >= 17:
            return cls(
                id=row[0],
                name=row[1],
                email=row[2],
                phone=row[3],
                company=row[4],
                business=row[5],
                industry=row[6],
                budget=row[7],
                timeline=row[8],
                pain_point=row[9],
                decision_maker=row[10],
                score=row[11],
                priority=row[12],
                status=row[13],
                notes=row[14],
                last_contacted=row[15],
                created_at=row[16],
            )

        # Older fallback
        if len(row) >= 13:
            return cls(
                id=row[0],
                name=row[1],
                email=row[2],
                company=row[3],
                business=row[3],
                budget=row[4],
                timeline=row[5],
                pain_point=row[6],
                score=row[7],
                priority=row[8],
                status=row[9],
                notes=row[10],
                last_contacted=row[11],
                created_at=row[12],
            )

        raise ValueError("Unsupported lead row format.")

    def to_dict(self):
        company = self.company or self.business

        return {
            "id": self.id,
            "name": _clean_text(self.name),
            "email": _clean_text(self.email),
            "company": company,
            "business": company,
            "phone": _clean_text(self.phone),
            "industry": _clean_text(self.industry),
            "budget": _clean_text(self.budget),
            "timeline": _clean_text(self.timeline),
            "pain_point": _clean_text(self.pain_point),
            "decision_maker": _clean_text(self.decision_maker),
            "score": int(self.score or 0),
            "priority": _clean_text(self.priority) or "Cold",
            "status": _clean_text(self.status) or "New",
            "notes": _clean_text(self.notes),
            "last_contacted": _clean_text(self.last_contacted) or None,
            "created_at": _clean_text(self.created_at) or None,
            "score_reasons": list(self.score_reasons or []),
        }