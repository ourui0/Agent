"""LangGraph StateGraph 组装。"""

import logging
from typing import Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .stage2_state import TravelState
from .stage2_nodes import parse_input_node, local_guide_node, hotel_expert_node, financial_actuary_node

logger = logging.getLogger(__name__)


def route_after_finance(state: TravelState) -> Literal["hotel_expert", "__end__"]:
    status = state.get("budget_status", "within_budget")
    rev = state.get("revision_count", 0)
    max_rev = state.get("max_revisions", 3)
    if status == "over_budget" and rev < max_rev:
        logger.warning(f"🔄 超支 修订{rev}/{max_rev} → 重选酒店")
        return "hotel_expert"
    if status == "over_budget":
        logger.warning(f"⛔ 达上限{max_rev}次，强制结束")
    return END


def build_graph() -> StateGraph:
    builder = StateGraph(TravelState)
    builder.add_node("parse_input", parse_input_node)
    builder.add_node("local_guide", local_guide_node)
    builder.add_node("hotel_expert", hotel_expert_node)
    builder.add_node("financial_actuary", financial_actuary_node)

    builder.add_edge(START, "parse_input")
    builder.add_edge("parse_input", "local_guide")
    builder.add_edge("local_guide", "hotel_expert")
    builder.add_edge("hotel_expert", "financial_actuary")
    builder.add_conditional_edges("financial_actuary", route_after_finance,
                                  {"hotel_expert": "hotel_expert", END: END})

    graph = builder.compile(checkpointer=MemorySaver())
    logger.info("🏗️ StateGraph 编译完成")
    return graph
