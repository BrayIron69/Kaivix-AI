"""
Admin dashboard: a read-only view of the leads captured in crm/leads.db.

Deliberately minimal -- server-rendered HTML, no frontend framework, and
HTTP Basic Auth instead of sessions/cookies. This is mounted on the
backend's own domain (e.g. https://kaivix-ai.onrender.com/admin), not on
the public marketing site.

Credentials come from ADMIN_USERNAME / ADMIN_PASSWORD in the environment
(same os.getenv pattern as config.py). There is no default: if either is
unset the dashboard refuses every request rather than falling back to
something guessable.
"""

import html
import os
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from services.lead_service import LeadService


security = HTTPBasic()


def require_admin(
    credentials: HTTPBasicCredentials = Depends(security),
) -> str:
    """
    Verify HTTP Basic credentials against ADMIN_USERNAME / ADMIN_PASSWORD.

    Read at request time (not import time) so that rotating the values on
    the host takes effect on restart without a code change, and so tests
    can override them.
    """
    expected_username = os.getenv("ADMIN_USERNAME")
    expected_password = os.getenv("ADMIN_PASSWORD")

    # Unconfigured means closed, never open. No default credentials.
    if not expected_username or not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Admin dashboard is not configured: ADMIN_USERNAME and "
                "ADMIN_PASSWORD must both be set in the environment."
            ),
        )

    # compare_digest on both halves, and only then combine, so the check
    # doesn't leak which half was wrong via timing.
    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_password.encode("utf-8"),
    )

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)

lead_service = LeadService()


# --------------------------------------------------
# Presentation helpers
# --------------------------------------------------

# (lead field, column header, sorts numerically)
_LIST_COLUMNS = [
    ("name", "Name", False),
    ("email", "Email", False),
    ("company", "Company", False),
    ("budget", "Budget", False),
    ("timeline", "Timeline", False),
    ("score", "Score", True),
    ("priority", "Temperature", False),
    ("created_at", "Created", False),
]

_CREATED_AT_INDEX = len(_LIST_COLUMNS) - 1

# Every field the CRM captures, in reading order, for the detail view.
_DETAIL_FIELDS = [
    ("name", "Name"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("company", "Company"),
    ("business", "Business"),
    ("industry", "Industry"),
    ("budget", "Budget"),
    ("timeline", "Timeline"),
    ("pain_point", "Pain point"),
    ("decision_maker", "Decision maker"),
    ("score", "Lead score"),
    ("priority", "Temperature"),
    ("status", "Status"),
    ("notes", "Notes"),
    ("last_contacted", "Last contacted"),
    ("created_at", "Created at"),
    ("business_id", "Business ID"),
    ("id", "Record ID"),
]

_EMPTY = "—"  # em dash

_STYLES = """
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px 24px 64px;
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        Helvetica, Arial, sans-serif;
  background: #f5f6f8;
  color: #16191d;
}
.wrap { max-width: 1180px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
.sub { color: #6b7280; font-size: 13px; margin: 0 0 24px; }
.bar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
input[type=search] {
  flex: 1; max-width: 380px; padding: 9px 12px; font-size: 14px;
  border: 1px solid #d4d8de; border-radius: 8px; background: #fff;
}
input[type=search]:focus { outline: 2px solid #2563eb; outline-offset: -1px; }
#count { color: #6b7280; font-size: 13px; white-space: nowrap; }
.card {
  background: #fff; border: 1px solid #e3e6ea; border-radius: 10px;
  overflow: hidden;
}
table { width: 100%; border-collapse: collapse; }
th, td {
  text-align: left; padding: 11px 14px; font-size: 14px;
  border-bottom: 1px solid #eef0f3; white-space: nowrap;
}
th {
  background: #fafbfc; font-size: 12px; font-weight: 600; color: #4b5563;
  text-transform: uppercase; letter-spacing: 0.04em; cursor: pointer;
  user-select: none; position: sticky; top: 0;
}
th:hover { background: #f1f3f5; }
th::after { content: " \\2195"; opacity: 0.25; }
th[data-dir=asc]::after { content: " \\25B2"; opacity: 0.9; }
th[data-dir=desc]::after { content: " \\25BC"; opacity: 0.9; }
tbody tr:hover { background: #f8fafc; }
tbody tr:last-child td { border-bottom: none; }
a { color: #1d4ed8; text-decoration: none; }
a:hover { text-decoration: underline; }
.muted { color: #9ca3af; }
.pill {
  display: inline-block; padding: 2px 9px; border-radius: 999px;
  font-size: 12px; font-weight: 600;
}
.pill-hot { background: #fee2e2; color: #991b1b; }
.pill-warm { background: #ffedd5; color: #9a3412; }
.pill-cold { background: #e0edff; color: #1e40af; }
.pill-none { background: #f1f3f5; color: #4b5563; }
.empty { padding: 40px 16px; text-align: center; color: #6b7280; }
dl { margin: 0; }
.row {
  display: grid; grid-template-columns: 200px 1fr; gap: 16px;
  padding: 11px 18px; border-bottom: 1px solid #eef0f3;
}
.row:last-child { border-bottom: none; }
dt { color: #6b7280; font-size: 13px; }
dd { margin: 0; font-size: 14px; overflow-wrap: anywhere; }
.back { display: inline-block; margin-bottom: 18px; font-size: 14px; }
"""

_SCRIPT = """
(function () {
  var input = document.getElementById('search');
  var table = document.getElementById('leads');
  if (!input || !table) { return; }

  var tbody = table.querySelector('tbody');
  var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
  var headers = Array.prototype.slice.call(
    table.querySelectorAll('th[data-index]')
  );
  var count = document.getElementById('count');
  var noMatches = document.getElementById('no-matches');

  function applyFilter() {
    var query = input.value.trim().toLowerCase();
    var shown = 0;

    rows.forEach(function (row) {
      var haystack = row.getAttribute('data-search') || '';
      var match = query === '' || haystack.indexOf(query) !== -1;
      row.style.display = match ? '' : 'none';
      if (match) { shown += 1; }
    });

    count.textContent = shown + (shown === 1 ? ' lead' : ' leads');
    noMatches.style.display = shown === 0 ? '' : 'none';
  }

  // Server already returns newest first; mirror that as the initial state
  // so the first click on Created flips to oldest-first.
  var sortIndex = CREATED_INDEX;
  var sortAsc = false;

  function applySort(index, numeric) {
    sortAsc = index === sortIndex ? !sortAsc : true;
    sortIndex = index;

    rows.sort(function (a, b) {
      var left = a.children[index].getAttribute('data-value') || '';
      var right = b.children[index].getAttribute('data-value') || '';
      var result;

      if (numeric) {
        result = (parseFloat(left) || 0) - (parseFloat(right) || 0);
      } else {
        result = left.localeCompare(right);
      }

      return sortAsc ? result : -result;
    });

    rows.forEach(function (row) { tbody.appendChild(row); });

    headers.forEach(function (header) { header.removeAttribute('data-dir'); });
    headers[index].setAttribute('data-dir', sortAsc ? 'asc' : 'desc');
  }

  headers.forEach(function (header, index) {
    header.addEventListener('click', function () {
      applySort(index, header.getAttribute('data-numeric') === '1');
    });
  });

  input.addEventListener('input', applyFilter);
  applyFilter();
})();
"""


def _text(value) -> str:
    """Render a lead field as display text, blanks collapsed to an em dash."""
    if value is None:
        return ""

    return str(value).strip()


def _escape(value) -> str:
    return html.escape(_text(value))


def _display(value) -> str:
    text = _escape(value)

    if not text:
        return f'<span class="muted">{_EMPTY}</span>'

    return text


def _temperature_pill(priority) -> str:
    text = _text(priority)

    if not text:
        return f'<span class="muted">{_EMPTY}</span>'

    variant = text.lower()
    if variant not in ("hot", "warm", "cold"):
        variant = "none"

    return f'<span class="pill pill-{variant}">{html.escape(text)}</span>'


def _page(title: str, body: str, script: str = "") -> str:
    script_tag = f"<script>{script}</script>" if script else ""

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_STYLES}</style>\n"
        "</head>\n"
        "<body>\n"
        f'<div class="wrap">{body}</div>\n'
        f"{script_tag}\n"
        "</body>\n"
        "</html>"
    )


def _lead_to_dict(lead) -> dict:
    if hasattr(lead, "to_dict"):
        return lead.to_dict()

    if isinstance(lead, dict):
        return lead.copy()

    if hasattr(lead, "keys"):
        return {key: lead[key] for key in lead.keys()}

    raise TypeError("Unsupported lead type.")


def _render_row(lead: dict) -> str:
    detail_url = "/admin/leads/" + quote(_text(lead.get("email")), safe="")

    # Only the three fields the search box is documented to cover.
    haystack = " ".join(
        _text(lead.get(field)).lower()
        for field in ("name", "email", "company")
    )

    cells = []

    for field, _, _numeric in _LIST_COLUMNS:
        value = lead.get(field)
        sort_value = html.escape(_text(value))

        if field == "name":
            label = _escape(value) or "(no name)"
            content = f'<a href="{html.escape(detail_url)}">{label}</a>'
        elif field == "priority":
            content = _temperature_pill(value)
        elif field == "score":
            content = _escape(value) or "0"
        else:
            content = _display(value)

        cells.append(f'<td data-value="{sort_value}">{content}</td>')

    return (
        f'<tr data-search="{html.escape(haystack)}">'
        + "".join(cells)
        + "</tr>"
    )


# --------------------------------------------------
# Routes
# --------------------------------------------------


@router.get("", response_class=HTMLResponse)
def leads_dashboard():
    """List every captured lead, most recent first."""
    leads = [_lead_to_dict(lead) for lead in lead_service.get_all()]

    headers = "".join(
        f'<th data-index="{index}" data-numeric="{1 if numeric else 0}"'
        + (f' data-dir="desc"' if index == _CREATED_AT_INDEX else "")
        + f">{html.escape(label)}</th>"
        for index, (_field, label, numeric) in enumerate(_LIST_COLUMNS)
    )

    if leads:
        rows = "".join(_render_row(lead) for lead in leads)
        table = (
            '<div class="card">'
            '<table id="leads">'
            f"<thead><tr>{headers}</tr></thead>"
            f"<tbody>{rows}</tbody>"
            "</table>"
            '<div class="empty" id="no-matches" style="display:none">'
            "No leads match that search."
            "</div>"
            "</div>"
        )
    else:
        table = (
            '<div class="card"><div class="empty">'
            "No leads captured yet."
            "</div></div>"
        )

    lead_count = len(leads)
    body = (
        "<h1>Leads</h1>"
        '<p class="sub">Captured by the Kaivix Labs AI sales agent.</p>'
        '<div class="bar">'
        '<input type="search" id="search" '
        'placeholder="Search name, email, or company…" '
        'autocomplete="off">'
        f'<span id="count">{lead_count} '
        f'{"lead" if lead_count == 1 else "leads"}</span>'
        "</div>"
        f"{table}"
    )

    script = (
        _SCRIPT.replace("CREATED_INDEX", str(_CREATED_AT_INDEX))
        if leads
        else ""
    )

    return HTMLResponse(_page("Leads — Kaivix Admin", body, script))


@router.get("/leads/{email}", response_class=HTMLResponse)
def lead_detail(email: str):
    """Show every captured field for a single lead."""
    lead = lead_service.get_by_email(email)

    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found",
        )

    data = _lead_to_dict(lead)

    rows = "".join(
        f'<div class="row"><dt>{html.escape(label)}</dt>'
        + "<dd>"
        + (
            _temperature_pill(data.get(field))
            if field == "priority"
            else _display(data.get(field))
        )
        + "</dd></div>"
        for field, label in _DETAIL_FIELDS
    )

    heading = _escape(data.get("name")) or _escape(data.get("email"))

    body = (
        '<a class="back" href="/admin">&larr; All leads</a>'
        f"<h1>{heading}</h1>"
        f'<p class="sub">{_escape(data.get("email"))}</p>'
        f'<div class="card"><dl>{rows}</dl></div>'
    )

    return HTMLResponse(_page(f"{_text(data.get('email'))} — Kaivix Admin", body))
