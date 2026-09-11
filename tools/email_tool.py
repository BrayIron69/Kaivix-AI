from typing import Optional

from scheduling.email_provider import EmailProvider
from tools.base_tool import BaseTool, ToolResult
from utils.logger import Logger, lead_reference


class SendOverviewEmailTool(BaseTool):
    """
    Sends the visitor a real follow-up email with what Kaivix does and
    the booking link.

    Wraps scheduling/email_provider.py rather than reimplementing Gmail
    access: that class already owns OAuth, refresh and the never-raise
    send contract, and owns it for BOTH this tool and the existing
    "email me a summary" path. One definition of how mail leaves this
    system, not two.

    Refuses rather than improvises when anything required is missing --
    no recipient, provider not connected. A tool that "sort of" ran and
    reported success is worse than one that declines, because the whole
    reason results flow back through ToolResult is so Bray's claim that
    an email was sent is downstream of an email actually being sent.
    """

    name = "send_overview_email"
    description = "Email the visitor a short overview plus the booking link."

    def __init__(
        self,
        email_provider: Optional[EmailProvider] = None,
        logger: Optional[Logger] = None,
    ):
        self.email_provider = email_provider or EmailProvider()
        self.logger = logger or Logger()

    def run(self, args: dict, business_context: dict) -> ToolResult:
        business_id = business_context.get("business_id") or ""
        recipient = (business_context.get("lead_email") or "").strip()
        business_name = business_context.get("business_name") or "us"
        booking_link = business_context.get("booking_link") or ""
        lead_name = (business_context.get("lead_name") or "").strip()

        if not recipient:
            return ToolResult(
                success=False,
                error="No recipient address on file for this conversation.",
            )

        if not self.email_provider.is_connected(business_id):
            return ToolResult(
                success=False,
                error=f"EmailProvider is not connected for business_id={business_id!r}.",
            )

        greeting = f"Hi {lead_name}," if lead_name else "Hi,"
        body = (
            f"{greeting}\n\n"
            f"Thanks for the conversation just now. Here's a short recap of "
            f"what {business_name} does:\n\n"
            f"We build AI employees that handle customer support, lead "
            f"qualification, scheduling and follow-up around the clock, "
            f"without salaries, sick days or turnover.\n\n"
        )
        if booking_link:
            body += f"When you're ready, you can grab a time here:\n{booking_link}\n\n"
        body += f"Speak soon,\n{business_name}\n"

        result = self.email_provider.send_email(
            business_id,
            to=recipient,
            subject=f"Following up from {business_name}",
            body_text=body,
        )

        if result.get("success"):
            return ToolResult(
                success=True,
                summary=f"Sent the overview email to {recipient}.",
                data={"recipient": recipient},
            )

        # Logged with the same masked reference Logger.log_lead uses --
        # a failed send is an operator problem, and the visitor's raw
        # address does not belong in the log to report it.
        self.logger.error(
            f"[SendOverviewEmailTool] Send failed "
            f"(business_id={business_id!r}, "
            f"ref={lead_reference(business_id, recipient)}): {result.get('error')}"
        )
        return ToolResult(success=False, error=str(result.get("error") or "Send failed."))
