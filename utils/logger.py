import hashlib
import logging
from pathlib import Path

# How much free text is kept from unbounded visitor-written fields. Long
# enough to be recognisable in a log line, short enough to bound it.
_FREE_TEXT_LIMIT = 60

# Length of the lead reference. 12 hex characters is ample to correlate log
# lines for one lead without collisions at any volume this will ever see.
_REFERENCE_LENGTH = 12


def lead_reference(business_id, email) -> str:
    """
    A stable, non-reversible reference for a lead, safe to write to a log.

    Derived from business_id + email, so the same lead produces the same
    reference on every line and two businesses' leads never collide even with
    the same address (which the CRM allows -- see UNIQUE(business_id, email)).

    This is a correlation handle, not a secret. An attacker holding the log
    could confirm a *guessed* address by hashing it, since an email is
    low-entropy input. That is a much weaker capability than reading a list of
    addresses off disk, which is what this replaces, and it is why the full
    record lives in the CRM and the admin dashboard rather than here.
    """
    seed = f"{business_id or ''}|{(email or '').strip().lower()}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:_REFERENCE_LENGTH]


def _mask_email(email) -> str:
    """
    Keep the first character of the local part and the whole domain:
    nadia@ridgeline.com -> n***@ridgeline.com

    The domain is deliberately kept. It is the field's real debugging value --
    spotting a wave of signups from one company, or one throwaway domain --
    and it does not identify a person on its own.
    """
    text = (email or "").strip()

    if not text:
        return ""

    # rsplit: an address may legitimately contain more than one "@" in a
    # quoted local part, and the domain is always after the last one.
    local, separator, domain = text.rpartition("@")

    if not separator or not local or not domain:
        # Malformed enough that we cannot tell local from domain. Withhold all
        # of it rather than guess and leak the wrong half.
        return "***"

    return f"{local[0]}***@{domain}"


def _initials(name) -> str:
    """
    Nadia Okonkwo -> N.O.

    Enough for a human reading the log to recognise the lead they were just
    looking at, without writing the name down.
    """
    parts = [part for part in (name or "").split() if part]

    if not parts:
        return ""

    return "".join(f"{part[0].upper()}." for part in parts)


def _truncate(value) -> str:
    """
    Bound an unbounded visitor-written field.

    This is a length guard, not redaction: it does not make free text safe,
    it stops one pasted essay from dominating the log. Fields that are direct
    identifiers get masked instead.
    """
    text = "" if value is None else str(value).strip()

    if len(text) <= _FREE_TEXT_LIMIT:
        return text

    return f"{text[:_FREE_TEXT_LIMIT]}... (+{len(text) - _FREE_TEXT_LIMIT} chars)"


class Logger:
    """
    Centralized application logger.
    """

    def __init__(self):
        log_directory = Path("logs")
        log_directory.mkdir(exist_ok=True)

        self.logger = logging.getLogger("KaivixLogger")

        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)

            file_handler = logging.FileHandler(
                log_directory / "app.log",
                encoding="utf-8"
            )

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s"
            )

            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    # ---------- Generic ----------

    def info(self, message: str):
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    # ---------- Application ----------

    def log_startup(self):
        self.logger.info("Application started.")

    def log_shutdown(self, reason: str = "Application closed."):
        self.logger.info(reason)

    # ---------- Conversation ----------

    def log_user(self, message: str):
        self.logger.info(f"Visitor: {message}")

    def log_ai(self, message: str):
        self.logger.info(f"Alex: {message}")

    # ---------- Lead ----------

    def log_lead(self, lead: dict):
        """
        Record that a lead was captured, without writing customer PII to disk
        in the clear.

        This used to log name, email, business, budget, timeline and pain
        point verbatim. logs/app.log is a plaintext file that is not
        access-controlled, gets copied around with the repo directory, and is
        never rotated -- a poor place for a customer contact list.

        The line drawn here: **direct identifiers are masked, non-identifying
        qualification data is kept.**

        - name  -> initials
        - email -> first character plus domain
        - ref   -> a stable non-reversible handle (see lead_reference), so
                   several lines about one lead can still be tied together,
                   and so a log line can be matched to the full record
        - company, budget, timeline, pain_point -> kept, since none of them
          identify a person; the free-text ones are length-bounded

        The full record is in the CRM and the admin dashboard, which is where
        it should be looked up. Debuggability of the log is preserved: you can
        still see that a lead was captured, roughly who, from what
        organization, and with what qualification signal.
        """
        company = lead.get("company") or lead.get("business")

        self.logger.info(
            "Lead Captured | "
            f"ref={lead_reference(lead.get('business_id'), lead.get('email'))} | "
            f"Name={_initials(lead.get('name'))} | "
            f"Email={_mask_email(lead.get('email'))} | "
            f"Company={_truncate(company)} | "
            f"Budget={_truncate(lead.get('budget'))} | "
            f"Timeline={_truncate(lead.get('timeline'))} | "
            f"Pain Point={_truncate(lead.get('pain_point'))}"
        )

    # ---------- Exceptions ----------

    def log_error(self, error: Exception):
        self.logger.exception(str(error))