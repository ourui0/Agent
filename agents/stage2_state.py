"""LangGraph 状态定义。"""

from typing import Annotated, Any, List
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class HotelRecord(TypedDict, total=False):
    name: str; price_per_night: float; rating: float; location: str; reason: str


class DayPlan(TypedDict, total=False):
    day: int; attractions: List[str]; notes: str


class TravelState(TypedDict):
    user_query: str
    city: str; budget: float; days: int; people: int
    itinerary: List[DayPlan]; hotels: List[HotelRecord]
    budget_status: str; total_cost: float
    revision_count: int; max_revisions: int
    logs: Annotated[List[str], add_messages]
    current_agent: str; final_summary: str


def create_initial_state(query: str, max_revisions: int = 3) -> TravelState:
    return TravelState(
        user_query=query, city="", budget=0.0, days=0, people=0,
        itinerary=[], hotels=[], budget_status="unknown", total_cost=0.0,
        revision_count=0, max_revisions=max_revisions, logs=[],
        current_agent="__start__", final_summary="",
    )
