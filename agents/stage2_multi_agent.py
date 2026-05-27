"""AutoGen 混编 — 财务-酒店博弈节点。"""

import json, logging, os
from typing import Any, Dict, List

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_ext.models.openai import OpenAIChatCompletionClient

from common.tools import HOTELS_DB
from .stage2_state import TravelState, HotelRecord

logger = logging.getLogger(__name__)


def negotiation_node(state: TravelState) -> dict:
    """AutoGen 博弈节点：财务和酒店直接对话达成降价共识。"""
    city = state.get("city", "北京"); budget = state.get("budget", 3000.0)
    total_cost = state.get("total_cost", 0.0); days = state.get("days", 3)
    people = state.get("people", 1); rev = state.get("revision_count", 0)
    over = total_cost - budget
    target = max((budget / people / max(days, 1)) * 0.25, 80)

    logger.info(f"🤝 [negotiation] 超支¥{over:.0f} 目标≤¥{target:.0f}/晚")

    alt_text = "\n".join(f"- {h['name']}: ¥{h['price']}/晚 {h['rating']}分" for h in HOTELS_DB[:3])

    try:
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        model_client = OpenAIChatCompletionClient(model="deepseek-chat", api_key=api_key, base_url="https://api.deepseek.com")

        financial = AssistantAgent("财务精算师", model_client, system_message=f"""超支¥{over:.0f}，要求酒店降价。
目标≤¥{target:.0f}/晚。可选: {alt_text}。合理则回复"成交"。""")
        hotel = AssistantAgent("酒店专家", model_client, system_message=f"""目的地{city} {people}人{days}天。
可选: {alt_text}。积极降价协商，底价¥{target:.0f}/晚。""")

        team = RoundRobinGroupChat([financial, hotel], MaxMessageTermination(8))
        result = team.run(task=f"超支¥{over:.0f}，请协商降价。")

        # 提取结果
        for msg in reversed(result.messages if hasattr(result, 'messages') else []):
            content = str(msg.content) if hasattr(msg, 'content') else str(msg)
            for h in HOTELS_DB:
                if h["name"] in content:
                    return {"hotels": [HotelRecord(name=h["name"], price_per_night=h["price"],
                              rating=h["rating"], location=h["location"], reason="博弈达成")],
                            "revision_count": rev+1, "current_agent": "negotiation",
                            "logs": [f"博弈: → {h['name']} ¥{h['price']}/晚"]}
    except Exception as e:
        logger.error(f"博弈失败: {e}")

    # 回退
    cheapest = min(HOTELS_DB, key=lambda h: h["price"])
    return {"hotels": [HotelRecord(name=cheapest["name"], price_per_night=cheapest["price"],
              rating=cheapest["rating"], location=cheapest["location"], reason="博弈失败，最低价")],
            "revision_count": rev+1, "current_agent": "negotiation",
            "logs": [f"回退: {cheapest['name']} ¥{cheapest['price']}/晚"]}
