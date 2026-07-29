"""
Provider-agnostic application exceptions.

These exist so callers can handle a failure without importing a specific
vendor's SDK. Nothing above utils/llm.py should ever need to know that the
current LLM happens to be Groq.
"""


class LLMUnavailableError(Exception):
    """
    Raised when the configured LLM provider cannot serve a request.

    Covers every reason the provider might be unreachable or refuse to
    answer -- quota exhausted, rate limited, bad credentials, network
    failure, timeout, provider-side 5xx.

    Deliberately NOT raised for a successful call that returned an
    unexpected payload: that is a bug, not an outage, and should surface
    as a real error rather than a soft fallback.

    Attributes
    ----------
    provider : str
        Which provider failed ("groq"), for logging.
    reason : str
        The provider's exception class name (e.g. "RateLimitError").
        Deliberately the class name and not the message text -- provider
        error messages can echo request details, and this value gets
        written to logs.
    status_code : int | None
        The provider's HTTP status if it had one (429, 401, 500...).
    """

    def __init__(
        self,
        provider: str,
        reason: str,
        status_code: int | None = None,
    ):
        self.provider = provider
        self.reason = reason
        self.status_code = status_code

        detail = f"{provider} unavailable ({reason}"
        if status_code is not None:
            detail += f", status={status_code}"
        detail += ")"

        super().__init__(detail)
