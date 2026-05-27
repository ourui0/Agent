"""
Plan-and-Solve Agent — 阶段一核心范式。
"""

import json, logging
from typing import Any, Dict, List

from common import BaseAgent, ToolRegistry, extract_json
from common.llm_client import LLMClient

logger = logging.getLogger(__name__)

PLANNER_PROMPT = """你是旅游规划专家。根据需求制定执行计划。

## 可用工具
{tools}

## 输出 (JSON)
```json
{{
  "plan": [
    {{"step": 1, "action": "工具名", "args": {{}}, "reason": "原因"}}
  ],
  "final_synthesis": "模板，用 {{results}} 占位"
}}
```

## 规则
每步对应一个可用工具，计划 5-8 步。"""


class PlanAndSolveAgent(BaseAgent):
    def __init__(self, tool_registry: ToolRegistry, max_iterations: int = 10, name: str = "PlanSolve"):
        super().__init__(name=name, max_iterations=max_iterations)
        self.llm = LLMClient.get()
        self.tools = tool_registry

    def _run_impl(self, query: str) -> str:
        logger.info("[P&S] 规划...")
        plan = self._generate_plan(query)
        if not plan:
            return "规划失败。"

        logger.info(f"[P&S] 执行 {len(plan)} 步...")
        results = self._execute_plan(plan)
        logger.info("[P&S] 综合...")
        return self._synthesize(query, plan, results)

    def _generate_plan(self, query: str) -> List[Dict]:
        raw = self.llm.chat([
            {"role": "user", "content": PLANNER_PROMPT.format(tools=self.tools.list_tools()) + f"\n\n{query}"},
        ])
        data = extract_json(raw) or {}
        return [s for s in data.get("plan", []) if s.get("action") in self.tools.tool_names]

    def _execute_plan(self, plan: List[Dict]) -> Dict[int, str]:
        results = {}
        for item in plan:
            step = item.get("step", len(results) + 1)
            obs = self.tools.call(item.get("action", ""), **item.get("args", {}))
            results[step] = obs
            logger.info(f"  步骤{step}: {obs[:60]}...")
        return results

    def _synthesize(self, query: str, plan: List[Dict], results: Dict[int, str]) -> str:
        results_text = "\n".join(f"步骤{k}: {v}" for k, v in sorted(results.items()))
        return self.llm.chat([
            {"role": "user", "content": f"用户: {query}\n计划:\n{json.dumps(plan, ensure_ascii=False)}\n结果:\n{results_text}\n\n请综合回答。"},
        ])
