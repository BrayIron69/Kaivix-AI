from groq import Groq, GroqError

from config import Config
from utils.exceptions import LLMUnavailableError
from utils.logger import Logger


class LLM:
    """
    Unified LLM interface.

    This class has one responsibility:
    send a list of chat messages to the model and
    return the assistant's response.

    All prompt construction belongs in PromptBuilder.
    """

    def __init__(self):
        self.client = Groq(
            api_key=Config.GROQ_API_KEY
        )

    def generate(self, messages):
        """
        Send a standard OpenAI/Groq chat message list.

        Parameters
        ----------
        messages : list[dict]

        Example
        -------
        [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."}
        ]

        Raises
        ------
        LLMUnavailableError
            If the provider is unreachable or refuses the request --
            quota exhausted, rate limited, bad credentials, timeout, or a
            provider-side 5xx. GroqError is the single base class for all
            of those, so catching it covers RateLimitError,
            AuthenticationError, APIConnectionError, APITimeoutError and
            InternalServerError alike.

            Callers get a provider-agnostic exception so nothing above
            this module has to import a vendor SDK to handle an outage.
        """

        try:
            response = self.client.chat.completions.create(
                model=Config.MODEL,
                messages=messages,
                max_tokens=Config.MAX_TOKENS,
                temperature=Config.TEMPERATURE,
            )
        except GroqError as error:
            # Log the exception CLASS and HTTP status, never str(error).
            # Provider error text can echo request details, and an
            # AuthenticationError message may quote part of the API key.
            reason = type(error).__name__
            status_code = getattr(error, "status_code", None)

            Logger().error(
                "LLM provider unavailable | "
                f"provider=groq | reason={reason} | status={status_code}"
            )

            raise LLMUnavailableError(
                provider="groq",
                reason=reason,
                status_code=status_code,
            ) from error

        return response.choices[0].message.content.strip()