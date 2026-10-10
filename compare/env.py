"""Load .env from the project root, so nobody has to export variables by hand (bash, PowerShell or cmd)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> bool:
    try:
        from dotenv import load_dotenv
    except ImportError:          # optional: plain environment variables still work
        return False
    return load_dotenv(ROOT / ".env", override=False)
