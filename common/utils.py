import json
import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出中提取 JSON 块 (兼容 ```json 围栏或无围栏)。"""
    # 尝试 ```json ... ``` 格式
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试纯 JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    return None


def extract_tag(text: str, tag: str) -> Optional[str]:
    """提取 <tag>...</tag> 或 [tag]...[/tag] 包裹的内容。"""
    patterns = [
        rf"<{tag}>\s*(.*?)\s*</{tag}>",
        rf"\[{tag}\]\s*(.*?)\s*\[/{tag}\]",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def trim_context(messages: list, max_tokens_est: int = 4000,
                 chars_per_token: int = 4) -> list:
    """裁剪对话历史，防止超出上下文窗口。保留 system + 最近消息。"""
    if not messages:
        return messages
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    est_tokens = total_chars / chars_per_token
    if est_tokens <= max_tokens_est:
        return messages
    # 保留 system 消息 + 最后 N 条
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]
    while other_msgs:
        trimmed = system_msgs + other_msgs
        total = sum(len(str(m.get("content", ""))) for m in trimmed)
        if total / chars_per_token <= max_tokens_est:
            return trimmed
        other_msgs.pop(0)
    return system_msgs + other_msgs[-2:]


def safe_json_dumps(obj: Any, indent: int = 2) -> str:
    """安全的 JSON 序列化，处理不可序列化对象。"""
    return json.dumps(obj, ensure_ascii=False, indent=indent, default=str)
