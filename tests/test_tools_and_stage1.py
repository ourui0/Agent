from common.tools.travel_tools import (
    check_visa,
    convert_currency,
    get_weather,
    search_attractions,
    search_flights,
    search_hotels,
    split_bill,
)
from agents.stage1_plan_solve import PlanAndSolveAgent
from agents.stage1_react import ReActAgent
from agents.stage1_reflection import ReflectionAgent


def test_travel_tools_return_structured_strings():
    assert "成都" in get_weather("成都", "2026-06-01")
    assert "热门景点" in search_attractions("北京", top_k=2)
    assert "推荐" in search_hotels("成都", budget_per_night=300)
    assert "北京" in search_flights("北京", "成都")
    assert "CNY" in convert_currency(10, "USD")
    assert "每人" in split_bill(100, 4)
    assert "泰国" in check_visa("中国", "泰国") or "免签" in check_visa("中国", "泰国")


def test_travel_tools_fallbacks():
    assert "暂无" in get_weather("火星")
    assert "暂无" in search_attractions("火星")
    assert "未找到" in search_hotels("成都", budget_per_night=1)
    assert "人数必须大于0" in split_bill(100, 0)
    assert "不支持" in convert_currency(1, "XXX")


def test_stage1_react_flow_finishes_with_mock(registry):
    result = ReActAgent(registry, max_iterations=6).run("三亚3天怎么玩")
    assert "三亚" in result
    assert "亚龙湾" in result or "天涯海角" in result


def test_stage1_plan_and_solve_generates_and_executes_plan(registry):
    agent = PlanAndSolveAgent(registry)
    plan = agent._generate_plan("三亚3天")
    assert plan
    assert all(step["action"] in registry.tool_names for step in plan)
    results = agent._execute_plan(plan)
    assert results


def test_stage1_reflection_triggers_correction(registry):
    result = ReflectionAgent(registry, max_iterations=1).run("三亚3天，预算1000")
    assert "修正" in result or "优化" in result or "餐饮" in result
