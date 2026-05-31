from common.llm_client import LLMClient
from common.tool_registry import ToolRegistry
from common.utils import extract_json, extract_tag, trim_context


def test_llm_client_mock_mode_without_api_key():
    client = LLMClient.get()
    assert client.mock_mode is True
    out = client.chat([{"role": "user", "content": "你好，推荐成都"}])
    assert isinstance(out, str)
    assert out


def test_llm_client_chat_json_parses_mock_stage2_prompt():
    client = LLMClient.get()
    data = client.chat_json([{"role": "user", "content": "从输入提取旅行参数：2人北京3天"}])
    assert data["city"] == "北京"
    assert data["days"] == 3
    assert data["people"] == 2


def test_tool_registry_register_call_unknown_and_bad_args():
    registry = ToolRegistry()

    def add(a: int, b: int) -> int:
        return a + b

    registry.register(add, description="加法")
    assert "add" in registry.tool_names
    assert registry.call("add", a=1, b=2) == "3"
    assert "未知工具" in registry.call("missing")
    assert "执行失败" in registry.call("add", a=1)
    assert "add" in registry.list_tools()


def test_extract_json_handles_plain_fenced_and_bad_json():
    assert extract_json('{"city": "成都"}') == {"city": "成都"}
    assert extract_json('```json\n{"city": "北京"}\n```') == {"city": "北京"}
    assert extract_json("not json") is None


def test_extract_tag_and_trim_context_preserve_system():
    assert extract_tag("<plan>hello</plan>", "plan") == "hello"
    messages = [{"role": "system", "content": "core"}]
    messages += [{"role": "user", "content": "x" * 1000} for _ in range(10)]
    trimmed = trim_context(messages, max_tokens_est=100, chars_per_token=1)
    assert trimmed[0]["role"] == "system"
    assert len(trimmed) < len(messages)
