"""
阶段三：基于自研框架的旅游规划 Agent。

使用 @tool / BaseAgent / EventBus / Middleware / Orchestrator，
替代 LangGraph 完成同等的编排能力。

阶段五增强: 接入高德真实 API — 路线规划 + 美食推荐 + 实时天气。
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
# 基础 @tool 工具 (高德 API 增强版)
# ═══════════════════════════════════════════════════════════════

@tool(description="查询城市实时天气（高德API）")
async def get_weather(city: str) -> str:
    """查询城市实时天气 + 未来4天预报。
    city: 城市名称 (中文)"""
    from common.tools.real_api_tools import amap_weather
    try:
        # 实时天气
        live = await amap_weather(city, "base")
        lives = live.get("lives", [])
        # 预报
        forecast = await amap_weather(city, "all")
        forecasts = forecast.get("forecasts", [{}])[0].get("casts", [])

        lines = [f"🌤️ {city}天气:"]
        if lives:
            w = lives[0]
            lines.append(f"  实时: {w.get('weather','?')} {w.get('temperature','?')}°C | "
                        f"湿度{w.get('humidity','?')}% | {w.get('winddirection','?')}风{w.get('windpower','?')}级")

        if forecasts:
            lines.append(f"  未来预报:")
            for day in forecasts[:4]:
                lines.append(f"    {day.get('date','?')}: {day.get('dayweather','?')} "
                           f"{day.get('nighttemp','?')}~{day.get('daytemp','?')}°C")

        return "\n".join(lines)
    except Exception as e:
        return f"天气查询失败: {e}"


@tool(description="搜索城市热门景点")
def search_attractions(city: str, top_k: int = 3) -> str:
    """搜索景点。
    city: 城市名称
    top_k: 返回数量"""
    spots = ATTRACTIONS_DB.get(city, ["热门景点"])[:top_k]
    return f"{city}景点: " + "、".join(spots)


@tool(description="搜索酒店（高德POI实时数据+价格估算）")
def search_hotels(city: str, budget_per_night: float = 500) -> str:
    """搜索酒店——高德地图POI搜索 + 星级价格估算。
    city: 城市名称
    budget_per_night: 每晚预算上限"""
    import asyncio as _asyncio
    
    # 按预算选关键词
    if budget_per_night <= 150:
        keywords = "青旅|招待所|经济型酒店"
    elif budget_per_night <= 350:
        keywords = "快捷酒店|民宿|商务酒店"
    elif budget_per_night <= 600:
        keywords = "四星级|精品酒店|度假酒店"
    else:
        keywords = "五星级|豪华酒店"
    
    async def _search():
        from common.tools.real_api_tools import amap_search_poi
        result = await amap_search_poi(keywords=keywords, city=city, types="住宿服务", offset=8)
        pois = result.get("pois", [])
        if not pois:
            return f"{city}未找到{budget_per_night}元以下酒店"
        
        lines = [f"🏨 {city} 酒店推荐 (预算≤¥{budget_per_night}/晚):"]
        for p in pois[:5]:
            name = p.get("name", "?")
            rating = p.get("rating", "?")
            addr = p.get("address", "")[:25]
            ptype = p.get("type", "")
            # 根据类型和星级估算价格
            if "五星" in ptype: est = "¥600-1200"
            elif "四星" in ptype: est = "¥350-600"
            elif "民宿" in ptype or "精品" in name: est = "¥200-400"
            elif "快捷" in name or "商务" in ptype: est = "¥150-300"
            elif "青旅" in name or "招待所" in ptype: est = "¥50-150"
            else: est = "¥200-500"
            lines.append(f"  {name} | ⭐{rating} | {est} | {addr}")
        return "\n".join(lines)
    
    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(_asyncio.run, _search())
                return future.result(timeout=10)
        return _asyncio.run(_search())
    except Exception as e:
        logger.warning(f"高德酒店搜索失败: {e}")
        # 回退到静态数据
        candidates = [h for h in HOTELS_DB if h["price"] <= budget_per_night]
        if not candidates:
            return f"{city}无{budget_per_night}元以下酒店"
        best = max(candidates, key=lambda h: h["rating"])
        return f"{best['name']} ¥{best['price']}/晚 {best['rating']}分 位于{best['location']}"


# ═══════════════════════════════════════════════════════════════
# 高德真实 API 工具 (阶段五增强)
# ═══════════════════════════════════════════════════════════════

@tool(description="搜索城市美食/餐厅（高德POI实时搜索）")
def search_restaurants(city: str, cuisine: str = "特色美食", top_k: int = 5) -> str:
    """
    搜索城市美食和餐厅——高德地图POI实时数据。
    city: 城市名称
    cuisine: 菜系或美食类型 (如 火锅/川菜/小吃/串串/烧烤)
    top_k: 返回前N家
    """
    import asyncio as _asyncio
    from common.tools.real_api_tools import amap_search_poi

    async def _search():
        result = await amap_search_poi(keywords=cuisine, city=city, types="餐饮", offset=top_k)
        pois = result.get("pois", [])
        if not pois:
            return f"在{city}未找到{cuisine}相关餐厅，建议试试其他关键词"

        lines = [f"🍜 {city} · {cuisine} 推荐 (评分/人均):"]
        for i, p in enumerate(pois[:top_k], 1):
            name = p.get("name", "?")
            rating = p.get("rating", "N/A")
            cost = p.get("cost", "N/A")
            addr = p.get("address", "")
            lines.append(f"  {i}. {name} | ⭐{rating} | ¥{cost}/人 | {addr[:30]}")
        return "\n".join(lines)

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(_asyncio.run, _search())
                return future.result(timeout=10)
        return _asyncio.run(_search())
    except Exception as e:
        logger.warning(f"高德美食搜索失败[{city}/{cuisine}]: {e}")
        return f"{city}美食推荐: 宽窄巷子小吃、锦里夜市、春熙路美食街 (离线数据)"


@tool(description="查询两点间驾车路线距离和时间（高德API：geocode+driving）")
def get_directions(origin: str, destination: str, city: str = "") -> str:
    """
    查询两地点之间的驾车路线——先地理编码获取坐标，再路径规划。
    origin: 起点名称 (如 "宽窄巷子")
    destination: 终点名称 (如 "锦里")
    city: 城市名
    """
    import asyncio as _asyncio
    from common.tools.real_api_tools import amap_direction, amap_geocode

    async def _search():
        # 并发地理编码
        o_geo, d_geo = await _asyncio.gather(
            amap_geocode(origin, city),
            amap_geocode(destination, city),
        )
        o_loc = o_geo.get("location", "")
        d_loc = d_geo.get("location", "")
        
        if not o_loc or not d_loc:
            return f"🚶 {origin} → {destination} | 地址解析失败，约30分钟步行"

        # 用坐标调驾车API
        route = await amap_direction(origin=o_loc, destination=d_loc)
        dist = route.get("distance", "?")
        dur = route.get("duration", "?")
        
        if dist in ("?", "N/A", "") or dur in ("?", "N/A", ""):
            return f"🚗 {origin} → {destination} | 路线查询失败"
        
        dist_km = float(dist) / 1000
        dur_min = int(float(dur)) / 60
        taxi_est = max(8, dist_km * 2.5)  # 成都起步8元，每公里2.5元
        return f"🚗 {origin} → {destination} | {dist_km:.1f}km | 驾车{dur_min:.0f}分钟 | 打车约¥{taxi_est:.0f}"

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(_asyncio.run, _search())
                return future.result(timeout=15)
        return _asyncio.run(_search())
    except Exception as e:
        logger.warning(f"高德路线规划失败[{origin}→{destination}]: {e}")
        return f"🚶 {origin} → {destination} | 约30分钟 | 建议打车约¥25 (估算)"


@tool(description="查询周边设施（高德POI周边搜索）")
def search_nearby(city: str, location: str, keywords: str = "购物|超市|医院|银行") -> str:
    """
    搜索指定地点周边的设施——高德POI周边搜索。
    city: 城市名称
    location: 中心地点 (如 "春熙路")
    keywords: 设施类型 (如 医院/药店/超市/银行)
    """
    import asyncio as _asyncio
    from common.tools.real_api_tools import amap_search_poi

    async def _search():
        result = await amap_search_poi(keywords=keywords, city=city, offset=5)
        pois = result.get("pois", [])
        if not pois:
            return f"{location}周边未找到{keywords}"
        lines = [f"📍 {location} 周边 {keywords}:"]
        for p in pois[:5]:
            lines.append(f"  • {p.get('name')} | {p.get('address','')[:30]}")
        return "\n".join(lines)

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(_asyncio.run, _search())
                return future.result(timeout=10)
        return _asyncio.run(_search())
    except Exception as e:
        logger.warning(f"周边搜索失败: {e}")
        return f"{location}周边: 便利店、药店、银行均在步行范围内 (离线估算)"


# ═══════════════════════════════════════════════════════════════
# 四个 BaseAgent 节点 (增强版: 美食+路线)
# ═══════════════════════════════════════════════════════════════

PARSE_PROMPT = """从用户输入提取旅行参数，返回 JSON。
格式: {"city":"城市","budget":数字,"days":数字,"people":数字,"preferences":["偏好1","偏好2"]}
规则: 仔细阅读用户输入，准确提取每个字段。城市名必须从原文中提取，不要臆测替换。
示例: "我要去苏州玩三天" → city="苏州", days=3
示例: "3个人预算三千" → people=3, budget=3000
只返回 JSON，不要加解释。"""

parse_agent = BaseAgent(
    name="输入解析器",
    system_prompt=PARSE_PROMPT,
    tools=[],
)

GUIDE_PROMPT = """你是当地资深向导 + 美食探店博主。

任务: 根据 state 中的 city/days/budget/preferences 规划完整行程。

你必须调用以下工具 (每类最多2-3次，不要过度调用):
1. get_weather(city) → 先查天气，影响穿衣和行程建议 (调1次)
2. search_attractions(city) → 获取热门景点 (调1次)
3. search_restaurants(city, cuisine) → 推荐2-3类当地特色美食 (调2-3次,选最有代表性的菜系)
4. get_directions(起点, 终点, city) → 仅查询关键景点间路线 (调3-4次,选距离最远的)

每个景点的门票参考:
- 故宫¥60, 长城¥40, 颐和园¥30, 天坛¥34, 大熊猫基地¥55, 迪士尼¥399, 南山寺¥129
- 其他景点默认¥50

返回 JSON 格式:
{
  "weather": "天气信息 (从get_weather结果中提取)",
  "itinerary": [
    {
      "day": 1,
      "attractions": ["景点A", "景点B", "景点C"],
      "food": {"breakfast": "早餐推荐", "lunch": "午餐推荐", "dinner": "晚餐推荐"},
      "routes": ["景点A→景点B: 约3km 打车¥15", "景点B→景点C: 步行10分钟"],
      "notes": "游玩建议/注意事项"
    }
  ],
  "food_summary": "城市必吃: 列举3-5样当地代表性美食",
  "tips": "实用出行建议"
}

规则:
- 每天2-3个景点，考虑地理位置邻近
- 每天必须包含早/午/晚三餐推荐
- 景点之间给出交通方式和预估时间/费用
- 根据 preferences 调整风格 (如"美食"偏好则多推荐餐厅)
只返回 JSON。"""

guide_agent = BaseAgent(
    name="本地土著向导",
    system_prompt=GUIDE_PROMPT,
    tools=[search_attractions, search_restaurants, get_directions, get_weather],
    max_turns=15,
)

HOTEL_PROMPT = """你是酒店预订专家。根据 state 中的 budget/days/people 推荐酒店。

人均每晚预算 = budget / people / days * 0.4

调用 search_hotels(city, budget_per_night=人均预算) 查询高德地图真实酒店数据。
返回的酒店包含真实名称/评分/地址，价格是星级估算值（非实时报价）。

返回 JSON:
{
  "hotels": [
    {
      "name":"酒店名",
      "price_per_night":价格(取估算中位数),
      "rating":评分,
      "location":"位置",
      "reason":"推荐理由 (考虑离景点距离/交通/性价比)"
    }
  ],
  "choice_reason":"综合推荐理由 (含价格估算说明)"
}

如果 state 中有 _backtrack_count > 0，说明上次超支了，降低 budget_per_night 重新查询。
只返回 JSON。"""

hotel_agent = BaseAgent(
    name="酒店专家",
    system_prompt=HOTEL_PROMPT,
    tools=[search_hotels, get_weather],
    max_turns=8,
)

FINANCE_PROMPT = """你是财务精算师。根据 state 核价。

费用标准:
- 酒店: 从 hotels 中取 price_per_night * (days-1) 晚
- 餐饮: ¥150/人/天 (节省模式) 或 ¥300/人/天 (美食模式)
- 市内交通: ¥80/人/天
- 门票: 参考行程中标注的价格

返回 JSON:
{
  "total_cost": 总费用,
  "budget_status": "within_budget" | "over_budget",
  "per_person": 人均费用,
  "breakdown": {
    "hotel": 酒店总费,
    "food": 餐饮总费,
    "transport": 交通总费,
    "tickets": 门票总费
  },
  "analysis": "费用分析说明"
}

只返回 JSON。"""

finance_agent = BaseAgent(
    name="财务精算师",
    system_prompt=FINANCE_PROMPT,
    tools=[],
    max_turns=6,
)


# ═══════════════════════════════════════════════════════════════
# 条件路由
# ═══════════════════════════════════════════════════════════════

def route_after_finance(state: dict) -> Tuple[Optional[str], bool]:
    """财务节点后的条件路由。"""
    status = state.get("budget_status", "within_budget")
    if status == "over_budget":
        logger.warning("⚠️ 超支! 回退到 hotel")
        return "hotel", True
    return None, False


# ═══════════════════════════════════════════════════════════════
# Orchestrator 构建
# ═══════════════════════════════════════════════════════════════

async def log_listener(event_type: str, data: dict):
    """EventBus 监听器：打印节点执行日志。"""
    node = data.get("node", "?")
    update = data.get("update", {})
    visible = {k: v for k, v in update.items()
               if not k.startswith("_") and k not in ("response",)}
    if visible:
        logger.info(f"  📤 [{node}] {json.dumps(visible, ensure_ascii=False)[:200]}")


def build_orchestrator() -> Orchestrator:
    """构建旅游规划编排器。"""
    bus = EventBus()
    bus.subscribe("node:complete", log_listener)

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

    orch.bus.subscribe("node:complete", log_listener)
    orch.bus.subscribe("orchestrator:backtrack",
                       lambda t, d: logger.warning(
                           f"↩ 回溯: {d.get('from')} → {d.get('to')} "
                           f"({d.get('count')}/{d.get('max')})"))

    orch.add_node("parse", parse_agent)
    orch.add_node("guide", guide_agent)
    orch.add_node("hotel", hotel_agent)
    orch.add_node("finance", finance_agent)
    orch.set_route("finance", route_after_finance)

    logger.info(f"🚀 自研框架启动: {query}")
    state = await orch.run({"user_query": query})
    return state
