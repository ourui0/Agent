"""
阶段三：基于自研框架的旅游规划 Agent。
使用 @tool / BaseAgent / EventBus / Middleware / Orchestrator，
替代 LangGraph 完成同等的编排能力。
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Tuple

from .stage3_framework import (
    tool, BaseAgent, EventBus, Orchestrator,
    MiddlewarePipeline, TokenCounterMiddleware, FunctionalAgent,
)
from common.tools import (
    WEATHER_DB, ATTRACTIONS_DB, HOTELS_DB,
    ATTRACTION_COST, DEFAULT_ATTRACTION_COST,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# @tool 装饰的工具函数 (替代阶段二的 ToolRegistry)
# ═══════════════════════════════════════════════════════════════

@tool(description="查询指定城市的天气")
def get_weather(city: str) -> str:
    """查询城市天气。
    city: 城市名称 (中文)"""
    import random
    if city not in WEATHER_DB:
        return f"暂无{city}天气数据"
    wtype, temp = random.choice(list(WEATHER_DB[city].items()))
    return f"{city}: {wtype} {temp}°C"


@tool(description="搜索城市热门景点")
def search_attractions(city: str, top_k: int = 3) -> str:
    """搜索景点。
    city: 城市名称
    top_k: 返回数量"""
    spots = ATTRACTIONS_DB.get(city, ["热门景点"])[:top_k]
    return f"{city}景点: " + "、".join(spots)


@tool(description="按预算搜索酒店")
def search_hotels(city: str, budget_per_night: float = 500) -> str:
    """搜索酒店。
    city: 城市名称
    budget_per_night: 每晚预算上限"""
    candidates = [h for h in HOTELS_DB if h["price"] <= budget_per_night]
    if not candidates:
        return f"{city}无{budget_per_night}元以下酒店"
    best = max(candidates, key=lambda h: h["rating"])
    return f"{best['name']} ¥{best['price']}/晚 {best['rating']}分"


# ═══════════════════════════════════════════════════════════════
# 四个 BaseAgent 节点 (替代阶段二的 LangGraph 节点)
# ═══════════════════════════════════════════════════════════════

parse_agent = BaseAgent(
    name="输入解析器",
    system_prompt="""从用户输入提取旅行参数，返回 JSON。
格式: {"city":"城市","budget":数字,"days":数字,"people":数字}
默认: city=北京 budget=3000 days=3 people=1。只返回 JSON。""",
    tools=[],
)

guide_agent = BaseAgent(
    name="本地土著向导",
    system_prompt="""你是当地向导。根据 state 中的 city 和 days 规划行程。

每个景点的门票参考:
- 故宫¥60, 长城¥40, 颐和园¥30, 天坛¥34, 大熊猫基地¥55, 迪士尼¥399, 南山寺¥129
- 其他景点默认¥50

返回 JSON:
{"itinerary": [{"day":1,"attractions":["景点A","景点B"],"notes":"提示"}], "tips":"建议"}

规则: 每天2-3个景点，注意位置邻近。只返回 JSON。""",
    tools=[search_attractions],
)

hotel_agent = BaseAgent(
    name="酒店专家",
    system_prompt="""你是酒店预订专家。根据 state 中的 budget/days/people 推荐酒店。

人均每晚预算 = budget / people / days * 0.4

调用 search_hotels 查询酒店，然后返回 JSON:
{"hotels": [{"name":"","price_per_night":0,"rating":0,"location":"","reason":""}], "choice_reason":""}

如果 state 中有 _backtrack_count > 0，说明上次超支了，请选择更便宜的酒店。
只返回 JSON。""",
    tools=[search_hotels, get_weather],
)

finance_agent = BaseAgent(
    name="财务精算师",
    system_prompt="""你是财务精算师。根据 state 核价。

费用标准:
- 酒店: 从 hotels 中取 price_per_night * (days-1) 晚
- 餐饮: ¥200/人/天
- 交通: ¥50/人/天
- 门票: 参考行程中标注的价格

返回 JSON:
{"total_cost":总费用,"budget_status":"within_budget"|"over_budget","per_person":人均,"analysis":"分析"}

只返回 JSON。""",
    tools=[],
)


# ═══════════════════════════════════════════════════════════════
# 条件路由函数 (替代阶段二的 route_after_finance)
# ═══════════════════════════════════════════════════════════════

def route_after_finance(state: dict) -> Tuple[Optional[str], bool]:
    """
    财务节点后的条件路由。
    返回 (目标节点名, 是否为回溯)
    """
    status = state.get("budget_status", "within_budget")
    if status == "over_budget":
        logger.warning(f"⚠️ 超支! 回退到 hotel")
        return "hotel", True   # 回溯到酒店节点
    return None, False         # 默认前进


# ═══════════════════════════════════════════════════════════════
# Orchestrator 构建 + EventBus 监听器
# ═══════════════════════════════════════════════════════════════

async def log_listener(event_type: str, data: dict):
    """EventBus 监听器：打印节点执行日志。"""
    node = data.get("node", "?")
    update = data.get("update", {})
    # 跳过工具调用产生的内部字段
    visible = {k: v for k, v in update.items()
               if not k.startswith("_") and k not in ("response",)}
    if visible:
        logger.info(f"  📤 [{node}] {json.dumps(visible, ensure_ascii=False)[:120]}")


async def sse_listener_factory(queue: asyncio.Queue):
    """SSE 监听器工厂：将事件放入 asyncio.Queue 供 FastAPI 消费。"""
    async def listener(event_type: str, data: dict):
        await queue.put({"event": event_type, "data": data})
    return listener


def build_orchestrator() -> Orchestrator:
    """构建旅游规划编排器。"""

    bus = EventBus()
    bus.subscribe("node:complete", log_listener)

    pipeline = MiddlewarePipeline(
        [TokenCounterMiddleware()],
        final_handler=None,  # 各节点自行处理
    )

    # 注意：pipeline 需要 final_handler，这里我们用节点自己的 __call__
    # 在实际运行时会传入 agent 作为 final_handler
    # 简化：直接传 agent 实例

    orch = Orchestrator(bus=bus, max_backtracks=3)

    orch.add_node("parse", parse_agent)
    orch.add_node("guide", guide_agent,
                  MiddlewarePipeline([TokenCounterMiddleware()], guide_agent))
    orch.add_node("hotel", hotel_agent,
                  MiddlewarePipeline([TokenCounterMiddleware()], hotel_agent))
    orch.add_node("finance", finance_agent,
                  MiddlewarePipeline([TokenCounterMiddleware()], finance_agent))

    orch.set_route("finance", route_after_finance)
    return orch


async def run_travel_plan(query: str, max_backtracks: int = 3) -> dict:
    """运行一次旅行规划。"""

    orch = Orchestrator(bus=EventBus(), max_backtracks=max_backtracks)

    # 监听日志
    orch.bus.subscribe("node:complete", log_listener)
    orch.bus.subscribe("orchestrator:backtrack",
                       lambda t, d: logger.warning(f"↩ 回溯: {d.get('from')} → {d.get('to')} ({d.get('count')}/{d.get('max')})"))

    orch.add_node("parse", parse_agent)
    orch.add_node("guide", guide_agent)
    orch.add_node("hotel", hotel_agent)
    orch.add_node("finance", finance_agent)
    orch.set_route("finance", route_after_finance)

    logger.info(f"🚀 自研框架启动: {query}")
    state = await orch.run({"user_query": query})
    return state
