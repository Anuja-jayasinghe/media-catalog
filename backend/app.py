"""Vercel-compatible FastAPI entrypoint."""

from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")  # Existing local provider credentials.
load_dotenv(HERE / ".env")

from catalog.main import app  # noqa: E402
