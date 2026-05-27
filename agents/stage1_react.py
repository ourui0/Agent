"""
ReAct Agent — 阶段一核心范式，现已接入统一 common 层。
"""

import json, re, logging
from typing import Any, Dict, List

from common import BaseAgent, ToolRegistry, extract_json, trim_context
from common.llm_client import LLMClient

logger = logging.getLogger(__name__)

REACT_SYSTEM_PROMPT = """你是一个旅游助手 AI，使用 ReAct 范式。

## 可用工具
{tools}

## 格式
Thought: <推理>
Action: <工具名>
Action Input: <JSON>

信息足够时:
Final Answer: <答案>

## 规则
每次一个 Thought + 一个 Action，不要多余内容。"""


class ReActAgent(BaseAgent):
    def __init__(self, tool_registry: ToolRegistry, max_iterations: int = 10, name: str = "ReAct"):
        super().__init__(name=name, max_iterations=max_iterations)
        self.llm = LLMClient.get()
        self.tools = tool_registry

    def _run_impl(self, query: str) -> str:
        prompt = REACT_SYSTEM_PROMPT.format(tools=self.tools.list_tools())
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt + f"\n\n用户问题: {query}"}]
        context: List[str] = []

        for i in range(1, self.max_iterations + 1):
            logger.info(f"[ReAct] 第 {i}/{self.max_iterations} 轮")
            if context:
                messages[-1]["content"] = prompt + f"\n\n用户: {query}\n## 历史\n" + "\n".join(context[-6:])
            raw = self.llm.chat(trim_context(messages))

            thought = re.search(r"Thought:\s*(.+?)(?:\n|$)", raw)
            action = re.search(r"Action:\s*(\S+)", raw)
            final = re.search(r"Final Answer:\s*(.+?)$", raw, re.DOTALL)

            if final:
                logger.info(f"[ReAct] 得出答案 (第{i}轮)")
                return final.group(1).strip()

            if action:
                action_name = action.group(1)
                input_match = re.search(r"Action Input:\s*(\{.*?\})", raw, re.DOTALL)
                kwargs = json.loads(input_match.group(1)) if input_match else {}
                obs = self.tools.call(action_name, **kwargs)
                context.append(f"[轮{i}] {action_name}({kwargs}) → {obs}")
                logger.info(f"  Action: {action_name} → {obs[:60]}...")
                continue

            logger.warning(f"  无法解析: {raw[:80]}...")
            messages.append({"role": "user", "content": "请按格式: Thought: xxx\nAction: xxx\nAction Input: {...}"})

        return f"思考 {self.max_iterations} 轮未得出结果。"
