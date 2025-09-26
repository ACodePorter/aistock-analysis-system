from dotenv import load_dotenv

load_dotenv()

from .logging_config import configure_logging

configure_logging()

from .main import app

__all__ = ["app"]
