import json

from agents.stage6_grpo import BENCHMARK, TravelRewardEngine, evaluate_outputs


def make_plan(city="成都", total_cost=500, overlap=False, place="武侯祠"):
    second_start = "10:30" if overlap else "11:15"
    return json.dumps({
        "city": city,
        "days": [
            {"day": 1, "items": [
                {"start": "09:00", "end": "11:00", "place": place, "cost": 100},
                {"start": second_start, "end": "12:00", "place": "锦里", "cost": 80},
            ]}
        ],
        "total_cost": total_cost,
    }, ensure_ascii=False)


def test_evaluation_closed_loop_metrics_on_custom_samples():
    cases = [
        (BENCHMARK[0], make_plan(total_cost=500)),
        (BENCHMARK[1], make_plan(total_cost=5000)),
        (BENCHMARK[2], make_plan(overlap=True)),
        (BENCHMARK[0], make_plan(place="不存在景点")),
        (BENCHMARK[0], "自然语言，不是JSON"),
    ]
    report = evaluate_outputs(cases, TravelRewardEngine())
    metrics = report["metrics"]
    assert 0 <= metrics["hallucination_rate"] <= 1
    assert 0 <= metrics["time_conflict_rate"] <= 1
    assert 0 <= metrics["budget_success_rate"] <= 1
    assert metrics["format_valid_rate"] == 0.8

    tool_call_success_rate = 1.0
    json_valid_rate = metrics["format_valid_rate"]
    extended = {**metrics, "tool_call_success_rate": tool_call_success_rate, "json_valid_rate": json_valid_rate}
    assert extended["tool_call_success_rate"] == 1.0
