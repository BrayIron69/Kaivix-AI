from typing import Optional

from tools.base_tool import BaseTool, ToolResult
from tools.email_tool import SendOverviewEmailTool
from utils.logger import Logger


class ToolRegistry:
    """
    Resolves a tool name to a real Tool, gated by the business's own
    tools.yaml enabled_tools list.

    The gate is the same one ConversationEngine._calendar_booking_enabled
    already applies to calendar booking, and it fails CLOSED for the same
    reason: a tool with a real, hard-to-undo side effect (mail leaving
    the system, an event landing on a real calendar) must be something a
    business switched on deliberately, not something it gets by upgrading.

    Deliberately NOT a plugin loader that imports arbitrary modules by
    name. docs/Architecture.md lists a Plugin System under planned
    additions; this is the narrow, real version of that -- a fixed map
    of tools this codebase actually ships, which cannot execute anything
    a visitor's message names.
    """

    def __init__(self, tools: Optional[dict] = None, logger: Optional[Logger] = None):
        self.logger = logger or Logger()
        if tools is None:
            email_tool = SendOverviewEmailTool(logger=self.logger)
            tools = {email_tool.name: email_tool}
        self._tools = tools

    def get(self, name: str, enabled_tools) -> Optional[BaseTool]:
        """
        The tool registered under `name`, or None when it doesn't exist
        or this business hasn't enabled it.
        """
        if not name or name not in self._tools:
            return None
        if name not in (enabled_tools or []):
            return None
        return self._tools[name]

    def run(self, name: str, args: dict, business_context: dict, enabled_tools) -> ToolResult:
        """
        Resolve and execute in one call. Never raises: a tool that
        throws would otherwise take down a conversation turn, and a
        dropped turn is a worse outcome than a declined action. Mirrors
        _sync_lead_to_crm's error-handling contract.
        """
        tool = self.get(name, enabled_tools)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Tool {name!r} is not available or not enabled for this business.",
            )

        try:
            return tool.run(args or {}, business_context or {})
        except Exception as error:
            self.logger.error(
                f"[ToolRegistry] Tool {name!r} raised, which it should never do: "
                f"{type(error).__name__}: {error}"
            )
            return ToolResult(success=False, error=f"{type(error).__name__}: {error}")
