import os

# Imported for its side effect: utils/env.py calls load_dotenv() at
# import time and is the single place that does so, so there is exactly
# one env bootstrap in the app rather than one per entry point. The
# values below are read at import time and need it to have already run.
import utils.env  # noqa: F401


class Config:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    MODEL = os.getenv(
        "MODEL",
        "openai/gpt-oss-120b"
    )

    MAX_TOKENS = int(
        os.getenv("MAX_TOKENS", 800)
    )

    TEMPERATURE = float(
        os.getenv("TEMPERATURE", 0.75)
    )