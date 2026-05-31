import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def force_mock_llm(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from common.llm_client import LLMClient

    LLMClient.reset_instance()
    yield
    LLMClient.reset_instance()


@pytest.fixture
def fixture_dir() -> Path:
    return PROJECT_ROOT / "tests" / "fixtures"


@pytest.fixture
def load_fixture(fixture_dir):
    def _load(name: str):
        with open(fixture_dir / name, "r", encoding="utf-8") as f:
            return json.load(f)

    return _load


@pytest.fixture
def registry():
    from common.tool_registry import ToolRegistry
    from common.tools.travel_tools import TOOL_FUNCTIONS

    r = ToolRegistry()
    for func, name, desc in TOOL_FUNCTIONS:
        r.register(func, name=name, description=desc)
    return r
