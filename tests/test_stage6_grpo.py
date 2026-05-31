import json

from agents.stage6_grpo import (
    BENCHMARK,
    TravelConstraints,
    TravelRewardEngine,
    bucket_report_markdown,
    evaluate_outputs,
    evolution_matrix,
    sample_bad_plan,
    sample_valid_plan,
)


def test_reward_engine_invalid_json_gets_hard_penalty():
    engine = TravelRewardEngine()
    result = engine.score("{bad json", TravelConstraints("成都", 1, 1000))
    assert result.score == -100.0
    assert result.details["format_valid"] is False


def test_reward_engine_valid_smooth_budget_timeline_components():
    engine = TravelRewardEngine()
    constraints = TravelConstraints("成都", 2, 1500, list(TravelRewardEngine.PLACE_COORDS.keys()))
    result = engine.score(sample_valid_plan(), constraints)
    components = result.details["component_scores"]
    assert result.details["format_valid"] is True
    assert components["route"] == 5.0
    assert components["budget"] == 5.0
    assert components["timeline"] == 5.0
    assert result.score > 0


def test_reward_engine_budget_overflow_and_timeline_conflict():
    engine = TravelRewardEngine()
    constraints = TravelConstraints("成都", 1, 1000, list(TravelRewardEngine.PLACE_COORDS.keys()))
    result = engine.score(sample_bad_plan(), constraints)
    components = result.details["component_scores"]
    assert components["timeline"] == -50.0
    assert -10.0 <= components["budget"] < 0
    assert result.details["timeline_conflicts"]
    assert "火星古城" in result.details["unknown_places"]


def test_reward_engine_budget_penalty_caps_at_minus_ten():
    engine = TravelRewardEngine()
    plan = json.loads(sample_valid_plan())
    plan["total_cost"] = 999999
    result = engine.score(json.dumps(plan, ensure_ascii=False), TravelConstraints("成都", 1, 100))
    assert result.details["component_scores"]["budget"] == -10.0


def test_evaluator_outputs_metrics_and_matrix():
    outputs = [
        (BENCHMARK[0], sample_valid_plan()),
        (BENCHMARK[1], sample_bad_plan()),
        (BENCHMARK[2], "not json"),
    ]
    report = evaluate_outputs(outputs)
    metrics = report["metrics"]
    bucketed = report["bucket_metrics"]
    assert set(metrics) >= {
        "avg_reward",
        "format_valid_rate",
        "time_conflict_rate",
        "budget_success_rate",
        "hallucination_rate",
    }
    assert any(key.startswith("budget:") for key in bucketed)
    assert any(key.startswith("scenario:") for key in bucketed)
    assert "| bucket | cases | avg_reward |" in bucket_report_markdown(bucketed)
    matrix = evolution_matrix({"阶段六-GRPO": metrics})
    assert "| 阶段六-GRPO |" in matrix


def test_stage6_benchmark_has_fifty_bucketed_cases():
    assert len(BENCHMARK) == 50
    ids = {case["id"] for case in BENCHMARK}
    assert len(ids) == 50
    scenarios = {case["bucket"]["scenario"] for case in BENCHMARK}
    assert scenarios >= {
        "tight_budget",
        "timeline_trap",
        "route_smoothness",
        "family_slow_pace",
        "anti_hallucination",
    }
    budgets = {case["constraints"].budget for case in BENCHMARK}
    assert budgets == {300, 800, 1500, 2500, 4000}


def test_grpo_train_step_can_be_mocked_without_model_download(monkeypatch):
    from agents import stage6_grpo

    class FakeTrainer:
        def __init__(self, cfg, reward_engine, constraints):
            self.cfg = cfg

        def train_step(self, prompt):
            return {"loss": 0.1, "reward_mean": 1.0, "reward_std": 0.5, "kl": 0.01, "samples": []}

    monkeypatch.setattr(stage6_grpo, "GRPOTrainer", FakeTrainer)
    cfg = stage6_grpo.GRPOConfig(model_name="no-download", group_size=2)
    trainer = stage6_grpo.GRPOTrainer(cfg, TravelRewardEngine(), TravelConstraints("成都", 1, 1000))
    stats = trainer.train_step("只输出JSON")
    assert stats["loss"] == 0.1
    assert stats["kl"] == 0.01
