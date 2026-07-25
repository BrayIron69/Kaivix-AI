from dotenv import load_dotenv
import os

load_dotenv()


class Config:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    MODEL = os.getenv(
        "MODEL",
        "llama-3.3-70b-versatile"
    )

    MAX_TOKENS = int(
        os.getenv("MAX_TOKENS", 400)
    )

    TEMPERATURE = float(
        os.getenv("TEMPERATURE", 0.75)
    )