import asyncio

from agents.stage2_graph import route_after_finance
from agents.stage2_nodes import financial_actuary_node, hotel_expert_node, local_guide_node, parse_input_node
from agents.stage2_state import create_initial_state
from agents.stage3_framework import EventBus, FunctionalAgent, Middleware, MiddlewarePipeline, Orchestrator, tool


def test_stage2_state_and_nodes_flow_offline():
    state = create_initial_state("2个人去北京玩3天，预算3000元")
    state.update(parse_input_node(state))
    assert state["city"] == "北京"
    state.update(local_guide_node(state))
    assert state["itinerary"]
    state.update(hotel_expert_node(state))
    assert state["hotels"]
    state.update(financial_actuary_node(state))
    assert state["budget_status"] in {"within_budget", "over_budget"}


def test_stage2_budget_route_backtracks_when_over_budget():
    state = create_initial_state("预算很低")
    state["budget_status"] = "over_budget"
    state["revision_count"] = 1
    state["max_revisions"] = 3
    assert route_after_finance(state) == "hotel_expert"
    state["revision_count"] = 3
    assert route_after_finance(state) == "__end__"


def test_stage3_tool_schema_generation():
    @tool(description="测试工具")
    def sample(city: str, days: int = 3) -> str:
        return f"{city}{days}"

    meta = sample.__tool_meta__
    schema = meta.parameters["function"]["parameters"]
    assert meta.name == "sample"
    assert schema["properties"]["city"]["type"] == "string"
    assert "city" in schema["required"]
    assert "days" not in schema["required"]


def test_stage3_eventbus_middleware_orchestrator():
    async def scenario():
        events = []
        bus = EventBus()
        bus.subscribe("node:complete", lambda event, data: events.append((event, data["node"])))

        class AddMiddleware(Middleware):
            async def __call__(self, state, next_call):
                state["middleware_before"] = True
                result = await next_call(state)
                result["middleware_after"] = True
                return result

        def first(state):
            return {"value": 1}

        def second(state):
            return {"value": state["value"] + 1}

        orch = Orchestrator(bus=bus)
        orch.add_node("first", FunctionalAgent("first", first))
        pipeline = MiddlewarePipeline([AddMiddleware()], final_handler=FunctionalAgent("second", second))
        orch.add_node("second", FunctionalAgent("second", second), pipeline=pipeline)
        final = await orch.run({"user_query": "test"})
        assert final["value"] == 2
        assert final["middleware_before"] is True
        assert final["middleware_after"] is True
        assert [node for _, node in events] == ["first", "second"]

    asyncio.run(scenario())
