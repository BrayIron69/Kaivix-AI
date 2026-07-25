from groq import Groq

from config import Config


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
        """

        response = self.client.chat.completions.create(
            model=Config.MODEL,
            messages=messages,
            max_tokens=Config.MAX_TOKENS,
            temperature=Config.TEMPERATURE,
        )

        return response.choices[0].message.content.strip()