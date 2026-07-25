import logging
from pathlib import Path


class Logger:
    """
    Centralized application logger.
    """

    def __init__(self):
        log_directory = Path("logs")
        log_directory.mkdir(exist_ok=True)

        self.logger = logging.getLogger("KaivixLogger")

        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)

            file_handler = logging.FileHandler(
                log_directory / "app.log",
                encoding="utf-8"
            )

            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s"
            )

            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    # ---------- Generic ----------

    def info(self, message: str):
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    # ---------- Application ----------

    def log_startup(self):
        self.logger.info("Application started.")

    def log_shutdown(self, reason: str = "Application closed."):
        self.logger.info(reason)

    # ---------- Conversation ----------

    def log_user(self, message: str):
        self.logger.info(f"Visitor: {message}")

    def log_ai(self, message: str):
        self.logger.info(f"Alex: {message}")

    # ---------- Lead ----------

    def log_lead(self, lead: dict):
        self.logger.info(
            "Lead Captured | "
            f"Name={lead.get('name')} | "
            f"Email={lead.get('email')} | "
            f"Business={lead.get('business')} | "
            f"Budget={lead.get('budget')} | "
            f"Timeline={lead.get('timeline')} | "
            f"Pain Point={lead.get('pain_point')}"
        )

    # ---------- Exceptions ----------

    def log_error(self, error: Exception):
        self.logger.exception(str(error))