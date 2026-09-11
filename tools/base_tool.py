from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """
    What every Tool returns. Never an exception.

    Mirrors the contract GoogleCalendarProvider.create_event and
    EmailProvider.send_email already use for real, external,
    side-effecting calls: callers need to distinguish "nothing to do"
    from "tried and it failed", and a raise partway through a
    conversation turn is not a distinction, it is a dropped turn.

    `success` is the ONLY thing PromptBuilder is allowed to treat as
    permission to have Bray confirm the action happened. That is the
    whole point of routing tools through a typed result instead of
    letting the model decide: a claim that an email was sent must be
    downstream of a real send returning True, never downstream of the
    conversation feeling like an email would be appropriate.
    """

    success: bool
    # Human-readable, already-safe-to-paraphrase description of what
    # actually happened, e.g. "Sent the overview to nadia@example.com".
    # PromptBuilder renders this; it never renders `error`.
    summary: str = ""
    # Structured payload for callers that need the specifics.
    data: dict = field(default_factory=dict)
    # Operator-facing only. Deliberately NOT shown to the visitor:
    # raw provider errors leak addresses, scopes and internals, and a
    # visitor can act on none of it.
    error: str = ""


class BaseTool:
    """
    A capability Bray can actually perform, as opposed to one the model
    can describe performing.

    Stable interface, deliberately small:
        name         -- stable identifier, matched against a business's
                        tools.yaml enabled_tools list
        description  -- one line, for operators reading a registry dump
        run(args, business_context) -> ToolResult

    INVOKED DETERMINISTICALLY, NEVER BY THE MODEL. PlanningEngine decides
    that a tool should run and records the request on the
    ConversationPlan; ConversationEngine performs the call one step
    later and attaches the ToolResult. This is the same split the
    calendar already uses (PlanningEngine sets strategy, then
    _maybe_attach_availability / _maybe_resolve_booking do the I/O),
    and it exists because PlanningEngine performs no I/O by design --
    see its docstring.

    There is no LLM function-calling path here and adding one would
    defeat the purpose: the model deciding when to send real email to a
    real prospect is precisely the failure mode Decision #030's
    unbacked-action gate was built after.

    `business_context` carries what a tool needs about who it is acting
    for (business_id, business name, booking link, the lead's details).
    Passed as a plain dict rather than the BusinessConfig object so a
    tool cannot reach into unrelated configuration, and so the contract
    stays stable if BusinessConfig's shape changes.
    """

    name: str = ""
    description: str = ""

    def run(self, args: dict, business_context: dict) -> ToolResult:
        raise NotImplementedError
