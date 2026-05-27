"""
LangGraph 节点 — 引用 common.tools 的数据源。
"""

import json, logging
from typing import Any, Dict, List

from common.llm_client import LLMClient
from common.tools import (
    ATTRACTIONS_DB, HOTELS_DB, ATTRACTION_COST, DEFAULT_ATTRACTION_COST,
)
from .stage2_state import TravelState, HotelRecord, DayPlan

logger = logging.getLogger(__name__)

MEAL_COST = 200; TRANSPORT_COST = 50

# ═══════════════════════════════════════════════════════
# parse_input
# ═══════════════════════════════════════════════════════
PARSE_PROMPT = """从输入提取旅行参数，返回 JSON。
{query}
格式: {{"city":"","budget":0,"days":0,"people":0}}
默认: city=北京, budget=3000, days=3, people=1。只返回 JSON。"""

def parse_input_node(state: TravelState) -> dict:
    logger.info("📥 [parse] 解析...")
    llm = LLMClient.get()
    resp = llm.chat_json([{"role": "user", "content": PARSE_PROMPT.format(query=state["user_query"])}])
    return {
        "city": resp.get("city", "北京"), "budget": float(resp.get("budget", 3000)),
        "days": int(resp.get("days", 3)), "people": int(resp.get("people", 1)),
        "current_agent": "parse_input",
        "logs": [f"解析: {resp.get('city','?')} {resp.get('days','?')}天 {resp.get('people','?')}人 ¥{resp.get('budget','?')}"],
    }

# ═══════════════════════════════════════════════════════
# local_guide
# ═══════════════════════════════════════════════════════
GUIDE_PROMPT = """你是{city}土著导游，规划{days}天行程。
景点: {attractions}
返回 JSON: {{"itinerary":[{{"day":1,"attractions":["景点"],"notes":"提示"}}],"tips":"建议"}}
规则: 每天2-3个景点，注意位置邻近。只返回 JSON。"""

def local_guide_node(state: TravelState) -> dict:
    city = state.get("city", "北京"); days = state.get("days", 3)
    attractions = ATTRACTIONS_DB.get(city, ["热门景点"])
    logger.info(f"🏖️  [guide] {city} {days}天...")
    llm = LLMClient.get()
    resp = llm.chat_json([{"role": "user", "content": GUIDE_PROMPT.format(
        city=city, days=days, attractions=", ".join(attractions))}])
    itinerary = [DayPlan(day=i.get("day", j+1), attractions=i.get("attractions", []), notes=i.get("notes", ""))
                 for j, i in enumerate(resp.get("itinerary", [])) if isinstance(i, dict)]
    return {"itinerary": itinerary, "current_agent": "local_guide",
            "logs": [f"行程: {len(itinerary)}天"]}

# ═══════════════════════════════════════════════════════
# hotel_expert
# ═══════════════════════════════════════════════════════
HOTEL_PROMPT = """你是酒店专家。
目的地: {city} | {people}人 | 预算¥{budget} | {days}天
{revision_hint}
可选:
{hotel_list}
返回 JSON: {{"hotels":[{{"name":"","price_per_night":0,"rating":0,"location":"","reason":""}}],"choice_reason":""}}
{revision_rule}
只返回 JSON。"""

def hotel_expert_node(state: TravelState) -> dict:
    city = state.get("city", "北京"); budget = state.get("budget", 3000.0)
    days = state.get("days", 3); people = state.get("people", 1)
    rev = state.get("revision_count", 0)
    per_night = (budget / people / max(days, 1)) * 0.4

    rev_hint = f"⚠️ 超支！每晚≤¥{per_night*0.7:.0f}" if rev else ""
    rev_rule = "- 🔴 必须比上一轮便宜30%" if rev else ""
    hotel_text = "\n".join(f"- {h['name']}: ¥{h['price']}/晚 {h['rating']}分 {h['location']}" for h in HOTELS_DB)

    logger.info(f"🏨 [hotel] 轮次{rev} 上限¥{per_night:.0f}...")
    llm = LLMClient.get()
    resp = llm.chat_json([{"role": "user", "content": HOTEL_PROMPT.format(
        city=city, people=people, budget=budget, days=days,
        revision_hint=rev_hint, hotel_list=hotel_text, revision_rule=rev_rule)}])

    raw_hotels = resp.get("hotels", []) or [HOTELS_DB[0]]
    hotels = [HotelRecord(name=h.get("name","?"), price_per_night=float(h.get("price_per_night",h.get("price",0))),
                          rating=float(h.get("rating",3.5)), location=h.get("location",""), reason=h.get("reason",""))
              for h in raw_hotels if isinstance(h, dict)]
    return {"hotels": hotels, "current_agent": "hotel_expert",
            "logs": [f"酒店: {hotels[0]['name']} ¥{hotels[0]['price_per_night']}/晚"]}

# ═══════════════════════════════════════════════════════
# financial_actuary
# ═══════════════════════════════════════════════════════
FINANCIAL_PROMPT = """你是财务精算师。
{people}人 {days}天 预算¥{budget}
行程: {itinerary_text}
酒店: {hotels_text}
标准: 餐饮¥{meal}/天 交通¥{transport}/天
返回 JSON: {{"total_cost":0,"budget_status":"within_budget|over_budget","per_person":0,"analysis":""}}
只返回 JSON。"""

def financial_actuary_node(state: TravelState) -> dict:
    people = state.get("people", 1); days = state.get("days", 3)
    budget = state.get("budget", 3000.0); rev = state.get("revision_count", 0)

    # 构建行程文本
    it_lines = []
    for day in state.get("itinerary", []):
        spots = day.get("attractions", [])
        costs = [f"{s}(¥{ATTRACTION_COST.get(s, DEFAULT_ATTRACTION_COST)})" for s in spots]
        it_lines.append(f"  Day{day.get('day','?')}: " + " → ".join(costs))

    # 构建酒店文本
    ht_lines = [f"  {h.get('name','?')}: ¥{h.get('price_per_night',0)}/晚" for h in state.get("hotels", [])]

    logger.info(f"💰 [finance] 轮次{rev}...")
    llm = LLMClient.get()
    resp = llm.chat_json([{"role": "user", "content": FINANCIAL_PROMPT.format(
        people=people, days=days, budget=budget,
        itinerary_text="\n".join(it_lines) if it_lines else "无",
        hotels_text="\n".join(ht_lines) if ht_lines else "未选",
        meal=MEAL_COST, transport=TRANSPORT_COST)}])

    total = resp.get("total_cost", 0.0)
    status = "over_budget" if total > budget else "within_budget"
    new_rev = rev + 1 if status == "over_budget" else rev

    return {"total_cost": total, "budget_status": status, "revision_count": new_rev,
            "current_agent": "financial_actuary",
            "logs": [f"费用: ¥{total:.0f} ({'✅' if status=='within_budget' else '⚠️超支¥'+str(total-budget)}) 人均¥{resp.get('per_person',0)}"]}
