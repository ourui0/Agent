"""
Agent 阶段模块的轻量包入口。

这里刻意使用懒加载，避免 `import agents` 时一次性导入 LangGraph、FAISS、
torch/transformers 等可选重依赖。外部仍可使用：

    from agents import TravelRewardEngine
    from agents import build_graph

真正的阶段模块会在符号首次访问时才导入。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict


_EXPORTS: Dict[str, str] = {
    # 阶段一
    "ReActAgent": "agents.stage1_react",
    "PlanAndSolveAgent": "agents.stage1_plan_solve",
    "ReflectionAgent": "agents.stage1_reflection",
    # 阶段二
    "TravelState": "agents.stage2_state",
    "create_initial_state": "agents.stage2_state",
    "build_graph": "agents.stage2_graph",
    "negotiation_node": "agents.stage2_multi_agent",
    # 阶段三
    "tool": "agents.stage3_framework",
    "BaseAgent": "agents.stage3_framework",
    "EventBus": "agents.stage3_framework",
    "Orchestrator": "agents.stage3_framework",
    "Middleware": "agents.stage3_framework",
    "MiddlewarePipeline": "agents.stage3_framework",
    "TokenCounterMiddleware": "agents.stage3_framework",
    "SafetyFilterMiddleware": "agents.stage3_framework",
    "FunctionalAgent": "agents.stage3_framework",
    "build_orchestrator": "agents.stage3_travel",
    "run_travel_plan": "agents.stage3_travel",
    # 阶段四
    "TravelMemoryManager": "agents.stage4_memory",
    "LocalMemoryManager": "agents.stage4_memory",
    "Embedder": "agents.stage4_memory",
    "HybridRetriever": "agents.stage4_rag",
    "LightweightReranker": "agents.stage4_rag",
    "TravelRAG": "agents.stage4_rag",
    "VectorStore": "agents.stage4_rag",
    "TravelDocumentLoader": "agents.stage4_rag",
    "CoreferenceResolver": "agents.stage4_compressor",
    "ContextCompressor": "agents.stage4_compressor",
    "ContextPipeline": "agents.stage4_pipeline",
    # 阶段五
    "RealAPITransport": "agents.stage5_mcp",
    "JSONRPCRequest": "agents.stage5_mcp",
    "JSONRPCResponse": "agents.stage5_mcp",
    "MCPTransport": "agents.stage5_mcp",
    "StdioTransport": "agents.stage5_mcp",
    "HTTPTransport": "agents.stage5_mcp",
    "MockTransport": "agents.stage5_mcp",
    "MCPClientBridge": "agents.stage5_mcp",
    "MCPToolAdapter": "agents.stage5_mcp",
    "NegotiationIntent": "agents.stage5_a2a",
    "NegotiationState": "agents.stage5_a2a",
    "A2AMessage": "agents.stage5_a2a",
    "A2ASecurityMiddleware": "agents.stage5_a2a",
    "NegotiationFSM": "agents.stage5_a2a",
    "ANPRouteEntry": "agents.stage5_a2a",
    "AgentNetworkRouter": "agents.stage5_a2a",
    "A2ASessionManager": "agents.stage5_a2a",
    "demo_stage5": "agents.stage5_a2a",
    # 阶段六
    "TravelConstraints": "agents.stage6_grpo",
    "RewardResult": "agents.stage6_grpo",
    "TravelRewardEngine": "agents.stage6_grpo",
    "GRPOConfig": "agents.stage6_grpo",
    "GRPOTrainer": "agents.stage6_grpo",
    "BENCHMARK": "agents.stage6_grpo",
    "TravelEvaluator": "agents.stage6_grpo",
    "evaluate_outputs": "agents.stage6_grpo",
    "bucket_metrics": "agents.stage6_grpo",
    "bucket_report_markdown": "agents.stage6_grpo",
    "evolution_matrix": "agents.stage6_grpo",
    "run_stage6_demo": "agents.stage6_grpo",
}

_SUBMODULES = {
    "stage1_react",
    "stage1_plan_solve",
    "stage1_reflection",
    "stage2_state",
    "stage2_graph",
    "stage2_multi_agent",
    "stage3_framework",
    "stage3_travel",
    "stage4_memory",
    "stage4_rag",
    "stage4_compressor",
    "stage4_pipeline",
    "stage5_mcp",
    "stage5_a2a",
    "stage6_grpo",
}

__all__ = sorted([*_EXPORTS.keys(), *_SUBMODULES])


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        module = import_module(_EXPORTS[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _SUBMODULES:
        module = import_module(f"agents.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module 'agents' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *__all__])
