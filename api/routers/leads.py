from typing import List

from fastapi import APIRouter, HTTPException

from crm.lead import Lead
from schemas.lead import LeadCreate, LeadUpdate, LeadResponse
from services.lead_service import LeadService

router = APIRouter(
    prefix="/leads",
    tags=["Leads"],
)

lead_service = LeadService()

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


def _build_lead(payload: dict) -> Lead:
    company = _clean_text(payload.get("company") or payload.get("business"))

    return Lead(
        id=payload.get("id"),
        name=_clean_text(payload.get("name")),
        email=_clean_text(str(payload.get("email", ""))),
        company=company,
        business=company,
        phone=_clean_text(payload.get("phone")),
        industry=_clean_text(payload.get("industry")),
        budget=_clean_text(payload.get("budget")),
        timeline=_clean_text(payload.get("timeline")),
        pain_point=_clean_text(payload.get("pain_point")),
        decision_maker=_clean_text(payload.get("decision_maker")),
        score=int(payload.get("score") or 0),
        priority=_clean_text(payload.get("priority")) or "Cold",
        status=_clean_text(payload.get("status")) or "New",
        notes=_clean_text(payload.get("notes")),
        last_contacted=_clean_text(payload.get("last_contacted")) or None,
        created_at=payload.get("created_at"),
        score_reasons=list(payload.get("score_reasons") or []),
    )


def _serialize_lead(lead) -> dict:
    if hasattr(lead, "to_dict"):
        data = lead.to_dict()
    elif isinstance(lead, dict):
        data = lead.copy()
    else:
        raise TypeError("Unsupported lead type.")

    company = _clean_text(data.get("company") or data.get("business"))
    data["company"] = company
    data["business"] = company

    for field in [
        "name",
        "email",
        "phone",
        "industry",
        "budget",
        "timeline",
        "pain_point",
        "decision_maker",
        "priority",
        "status",
        "notes",
        "last_contacted",
        "created_at",
    ]:
        if field in data:
            data[field] = _clean_text(data.get(field))

    if data.get("score") in ("", None):
        data["score"] = 0
    else:
        try:
            data["score"] = int(data["score"])
        except (TypeError, ValueError):
            data["score"] = 0

    if data.get("score_reasons") is None:
        data["score_reasons"] = []

    return data


@router.get("", response_model=List[LeadResponse])
def get_all_leads():
    leads = lead_service.get_all()

    return [
        LeadResponse(**_serialize_lead(lead))
        for lead in leads
    ]


@router.get("/{email}", response_model=LeadResponse)
def get_lead(email: str):
    lead = lead_service.get_by_email(email)

    if lead is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found",
        )

    return LeadResponse(**_serialize_lead(lead))


@router.post("", response_model=LeadResponse, status_code=201)
def create_lead(lead_data: LeadCreate):
    payload = lead_data.model_dump()

    lead = _build_lead(payload)
    saved_lead = lead_service.save(lead)

    return LeadResponse(**_serialize_lead(saved_lead))


@router.put("/{email}", response_model=LeadResponse)
def update_lead(email: str, update: LeadUpdate):
    existing = lead_service.get_by_email(email)

    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="Lead not found",
        )

    current = _serialize_lead(existing)
    incoming = update.model_dump(exclude_none=True)

    current.update(incoming)
    current["email"] = email

    lead = _build_lead(current)
    saved_lead = lead_service.save(lead)

    return LeadResponse(**_serialize_lead(saved_lead))


@router.delete("/{email}")
def delete_lead(email: str):
    success = lead_service.delete(email)

    if not success:
        raise HTTPException(
            status_code=404,
            detail="Lead not found",
        )

    return {
        "message": "Lead deleted successfully."
    }