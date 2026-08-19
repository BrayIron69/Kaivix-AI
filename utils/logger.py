import hashlib
import logging
import os
import re
from pathlib import Path

# Imported for its side effect (load_dotenv at import time), so the
# KAIVIX_LOG_CONVERSATION_BODIES read below is correct on a freshly
# started server regardless of import order -- see utils/env.py.
import utils.env  # noqa: F401

# How much free text is kept from unbounded visitor-written fields. Long
# enough to be recognisable in a log line, short enough to bound it.
_FREE_TEXT_LIMIT = 60

# The same guard for text that is a whole turn or a generated narrative rather
# than one field. 60 characters is the right bound for a `pain_point`; applied
# to a paragraph it cuts mid-sentence and throws away the structured tail --
# including, in the case of the turn summary, the missing-field list that is
# the most useful thing in the line. Still bounded, just at paragraph scale.
_TURN_TEXT_LIMIT = 400

# Length of the lead reference. 12 hex characters is ample to correlate log
# lines for one lead without collisions at any volume this will ever see.
_REFERENCE_LENGTH = 12

# Finds an address embedded anywhere in a sentence, which is how emails
# actually reach the log -- not as a tidy `email` field but inside "my email
# is nadia@example.com" or a generated summary's "Known so far: email:n@e.com".
# Deliberately loose on the local part and anchored on a dotted domain: over-
# matching costs a masked false positive, under-matching writes an address to
# disk. Not an RFC 5322 validator and does not need to be.
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

# Opt-in for writing whole conversation turns to the log. See
# `conversation_bodies_enabled` for why they are off by default.
_CONVERSATION_BODY_ENV = "KAIVIX_LOG_CONVERSATION_BODIES"
_TRUTHY = {"1", "true", "yes", "on"}


def conversation_bodies_enabled() -> bool:
    """
    Whether whole conversation turns may be written to the log.

    Off unless `KAIVIX_LOG_CONVERSATION_BODIES` is set to a truthy value.

    A conversation turn is unbounded text a visitor typed, and routinely
    carries a name, an address and a phone number in one sentence. Unlike a
    lead's structured fields there is nothing to mask field-by-field: the
    identifiers are the content.

    Off by default is affordable because nothing depends on the log for the
    live case -- `app.py` already prints the whole exchange to the terminal
    for the human sitting in front of it. What the log adds is the *later*
    read, which is exactly when a plaintext transcript on disk is a liability
    rather than a convenience. Turning this on is a deliberate act for a
    debugging session, not the resting state.

    Read per call rather than cached at import so a test (or a developer
    mid-session) can flip it without rebuilding the Logger.
    """
    return os.getenv(_CONVERSATION_BODY_ENV, "").strip().lower() in _TRUTHY


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


def _truncate(value, limit: int = _FREE_TEXT_LIMIT) -> str:
    """
    Bound an unbounded visitor-written field.

    This is a length guard, not redaction: it does not make free text safe,
    it stops one pasted essay from dominating the log. Fields that are direct
    identifiers get masked instead.

    `limit` defaults to one field's worth; callers handling a whole turn or a
    generated paragraph pass `_TURN_TEXT_LIMIT` instead.
    """
    text = "" if value is None else str(value).strip()

    if len(text) <= limit:
        return text

    return f"{text[:limit]}... (+{len(text) - limit} chars)"


def redact_free_text(value, limit: int = _TURN_TEXT_LIMIT) -> str:
    """
    Make a line of free text loggable: mask any address inside it, then bound
    its length.

    `_mask_email` masks a field known to *be* an address. This handles the
    other case -- an address sitting inside a sentence -- by sweeping the text
    for anything that looks like one and masking each hit through that same
    function, so both paths produce `n***@example.com` and there is one
    definition of what a masked address looks like.

    Masking runs before truncation deliberately. Truncating first can cut an
    address in half and leave the local part -- the identifying half -- sitting
    in the log with the domain gone.

    This bounds and de-identifies; it does not sanitise. A name, a phone
    number, or an address written in words all survive it, which is why whole
    conversation turns are additionally withheld by default rather than merely
    swept (see `conversation_bodies_enabled`).
    """
    text = "" if value is None else str(value).strip()

    if not text:
        return ""

    swept = _EMAIL_PATTERN.sub(lambda hit: _mask_email(hit.group(0)), text)

    return _truncate(swept, limit)


def describe_body(value) -> str:
    """
    What stands in for a conversation turn in the log.

    Withheld by default, and the placeholder still reports the length so the
    log remains useful for the questions it can honestly answer -- did a turn
    happen, was it empty, was it enormous -- without carrying its content.

    When bodies are switched on the text is still swept and bounded. The gate
    and the sweep are not alternatives: the gate is the default posture, the
    sweep is the floor that applies whatever the gate is set to.
    """
    text = "" if value is None else str(value).strip()

    if not text:
        return "<empty>"

    if not conversation_bodies_enabled():
        return f"<{len(text)} chars withheld; set {_CONVERSATION_BODY_ENV}=1 to log bodies>"

    return redact_free_text(text)


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
        """
        Record that the visitor said something, without writing what they said
        to disk by default.

        This used to log the turn verbatim. A visitor message is the densest
        PII in the system -- one line of the existing log carries a name, an
        address, a phone number and a budget, because that is simply how people
        answer "what should I call you and where can I reach you?".

        Same rule as `log_lead`: direct identifiers do not go to disk. The
        difference is that a lead is a set of named fields that can be masked
        one by one, and a turn is undifferentiated prose where the identifiers
        *are* the content -- so the body is withheld rather than masked, and
        masking applies on top when it is switched back on.
        """
        self.logger.info(f"Visitor: {describe_body(message)}")

    def log_ai(self, message: str):
        """
        Record that the assistant replied. Gated the same way as `log_user`.

        The assistant's own text is not visitor-written, but it quotes back
        what it was told ("Thanks Nadia, I'll send that to nadia@..."), so it
        leaks the same identifiers one turn later.
        """
        self.logger.info(f"Alex: {describe_body(message)}")

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