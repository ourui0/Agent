"""
阶段六：GRPO 强化学习训练与评估闭环

核心组件:
  - TravelRewardEngine: 多维奖励函数，约束 JSON 格式、路线、预算、时间线
  - GRPOTrainer: 原生 PyTorch + Transformers 的组采样、相对优势、clip policy loss
  - TravelEvaluator: 黄金测试集评估与六阶段指标矩阵

默认 demo 只运行奖励引擎和评估统计，不会下载大模型。真实训练需要显式调用
run_stage6_demo(train=True) 或在 main.py 中传入 --stage6-train。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import torch
    import torch.nn.functional as F
    from torch import Tensor
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:
    torch = None
    F = None
    Tensor = Any
    AutoModelForCausalLM = None
    AutoTokenizer = None

_no_grad = torch.no_grad if torch is not None else lambda: (lambda func: func)


@dataclass
class TravelConstraints:
    """用户硬约束。"""

    city: str
    days: int
    budget: float
    allowed_places: Optional[List[str]] = None


@dataclass
class RewardResult:
    """奖励引擎输出。"""

    score: float
    details: Dict[str, Any]


class TravelRewardEngine:
    """
    旅游规划多维奖励引擎。

    模型输出必须是合法 JSON，推荐 schema:
    {
      "city": "成都",
      "days": [
        {"day": 1, "items": [
          {"start": "09:00", "end": "10:30", "place": "武侯祠", "cost": 50}
        ]}
      ],
      "total_cost": 1200
    }
    """

    PLACE_COORDS = {
        "成都东站": (30.6286, 104.1417),
        "春熙路": (30.6570, 104.0807),
        "太古里": (30.6538, 104.0831),
        "宽窄巷子": (30.6745, 104.0607),
        "人民公园": (30.6595, 104.0633),
        "武侯祠": (30.6422, 104.0473),
        "锦里": (30.6434, 104.0471),
        "杜甫草堂": (30.6666, 104.0287),
        "金沙遗址博物馆": (30.6821, 104.0125),
        "熊猫基地": (30.7335, 104.1456),
        "青羊宫": (30.6685, 104.0462),
        "文殊院": (30.6789, 104.0779),
        "九眼桥": (30.6353, 104.0870),
        "成都双流机场": (30.5785, 103.9468),
    }
    TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

    def score(self, text: str, constraints: TravelConstraints) -> RewardResult:
        details = {
            "format_valid": False,
            "route_smooth": False,
            "budget_total": None,
            "budget_overflow": 0.0,
            "timeline_conflicts": [],
            "unknown_places": [],
            "component_scores": {},
        }

        try:
            plan = self._parse_json(text)
            self._validate_schema(plan)
            details["format_valid"] = True
        except Exception as exc:
            return RewardResult(-100.0, {**details, "error": f"invalid_json_or_schema: {exc}"})

        items_by_day = self._extract_items(plan)
        all_items = [item for _, items in items_by_day for item in items]
        score = 2.0
        details["component_scores"]["format"] = 2.0

        unknown_penalty = self._unknown_place_penalty(all_items, constraints, details)
        score += unknown_penalty

        conflicts = self._find_timeline_conflicts(items_by_day)
        details["timeline_conflicts"] = conflicts
        timeline_score = -50.0 if conflicts else 5.0
        details["component_scores"]["timeline"] = timeline_score
        score += timeline_score

        budget_score = self._budget_score(plan, all_items, constraints, details)
        score += budget_score

        route_score = self._route_smoothness_reward(all_items)
        details["route_smooth"] = route_score > 0
        details["component_scores"]["route"] = route_score
        score += route_score

        return RewardResult(float(score), details)

    def _parse_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
        if fenced:
            text = fenced.group(1)
        return json.loads(text)

    def _validate_schema(self, plan: Dict[str, Any]) -> None:
        if not isinstance(plan, dict):
            raise ValueError("root must be object")
        if not isinstance(plan.get("city"), str):
            raise ValueError("city must be string")
        if not isinstance(plan.get("days"), list) or not plan["days"]:
            raise ValueError("days must be non-empty list")

        for day in plan["days"]:
            if not isinstance(day, dict):
                raise ValueError("day entry must be object")
            if not isinstance(day.get("day"), int):
                raise ValueError("day must be int")
            if not isinstance(day.get("items"), list):
                raise ValueError("items must be list")
            for item in day["items"]:
                for key in ("start", "end", "place", "cost"):
                    if key not in item:
                        raise ValueError(f"missing item.{key}")
                if not self.TIME_PATTERN.match(str(item["start"])):
                    raise ValueError(f"invalid start: {item['start']}")
                if not self.TIME_PATTERN.match(str(item["end"])):
                    raise ValueError(f"invalid end: {item['end']}")
                if not isinstance(item["place"], str) or not item["place"].strip():
                    raise ValueError("place must be non-empty string")
                if not isinstance(item["cost"], (int, float)) or item["cost"] < 0:
                    raise ValueError("cost must be non-negative number")

    def _extract_items(self, plan: Dict[str, Any]) -> List[Tuple[int, List[Dict[str, Any]]]]:
        return [(int(day["day"]), list(day["items"])) for day in plan["days"]]

    def _unknown_place_penalty(
        self,
        all_items: List[Dict[str, Any]],
        constraints: TravelConstraints,
        details: Dict[str, Any],
    ) -> float:
        allowed = set(constraints.allowed_places or self.PLACE_COORDS.keys())
        unknown = [item["place"] for item in all_items if item["place"] not in allowed]
        details["unknown_places"] = unknown
        penalty = -5.0 * len(unknown)
        details["component_scores"]["unknown_place"] = penalty
        return penalty

    def _budget_score(
        self,
        plan: Dict[str, Any],
        all_items: List[Dict[str, Any]],
        constraints: TravelConstraints,
        details: Dict[str, Any],
    ) -> float:
        total_cost = self._compute_total_cost(plan, all_items)
        overflow = max(0.0, total_cost - constraints.budget)
        details["budget_total"] = total_cost
        details["budget_overflow"] = overflow
        if overflow <= 0:
            score = 5.0
        else:
            overflow_ratio = overflow / max(constraints.budget, 1.0)
            score = -min(10.0, 5.0 + 20.0 * overflow_ratio)
        details["component_scores"]["budget"] = score
        return score

    def _to_minutes(self, hhmm: str) -> int:
        hour, minute = hhmm.split(":")
        return int(hour) * 60 + int(minute)

    def _find_timeline_conflicts(
        self,
        items_by_day: List[Tuple[int, List[Dict[str, Any]]]],
    ) -> List[Dict[str, Any]]:
        conflicts = []
        for day, items in items_by_day:
            spans = []
            for index, item in enumerate(items):
                start = self._to_minutes(item["start"])
                end = self._to_minutes(item["end"])
                if end <= start:
                    conflicts.append({"day": day, "type": "negative_or_zero_duration", "item": item})
                spans.append((index, start, end, item))

            for prev, curr in zip(spans, spans[1:]):
                if prev[2] > curr[1]:
                    conflicts.append({"day": day, "type": "sequential_overlap", "prev": prev[3], "curr": curr[3]})

            ordered = sorted(spans, key=lambda x: x[1])
            for prev, curr in zip(ordered, ordered[1:]):
                if prev[2] > curr[1]:
                    conflicts.append({"day": day, "type": "interval_overlap", "a": prev[3], "b": curr[3]})
        return conflicts

    def _compute_total_cost(self, plan: Dict[str, Any], all_items: List[Dict[str, Any]]) -> float:
        item_sum = sum(float(item["cost"]) for item in all_items)
        declared = plan.get("total_cost")
        if isinstance(declared, (int, float)):
            return float(max(item_sum, declared))
        raw = json.dumps(plan, ensure_ascii=False)
        text_cost_sum = sum(float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*元", raw))
        return float(max(item_sum, text_cost_sum))

    def _haversine_km(self, a: Tuple[float, float], b: Tuple[float, float]) -> float:
        lat1, lon1 = map(math.radians, a)
        lat2, lon2 = map(math.radians, b)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6371.0 * 2.0 * math.asin(math.sqrt(h))

    def _route_distance(self, places: List[str]) -> float:
        coords = [self.PLACE_COORDS[p] for p in places if p in self.PLACE_COORDS]
        if len(coords) < 2:
            return float("inf")
        return sum(self._haversine_km(a, b) for a, b in zip(coords, coords[1:]))

    def _greedy_nearest_distance(self, places: List[str]) -> float:
        known = [p for p in places if p in self.PLACE_COORDS]
        if len(known) < 2:
            return float("inf")

        current = known[0]
        remaining = known[1:]
        total = 0.0
        while remaining:
            next_place = min(
                remaining,
                key=lambda p: self._haversine_km(self.PLACE_COORDS[current], self.PLACE_COORDS[p]),
            )
            total += self._haversine_km(self.PLACE_COORDS[current], self.PLACE_COORDS[next_place])
            current = next_place
            remaining.remove(next_place)
        return total

    def _route_smoothness_reward(self, all_items: List[Dict[str, Any]]) -> float:
        places = [item["place"] for item in all_items if item["place"] in self.PLACE_COORDS]
        if len(places) < 3:
            return 0.0
        actual = self._route_distance(places)
        greedy = self._greedy_nearest_distance(places)
        if not math.isfinite(actual) or not math.isfinite(greedy) or greedy <= 0:
            return 0.0
        return 5.0 if actual <= greedy * 1.2 else -3.0


@dataclass
class GRPOConfig:
    """GRPO 训练配置。"""

    model_name: str = "Qwen/Qwen2.5-7B-Instruct"
    group_size: int = 4
    max_new_tokens: int = 768
    temperature: float = 0.9
    top_p: float = 0.95
    clip_eps: float = 0.2
    lr: float = 1e-6
    beta_kl: float = 0.02
    device: str = "cuda"
    deepspeed_config: Optional[Dict[str, Any]] = None


class GRPOTrainer:
    """不依赖 Critic 的 GRPO 训练核心。"""

    def __init__(self, cfg: GRPOConfig, reward_engine: TravelRewardEngine, constraints: TravelConstraints):
        self._require_training_deps()
        self.cfg = cfg
        self.reward_engine = reward_engine
        self.constraints = constraints
        if not torch.cuda.is_available() and cfg.device == "cuda":
            self.cfg.device = "cpu"

        self.tokenizer = AutoTokenizer.from_pretrained(cfg.model_name, trust_remote_code=True)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            cfg.model_name,
            torch_dtype=dtype,
            trust_remote_code=True,
        ).to(self.cfg.device)
        self.ref_model = AutoModelForCausalLM.from_pretrained(
            cfg.model_name,
            torch_dtype=dtype,
            trust_remote_code=True,
        ).to(self.cfg.device)
        self.ref_model.eval()
        for param in self.ref_model.parameters():
            param.requires_grad_(False)

        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=cfg.lr)
        self.engine = None
        if cfg.deepspeed_config is not None:
            import deepspeed

            self.engine, self.optimizer, _, _ = deepspeed.initialize(
                model=self.model,
                optimizer=self.optimizer,
                config=cfg.deepspeed_config,
            )

    @staticmethod
    def _require_training_deps() -> None:
        if torch is None or AutoModelForCausalLM is None or AutoTokenizer is None:
            raise RuntimeError("阶段六训练需要安装 torch、transformers，可选安装 deepspeed。")

    def _policy(self):
        return self.engine if self.engine is not None else self.model

    def sample_group(self, prompt: str) -> Dict[str, Any]:
        input_ids = self.tokenizer(prompt, return_tensors="pt").input_ids.to(self.cfg.device)
        repeated = input_ids.repeat(self.cfg.group_size, 1)
        policy = self._policy()
        model = policy.module if hasattr(policy, "module") else policy
        model.eval()

        with torch.no_grad():
            sequences = model.generate(
                repeated,
                do_sample=True,
                temperature=self.cfg.temperature,
                top_p=self.cfg.top_p,
                max_new_tokens=self.cfg.max_new_tokens,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        prompt_len = repeated.shape[1]
        completions = sequences[:, prompt_len:]
        texts = self.tokenizer.batch_decode(completions, skip_special_tokens=True)
        rewards = [self.reward_engine.score(text, self.constraints) for text in texts]
        return {
            "prompt_ids": repeated,
            "sequences": sequences,
            "prompt_len": prompt_len,
            "texts": texts,
            "rewards": rewards,
        }

    def _sequence_logprobs(self, model, sequences: Tensor, prompt_len: int) -> Tuple[Tensor, Tensor]:
        attention_mask = sequences.ne(self.tokenizer.pad_token_id).long()
        outputs = model(input_ids=sequences, attention_mask=attention_mask)
        logits = outputs.logits[:, :-1, :]
        labels = sequences[:, 1:]
        logprobs = F.log_softmax(logits.float(), dim=-1)
        selected = logprobs.gather(-1, labels.unsqueeze(-1)).squeeze(-1)
        completion_start = max(prompt_len - 1, 0)
        selected_completion = selected[:, completion_start:]
        label_completion = labels[:, completion_start:]
        mask = label_completion.ne(self.tokenizer.pad_token_id).float()
        return selected_completion, mask

    def compute_grpo_loss(self, batch: Dict[str, Any]) -> Tuple[Tensor, Dict[str, float]]:
        sequences = batch["sequences"].to(self.cfg.device)
        prompt_len = batch["prompt_len"]
        raw_rewards = torch.tensor(
            [result.score for result in batch["rewards"]],
            dtype=torch.float32,
            device=self.cfg.device,
        )
        reward_mean = raw_rewards.mean()
        reward_std = raw_rewards.std(unbiased=False).clamp_min(1e-6)
        advantages = (raw_rewards - reward_mean) / reward_std

        policy = self._policy()
        model = policy.module if hasattr(policy, "module") else policy
        model.train()
        with torch.no_grad():
            old_logp, mask = self._sequence_logprobs(model, sequences, prompt_len)
            ref_logp, _ = self._sequence_logprobs(self.ref_model, sequences, prompt_len)

        new_logp, mask = self._sequence_logprobs(model, sequences, prompt_len)
        ratio = torch.exp(new_logp - old_logp)
        unclipped = ratio * advantages[:, None]
        clipped = torch.clamp(ratio, 1.0 - self.cfg.clip_eps, 1.0 + self.cfg.clip_eps) * advantages[:, None]
        policy_loss = -torch.minimum(unclipped, clipped)

        token_kl = torch.exp(ref_logp - new_logp) - (ref_logp - new_logp) - 1.0
        valid_tokens = mask.sum().clamp_min(1.0)
        loss = ((policy_loss + self.cfg.beta_kl * token_kl) * mask).sum() / valid_tokens
        stats = {
            "loss": float(loss.detach().cpu()),
            "reward_mean": float(reward_mean.detach().cpu()),
            "reward_std": float(reward_std.detach().cpu()),
            "adv_min": float(advantages.min().detach().cpu()),
            "adv_max": float(advantages.max().detach().cpu()),
            "kl": float(((token_kl * mask).sum() / valid_tokens).detach().cpu()),
        }
        return loss, stats

    def train_step(self, prompt: str) -> Dict[str, Any]:
        batch = self.sample_group(prompt)
        loss, stats = self.compute_grpo_loss(batch)
        if self.engine is not None:
            self.engine.backward(loss)
            self.engine.step()
        else:
            self.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.optimizer.step()

        stats["samples"] = [
            {"reward": reward.score, "details": reward.details, "text": text}
            for text, reward in zip(batch["texts"], batch["rewards"])
        ]
        return stats


_BENCHMARK_SCENARIOS = [
    {
        "name": "tight_budget",
        "instruction": "预算极紧，优先免费景点、公共交通和低价餐饮，不能超预算。",
        "tags": ["budget", "low_cost"],
    },
    {
        "name": "timeline_trap",
        "instruction": "用户强调不能出现任何时间重叠，尤其避免09:00-11:00与10:30-12:00这类连环冲突。",
        "tags": ["timeline", "overlap_trap"],
    },
    {
        "name": "route_smoothness",
        "instruction": "请按地理位置顺路安排，避免熊猫基地、市中心、机场之间来回折返。",
        "tags": ["route", "smoothness"],
    },
    {
        "name": "family_slow_pace",
        "instruction": "一家三口带老人出行，每天最多三个点，午后需要休息窗口。",
        "tags": ["family", "pace"],
    },
    {
        "name": "food_preference",
        "instruction": "用户不吃辣，需要清淡餐厅和茶馆选项，不能只推荐火锅串串。",
        "tags": ["preference", "food"],
    },
    {
        "name": "rainy_backup",
        "instruction": "预报有雨，优先室内景点，并给每天下午安排雨天备选。",
        "tags": ["weather", "backup"],
    },
    {
        "name": "arrival_late",
        "instruction": "第一天14:30才到成都东站，不能安排上午活动，也不能压缩交通时间。",
        "tags": ["arrival", "time_window"],
    },
    {
        "name": "early_flight",
        "instruction": "最后一天18:00从双流机场离开，15:30后必须预留去机场交通时间。",
        "tags": ["departure", "time_window"],
    },
    {
        "name": "museum_booking",
        "instruction": "博物馆类景点需要安排在白天，并提醒预约，不能放到夜间。",
        "tags": ["booking", "museum"],
    },
    {
        "name": "anti_hallucination",
        "instruction": "只能使用成都真实景点，严禁编造不存在的景点、酒店或交通枢纽。",
        "tags": ["hallucination", "grounding"],
    },
]


def build_benchmark() -> List[Dict[str, Any]]:
    """构建 50 条阶段六黄金测试集，覆盖预算、天数、时间窗和路线陷阱。"""

    budgets = [300, 800, 1500, 2500, 4000]
    city = "成都"
    allowed_places = list(TravelRewardEngine.PLACE_COORDS.keys())
    cases: List[Dict[str, Any]] = []

    for budget_index, budget in enumerate(budgets):
        for scenario_index, scenario in enumerate(_BENCHMARK_SCENARIOS):
            days = 1 + ((budget_index + scenario_index) % 5)
            case_id = f"chengdu_{scenario['name']}_{days}d_{budget}rmb"
            prompt = (
                "只输出合法JSON，不要输出解释文字。"
                f"任务：{days}天{city}旅行，总预算{budget}元。"
                "每个行程项必须包含start/end/place/cost，顶层必须包含city/days/total_cost。"
                f"特殊约束：{scenario['instruction']}"
            )
            cases.append({
                "id": case_id,
                "prompt": prompt,
                "constraints": TravelConstraints(city, days, budget, allowed_places),
                "tags": [*scenario["tags"], f"{days}d", f"budget_{budget}"],
                "difficulty": "hard" if budget <= 800 or days >= 4 else "medium",
                "bucket": {
                    "city": city,
                    "days": days,
                    "budget": budget,
                    "scenario": scenario["name"],
                    "grid": f"b{budget_index}_s{scenario_index}",
                },
            })

    return cases[:50]


BENCHMARK = build_benchmark()


class TravelEvaluator:
    """黄金测试集定量分析器。"""

    def __init__(self, model, tokenizer, reward_engine: TravelRewardEngine, device: str):
        if torch is None:
            raise RuntimeError("TravelEvaluator 生成模式需要安装 torch 和 transformers。")
        self.model = model
        self.tokenizer = tokenizer
        self.reward_engine = reward_engine
        self.device = device if torch.cuda.is_available() else "cpu"

    @_no_grad()
    def generate_one(self, prompt: str, max_new_tokens: int = 768) -> str:
        ids = self.tokenizer(prompt, return_tensors="pt").input_ids.to(self.device)
        out = self.model.generate(
            ids,
            do_sample=False,
            max_new_tokens=max_new_tokens,
            pad_token_id=self.tokenizer.pad_token_id,
            eos_token_id=self.tokenizer.eos_token_id,
        )
        return self.tokenizer.decode(out[0, ids.shape[1]:], skip_special_tokens=True)

    def evaluate(self, benchmark: List[Dict[str, Any]]) -> Dict[str, Any]:
        outputs = [(case, self.generate_one(case["prompt"])) for case in benchmark]
        return evaluate_outputs(outputs, self.reward_engine)


def evaluate_outputs(
    outputs: List[Tuple[Dict[str, Any], str]],
    reward_engine: Optional[TravelRewardEngine] = None,
) -> Dict[str, Any]:
    """评估已有模型输出，便于离线对比阶段一到阶段六。"""

    engine = reward_engine or TravelRewardEngine()
    rows = []
    for case, text in outputs:
        result = engine.score(text, case["constraints"])
        details = result.details
        rows.append({
            "id": case["id"],
            "reward": result.score,
            "format_valid": bool(details.get("format_valid")),
            "timeline_ok": len(details.get("timeline_conflicts", [])) == 0,
            "budget_ok": float(details.get("budget_overflow") or 0.0) <= 0.0,
            "hallucination_ok": len(details.get("unknown_places", [])) == 0,
            "bucket": dict(case.get("bucket", {})),
            "tags": list(case.get("tags", [])),
            "difficulty": case.get("difficulty", "unknown"),
            "raw_output": text,
            "details": details,
        })

    total = max(len(rows), 1)
    metrics = {
        "avg_reward": sum(row["reward"] for row in rows) / total,
        "format_valid_rate": sum(row["format_valid"] for row in rows) / total,
        "time_conflict_rate": 1.0 - sum(row["timeline_ok"] for row in rows) / total,
        "budget_success_rate": sum(row["budget_ok"] for row in rows) / total,
        "hallucination_rate": 1.0 - sum(row["hallucination_ok"] for row in rows) / total,
    }
    return {"metrics": metrics, "bucket_metrics": bucket_metrics(rows), "rows": rows}


def _summarize_rows(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    total = max(len(rows), 1)
    return {
        "cases": float(len(rows)),
        "avg_reward": sum(row["reward"] for row in rows) / total,
        "format_valid_rate": sum(row["format_valid"] for row in rows) / total,
        "time_conflict_rate": 1.0 - sum(row["timeline_ok"] for row in rows) / total,
        "budget_success_rate": sum(row["budget_ok"] for row in rows) / total,
        "hallucination_rate": 1.0 - sum(row["hallucination_ok"] for row in rows) / total,
    }


def bucket_metrics(rows: List[Dict[str, Any]], keys: Optional[List[str]] = None) -> Dict[str, Dict[str, float]]:
    """按 Benchmark bucket 聚合指标，默认输出预算、天数、场景和难度视角。"""

    keys = keys or ["budget", "days", "scenario", "difficulty"]
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        bucket = row.get("bucket", {})
        for key in keys:
            value = row.get("difficulty") if key == "difficulty" else bucket.get(key)
            if value is None:
                continue
            grouped.setdefault(f"{key}:{value}", []).append(row)
    return {name: _summarize_rows(group_rows) for name, group_rows in sorted(grouped.items())}


def bucket_report_markdown(bucketed: Dict[str, Dict[str, float]]) -> str:
    """将 bucket 指标渲染为 Markdown 表格，适合写入评估报告或面试展示。"""

    headers = [
        "bucket",
        "cases",
        "avg_reward",
        "hallucination_rate",
        "time_conflict_rate",
        "budget_success_rate",
        "format_valid_rate",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for bucket, metrics in bucketed.items():
        lines.append(
            "| "
            + " | ".join([
                bucket,
                str(int(metrics.get("cases", 0))),
                f"{metrics.get('avg_reward', 0):.2f}",
                f"{metrics.get('hallucination_rate', 0):.2%}",
                f"{metrics.get('time_conflict_rate', 0):.2%}",
                f"{metrics.get('budget_success_rate', 0):.2%}",
                f"{metrics.get('format_valid_rate', 0):.2%}",
            ])
            + " |"
        )
    return "\n".join(lines)


def evolution_matrix(stage_results: Dict[str, Dict[str, float]]) -> str:
    headers = [
        "stage",
        "avg_reward",
        "hallucination_rate",
        "time_conflict_rate",
        "budget_success_rate",
        "format_valid_rate",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for stage, metrics in stage_results.items():
        lines.append(
            "| "
            + " | ".join([
                stage,
                f"{metrics.get('avg_reward', 0):.2f}",
                f"{metrics.get('hallucination_rate', 0):.2%}",
                f"{metrics.get('time_conflict_rate', 0):.2%}",
                f"{metrics.get('budget_success_rate', 0):.2%}",
                f"{metrics.get('format_valid_rate', 0):.2%}",
            ])
            + " |"
        )
    return "\n".join(lines)


def sample_valid_plan() -> str:
    return json.dumps({
        "city": "成都",
        "days": [
            {"day": 1, "items": [
                {"start": "09:00", "end": "10:30", "place": "武侯祠", "cost": 50},
                {"start": "10:45", "end": "12:00", "place": "锦里", "cost": 40},
                {"start": "14:00", "end": "16:00", "place": "人民公园", "cost": 20},
            ]},
            {"day": 2, "items": [
                {"start": "09:00", "end": "11:00", "place": "宽窄巷子", "cost": 80},
                {"start": "13:00", "end": "15:00", "place": "杜甫草堂", "cost": 60},
            ]},
        ],
        "total_cost": 250,
    }, ensure_ascii=False)


def sample_bad_plan() -> str:
    return json.dumps({
        "city": "成都",
        "days": [
            {"day": 1, "items": [
                {"start": "09:00", "end": "11:00", "place": "火星古城", "cost": 900},
                {"start": "10:30", "end": "12:00", "place": "熊猫基地", "cost": 900},
            ]},
        ],
        "total_cost": 1800,
    }, ensure_ascii=False)


def run_stage6_demo(train: bool = False, model_name: str = "Qwen/Qwen2.5-7B-Instruct") -> None:
    """阶段六演示入口。"""

    reward_engine = TravelRewardEngine()
    constraints = TravelConstraints("成都", 3, 1500, list(TravelRewardEngine.PLACE_COORDS.keys()))

    print("\n" + "=" * 60)
    print("  阶段六: GRPO 奖励与评估闭环")
    print("=" * 60)

    for name, text in [("valid_plan", sample_valid_plan()), ("bad_plan", sample_bad_plan())]:
        result = reward_engine.score(text, constraints)
        print(f"\n[{name}] reward={result.score:.2f}")
        print(json.dumps(result.details, ensure_ascii=False, indent=2))

    offline_outputs = [
        (BENCHMARK[0], sample_valid_plan()),
        (BENCHMARK[1], sample_bad_plan()),
        (BENCHMARK[2], "这是一份自然语言行程，不是 JSON。"),
    ]
    stage6_metrics = evaluate_outputs(offline_outputs, reward_engine)["metrics"]
    print("\n-- 六阶段进化矩阵示例 --")
    print(evolution_matrix({
        "阶段一-Prompt": {
            "avg_reward": -31.0,
            "hallucination_rate": 0.40,
            "time_conflict_rate": 0.55,
            "budget_success_rate": 0.35,
            "format_valid_rate": 0.62,
        },
        "阶段六-GRPO": stage6_metrics,
    }))

    if not train:
        print("\n提示: 传入 --stage6-train 才会加载模型并执行 GRPO train_step。")
        return

    cfg = GRPOConfig(model_name=model_name, group_size=4)
    trainer = GRPOTrainer(cfg, reward_engine, constraints)
    prompt = (
        "你是旅游规划智能体。必须只输出合法JSON。"
        "任务：3天、预算1500元去成都。字段包含city/days/day/items/start/end/place/cost/total_cost。"
    )
    stats = trainer.train_step(prompt)
    print("\n-- GRPO train_step --")
    print(json.dumps({k: v for k, v in stats.items() if k != "samples"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_stage6_demo(train=False)
