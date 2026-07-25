from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LeadCreate(BaseModel):
    name: str = ""
    email: EmailStr

    company: str = ""
    business: str = ""

    phone: str = ""
    industry: str = ""

    budget: str = ""
    timeline: str = ""
    pain_point: str = ""
    decision_maker: str = ""

    notes: str = ""


class LeadUpdate(BaseModel):
    name: Optional[str] = None

    company: Optional[str] = None
    business: Optional[str] = None

    phone: Optional[str] = None
    industry: Optional[str] = None

    budget: Optional[str] = None
    timeline: Optional[str] = None
    pain_point: Optional[str] = None
    decision_maker: Optional[str] = None

    score: Optional[int] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    last_contacted: Optional[str] = None


class LeadResponse(BaseModel):
    id: Optional[int] = None

    name: str = ""
    email: EmailStr

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
    last_contacted: Optional[str] = None
    created_at: Optional[str] = None

    score_reasons: list[str] = Field(default_factory=list)