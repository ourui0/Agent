"""
统一 LLM 客户端 — 全阶段共用。
- 默认 DeepSeek API (阶段二引入)
- Mock 模式降级 (阶段一引入，无 Key 也能演示)
- 单例 + reset_mock + chat/chat_json
"""

import os
import re
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
    logger.warning("openai 未安装，启用 Mock 模式")

# ─── 默认配置 ───
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class LLMClient:
    """统一 LLM 客户端，单例模式。"""

    _instance: Optional["LLMClient"] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.3,
    ):
        self.model = model
        self.temperature = temperature
        self.mock_mode = not _OPENAI_AVAILABLE

        api_key = (
            api_key
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY", "")
        )

        if not self.mock_mode and api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = None
            self.mock_mode = True

        self._mock_turn = 0

    @classmethod
    def get(cls, **kwargs) -> "LLMClient":
        """获取/创建单例。"""
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """重置单例（用于切换模式）。"""
        cls._instance = None

    def reset_mock(self):
        """重置 Mock 轮次计数器（每次新 Agent 运行前调用）。"""
        self._mock_turn = 0

    # ── 公共接口 ──

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
    ) -> str:
        if self.mock_mode or self.client is None:
            return self._mock_reply(messages)
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or self.temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        raw = self.chat(messages, temperature)
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            logger.warning(f"JSON 解析失败: {raw[:200]}")
            return {"raw": raw, "error": "json_parse_failed"}

    # ── Mock 回复 ──

    def _mock_reply(self, messages: List[Dict[str, str]]) -> str:
        """智能 Mock：根据消息内容模拟多轮回复。"""
        full_ctx = " ".join(m.get("content", "") for m in messages)
        last = messages[-1]["content"] if messages else ""
        self._mock_turn += 1

        # ── 阶段二 LangGraph 节点 (优先匹配) ──
        if "从输入提取" in full_ctx or "提取旅行参数" in full_ctx:
            return json.dumps({"city": "北京", "budget": 3000, "days": 3, "people": 2}, ensure_ascii=False)
        if "土著导游" in full_ctx:
            return json.dumps({
                "itinerary": [
                    {"day": 1, "attractions": ["故宫", "天坛"], "notes": "提前预约"},
                    {"day": 2, "attractions": ["颐和园", "798艺术区"], "notes": "地铁出行"},
                    {"day": 3, "attractions": ["长城"], "notes": "早出发"},
                ],
                "tips": "北京地铁方便，注意防晒"
            }, ensure_ascii=False)
        if "酒店专家" in full_ctx:
            budget = 3000.0
            for m in messages:
                if "预算" in m.get("content", "") and "¥" in m.get("content", ""):
                    import re
                    nums = re.findall(r"¥(\d+)", m.get("content", ""))
                    if nums: budget = float(nums[-1])
            per_night = max(budget * 0.4 / 2 / 3, 60)
            candidates = [h for h in [
                {"name": "青年旅舍", "price": 60, "rating": 3.5, "location": "市中心"},
                {"name": "如家快捷", "price": 180, "rating": 3.8, "location": "交通枢纽"},
                {"name": "精品民宿", "price": 280, "rating": 4.5, "location": "景区附近"},
            ] if h["price"] <= per_night] or [{"name": "青年旅舍", "price": 60, "rating": 3.5, "location": "市中心"}]
            return json.dumps({"hotels": [{"name": candidates[0]["name"], "price_per_night": candidates[0]["price"],
                "rating": candidates[0]["rating"], "location": candidates[0]["location"], "reason": "Mock推荐"}],
                "choice_reason": "预算适配"}, ensure_ascii=False)
        if "财务精算" in full_ctx:
            return json.dumps({"ticket_cost": 200, "hotel_cost": 560, "meal_cost": 600, "transport_cost": 150,
                "total_cost": 1510, "budget_status": "within_budget", "per_person": 755, "analysis": "预算充足"}, ensure_ascii=False)

        # ── 阶段一 ReAct ──
        is_react_prompt = "可用工具" in full_ctx and "Thought:" in full_ctx and "Action:" in full_ctx
        if is_react_prompt and self._mock_turn == 1:
            return (
                "Thought: 先查天气。\n"
                "Action: get_weather\n"
                'Action Input: {"city": "三亚", "date": "2026-06-01"}'
            )
        if is_react_prompt and self._mock_turn == 2:
            return (
                "Thought: 再查景点。\n"
                "Action: search_attractions\n"
                'Action Input: {"city": "三亚", "top_k": 3}'
            )
        if is_react_prompt and self._mock_turn == 3:
            return (
                "Thought: 最后查酒店。\n"
                "Action: search_hotels\n"
                'Action Input: {"city": "三亚", "budget_per_night": 500}'
            )
        if is_react_prompt and self._mock_turn >= 4 and "请严格按照格式" not in last:
            return (
                "Thought: 信息足够。\n"
                "Final Answer: 三亚晴32°C，推荐亚龙湾、天涯海角，精品民宿¥280/晚。祝旅途愉快！🌴"
            )

        # ── 阶段一 P&S ──
        if "旅游规划专家" in full_ctx and self._mock_turn == 1:
            return json.dumps({
                "plan": [
                    {"step": 1, "action": "get_weather", "args": {"city": "三亚", "date": "2026-06-01"}, "reason": "查天气"},
                    {"step": 2, "action": "search_attractions", "args": {"city": "三亚", "top_k": 3}, "reason": "找景点"},
                    {"step": 3, "action": "search_hotels", "args": {"city": "三亚", "budget_per_night": 500}, "reason": "选住宿"},
                ],
                "final_synthesis": "天气{{step1}}，景点{{step2}}，住宿{{step3}}。祝旅途愉快！"
            }, ensure_ascii=False)
        if "综合以上信息" in last or "生成最终答案" in last:
            return "三亚3日游：D1亚龙湾+天涯海角，D2南山寺+蜈支洲岛，D3自由活动。总预算约¥2000/人。"

        # ── 阶段一 Reflection ──
        if "旅行规划审查员" in full_ctx:
            return json.dumps({
                "issues": ["行程过紧", "预算未含餐饮"],
                "corrections": ["拆分D1行程", "增加餐饮提醒"],
                "verdict": "NEEDS_FIX", "final_answer": ""
            }, ensure_ascii=False)
        if "修改意见" in last or "修改后的" in last or "修改:" in last:
            return "修正后行程已优化，D1上午亚龙湾下午天涯海角，D2南山寺+蜈支洲岛，D3自由活动。餐饮¥150/天。"
        if "请严格按照格式" in last:
            self._mock_turn = 1
            return "Thought: 查天气。\nAction: get_weather\nAction Input: {\"city\": \"三亚\"}"

        return f"好的，关于「{last[:30]}」的建议是：提前预订，错峰出行。"
