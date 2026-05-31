import asyncio

from agents.stage3_travel import run_travel_plan


def test_stage3_travel_agent_simple_query_smoke(monkeypatch):
    async def scenario():
        state = await run_travel_plan("2人北京3天，预算3000", 1)
        assert state.get("city")
        assert "budget_status" in state or "error" in state

    asyncio.run(scenario())
