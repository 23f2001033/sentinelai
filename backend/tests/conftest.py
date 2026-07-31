import os
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "sentinel_test.db"
_TMP_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"

# Tests must not depend on whichever provider key the developer happens to have
# exported, so blank them all out for the session.
for _key in (
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "TOGETHER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "LLM_API_KEY",
    "LLM_PROVIDER",
    "PLANNER_MODEL",
):
    os.environ[_key] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
