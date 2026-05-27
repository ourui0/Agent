"""
Reflection Agent — 阶段一核心范式：生成 → 反思 → 修正。
"""

import json, re, logging
from typing import Any, Dict, List

from common import BaseAgent, ToolRegistry, extract_json, trim_context
from common.llm_client import LLMClient

logger = logging.getLogger(__name__)

GENERATOR_PROMPT = """你是旅游助手，生成旅行建议。

## 工具
{tools}

格式: Thought: ...\nAction: xxx\nAction Input: {{...}}
完成: Final Answer: ...

用户: {query}"""

REFLECTOR_PROMPT = """你是旅行规划审查员。检查以下建议。

## 检查清单
1. 路线: 顺序合理？是否绕路？
2. 预算: 是否在预算内？
3. 完整性: 遗漏天气/签证/交通？
4. 一致性: 自相矛盾？

## 输出 (JSON)
```json
{{
  "issues": ["问题"],
  "corrections": ["修正"],
  "verdict": "PASS" 或 "NEEDS_FIX",
  "final_answer": "修正后答案"
}}
```

审查对象:
{generation}"""


class ReflectionAgent(BaseAgent):
    def __init__(self, tool_registry: ToolRegistry, max_iterations: int = 2,
                 tool_max: int = 8, name: str = "Reflection"):
        super().__init__(name=name, max_iterations=max_iterations)
        self.llm = LLMClient.get()
        self.tools = tool_registry
        self.tool_max = tool_max

    def _run_impl(self, query: str) -> str:
        logger.info("[Reflection] 生成初稿...")
        generation = self._generate(query)

        for r in range(1, self.max_iterations + 1):
            logger.info(f"[Reflection] 第{r}轮反思...")
            review = self._reflect(query, generation)
            if review.get("verdict") == "PASS" or not review.get("issues"):
                logger.info("[Reflection] 通过!")
                return review.get("final_answer", generation)
            logger.info(f"  发现 {len(review.get('issues', []))} 个问题")
            generation = self._correct(query, generation, review)

        return generation

    def _generate(self, query: str) -> str:
        messages = [{"role": "user", "content": GENERATOR_PROMPT.format(
            tools=self.tools.list_tools(), query=query)}]
        for _ in range(self.tool_max):
            raw = self.llm.chat(trim_context(messages))
            fm = re.search(r"Final Answer:\s*(.+?)$", raw, re.DOTALL)
            if fm:
                return fm.group(1).strip()
            am = re.search(r"Action:\s*(\S+)", raw)
            im = re.search(r"Action Input:\s*(\{.*?\})", raw, re.DOTALL)
            if am:
                kwargs = json.loads(im.group(1)) if im else {}
                obs = self.tools.call(am.group(1), **kwargs)
                messages.append({"role": "user", "content": f"观察: {obs}"})
            else:
                messages.append({"role": "user", "content": "请继续。"})
        return "无法在限定步数内生成答案。"

    def _reflect(self, query: str, generation: str) -> Dict:
        raw = self.llm.chat([{"role": "user", "content": REFLECTOR_PROMPT.format(generation=generation)}])
        return extract_json(raw) or {"verdict": "PASS", "final_answer": generation}

    def _correct(self, query: str, generation: str, review: Dict) -> str:
        issues = "\n".join(f"- {i}" for i in review.get("issues", []))
        corrections = "\n".join(f"- {c}" for c in review.get("corrections", []))
        return self.llm.chat([{"role": "user", "content": f"原建议: {generation}\n问题:\n{issues}\n修改:\n{corrections}\n\n请给出修正后的完整建议。"}])
