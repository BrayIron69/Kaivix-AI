import os
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from tools.base_tool import BaseTool, ToolResult
from utils.logger import Logger

# Deliberately small. This exists so Bray doesn't say "I can't search the
# web" to something trivial mid-conversation, NOT so it can research on a
# prospect's behalf. An open-ended browsing agent in a sales conversation
# is a different product with a different risk profile, and this is not
# a step toward one.
_MAX_RESULT_CHARS = 400
_REQUEST_TIMEOUT_SECONDS = 8

# Answered locally, with no network call and no API key, because they
# need none: the answer is the clock. This is most of the real value
# here -- "what's today's date" was the example in the report, and a
# search API would be a slow, billable, failure-prone way to read a
# clock the process already has.
_DATE_QUESTION_PATTERN = re.compile(
    r"\b(?:what(?:'s| is)\s+(?:the\s+)?(?:today'?s?\s+)?date"
    r"|what\s+day\s+is\s+(?:it|today)"
    r"|what(?:'s| is)\s+today"
    r"|what\s+(?:is\s+)?the\s+time"
    r"|what\s+time\s+is\s+it"
    r"|what\s+year\s+is\s+it"
    r"|what\s+month\s+is\s+it)\b",
    re.IGNORECASE,
)

_TIME_QUESTION_PATTERN = re.compile(
    r"\b(?:what(?:'s| is)\s+the\s+time|what\s+time\s+is\s+it)\b", re.IGNORECASE
)


class FactualLookupTool(BaseTool):
    """
    Answers a simple factual question asked mid-conversation.

    Two tiers, in order:

      1. Date and time, answered from the business's own configured
         timezone with no network call at all. No API key, nothing to
         configure, nothing to fail.

      2. Anything else, via a web search API, and ONLY when one is
         configured (WEB_SEARCH_API_KEY). Without it this tier reports
         failure, which means Bray says nothing rather than guessing --
         the same stance as every other capability here.

    Scope is narrow by construction, not by instruction: there is no
    page fetching, no link following, no multi-step research, and the
    result is truncated. A sales agent that can read a clock and check a
    simple fact is the goal; a browsing agent is not.
    """

    name = "factual_lookup"
    description = "Answer a simple factual question (date, time, or a basic fact check)."

    def __init__(self, logger: Optional[Logger] = None):
        self.logger = logger or Logger()

    @staticmethod
    def is_simple_date_question(question: str) -> bool:
        """Whether this can be answered from the clock alone."""
        return bool(_DATE_QUESTION_PATTERN.search(question or ""))

    def run(self, args: dict, business_context: dict) -> ToolResult:
        question = (args.get("question") or "").strip()
        if not question:
            return ToolResult(success=False, error="No question supplied.")

        if self.is_simple_date_question(question):
            return self._answer_from_the_clock(question, business_context)

        return self._answer_from_web_search(question)

    def _answer_from_the_clock(self, question: str, business_context: dict) -> ToolResult:
        timezone_name = business_context.get("timezone") or "UTC"
        try:
            now = datetime.now(ZoneInfo(timezone_name))
        except Exception:
            # An unknown timezone is a config error, not a reason to
            # refuse to say what day it is.
            self.logger.warning(
                f"[FactualLookupTool] Unknown timezone {timezone_name!r}, using UTC."
            )
            now = datetime.now(ZoneInfo("UTC"))

        # Built without strftime's %-I / %-d, which are not portable to
        # Windows (where this is developed) and raise there.
        date_part = f"{now.strftime('%A, %B')} {now.day}, {now.year}"

        if _TIME_QUESTION_PATTERN.search(question):
            clock = f"{now.strftime('%I').lstrip('0')}:{now.strftime('%M %p')}"
            answer = f"{clock} on {date_part}"
        else:
            answer = date_part

        return ToolResult(
            success=True,
            summary=answer,
            data={"answer": answer, "timezone": timezone_name},
        )

    def _answer_from_web_search(self, question: str) -> ToolResult:
        api_key = os.getenv("WEB_SEARCH_API_KEY")
        if not api_key:
            return ToolResult(
                success=False,
                error=(
                    "WEB_SEARCH_API_KEY is not set, so nothing beyond date and "
                    "time can be looked up."
                ),
            )

        try:
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                params={"q": question, "count": 1},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            results = (response.json().get("web") or {}).get("results") or []
        except Exception as error:
            self.logger.error(
                f"[FactualLookupTool] Search failed: {type(error).__name__}: {error}"
            )
            return ToolResult(success=False, error=f"{type(error).__name__}: {error}")

        if not results:
            return ToolResult(success=False, error="No results.")

        top = results[0]
        snippet = (top.get("description") or "").strip()
        if not snippet:
            return ToolResult(success=False, error="Top result carried no description.")

        return ToolResult(
            success=True,
            summary=snippet[:_MAX_RESULT_CHARS],
            data={"source": top.get("url") or ""},
        )
