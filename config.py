from dotenv import load_dotenv
import os

load_dotenv()


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