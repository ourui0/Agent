"""
旅游规划帝 · 统一入口

用法:
  python main.py                              # 默认: 阶段二 LangGraph CLI
  python main.py --stage1                     # 阶段一: 手写三大范式
  python main.py --stage1 --mode reflection   # 阶段一: 仅 Reflection
  python main.py --mock                       # Mock 模式 (无需 API Key)
  python main.py --serve                      # 启动 FastAPI 服务
  python main.py --query "..."                # 自定义查询
"""

import sys, os, argparse, logging

# 确保项目根目录在 sys.path
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from common import ToolRegistry
from common.tools import TOOL_FUNCTIONS
from common.llm_client import LLMClient
import asyncio

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("main")


def build_registry() -> ToolRegistry:
    r = ToolRegistry()
    for func, name, desc in TOOL_FUNCTIONS:
        r.register(func, name=name, description=desc)
    return r


# ═══════════════════════════════════════════════════════
# 阶段一
# ═══════════════════════════════════════════════════════

def run_stage1(query: str, mode: str, mock: bool):
    from agents.stage1_react import ReActAgent
    from agents.stage1_plan_solve import PlanAndSolveAgent
    from agents.stage1_reflection import ReflectionAgent

    if mock:
        LLMClient.reset_instance()
    llm = LLMClient.get()
    llm.reset_mock()
    registry = build_registry()

    print(f"\n{'='*60}\n  🧪 阶段一: {mode}\n{'='*60}\n  📝 {query}\n")
    print(f"🔧 工具: {', '.join(registry.tool_names)}")
    if llm.mock_mode:
        print("⚠️  Mock 模式")

    if mode in ("react", "all"):
        print("\n--- 🤖 ReAct ---")
        result = ReActAgent(registry, max_iterations=8).run(query)
        print(f"\n✅ {result}")

    if mode in ("plan-solve", "all"):
        llm.reset_mock()
        print("\n--- 📋 Plan-and-Solve ---")
        result = PlanAndSolveAgent(registry).run(query)
        print(f"\n✅ {result}")

    if mode in ("reflection", "all"):
        llm.reset_mock()
        print("\n--- 🔍 Reflection ---")
        result = ReflectionAgent(registry).run(query)
        print(f"\n✅ {result}")

    print(f"\n🎉 阶段一完成!\n")



# ═══════════════════════════════════════════════════════════
# 阶段三
# ═══════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════
# 阶段四
# ═══════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════
# 阶段五
# ═══════════════════════════════════════════════════════════

def run_stage5():
    """MCP + A2A + ANP 协议栈演示"""
    from agents.stage5_a2a import demo_stage5
    asyncio.run(demo_stage5())

def run_stage4(query: str):
    """阶段四: 双轨记忆 + RAG检索 + 上下文压缩"""
    from agents.stage4_pipeline import ContextPipeline

    print(f"\n{'='*60}\n  🧠 阶段四: 记忆与RAG\n{'='*60}\n  📝 {query}\n")

    async def _run():
        pipeline = ContextPipeline()
        await pipeline.init()

        session_id = "stage4-demo"
        state = {"user_query": query, "session_id": session_id}
        state = await pipeline.enhance_state(state, session_id)

        # 展示增强结果
        if state.get("resolved_query"):
            print(f"  🔄 指代消解: {state['original_query'][:50]} → {state['resolved_query'][:50]}")
        else:
            print(f"  📝 查询: {query[:50]}")

        if state.get("rag_context"):
            print(f"  📚 RAG 知识库匹配:")
            for line in state["rag_context"].split("\n")[:3]:
                print(f"     {line[:100]}")

        if state.get("long_term_preferences"):
            print(f"  💾 长期偏好: {[p['preference'] for p in state['long_term_preferences']]}")

        # 自动偏好检测
        detected = pipeline.memory.detect_preferences(query)
        if detected:
            print(f"  🔍 检测到偏好: {[d[0] for d in detected]}")

        await pipeline.close()
        print(f"\n✅ 阶段四演示完成!\n")

    asyncio.run(_run())

def run_stage3(query: str, max_revisions: int):
    """自研框架: @tool + BaseAgent + EventBus + Middleware + Orchestrator"""
    from agents.stage3_travel import run_travel_plan

    print(f"\n{'='*60}\n  🔧 阶段三: 自研框架 V3.0\n{'='*60}\n  📝 {query}\n")

    state = asyncio.run(run_travel_plan(query, max_revisions))

    print(f"\n{'─'*60}")
    print(f"  📍 {state.get('city','?')} | 👥{state.get('people','?')}人 📅{state.get('days','?')}天")
    print(f"  💰 预算¥{state.get('budget','?')} | 💸 总费¥{state.get('total_cost',0):.0f} | {state.get('budget_status','?')}")
    print(f"  🔄 回溯{state.get('_backtrack_count',0)}次")
    for day in state.get("itinerary", []):
        print(f"  Day{day.get('day')}: {' → '.join(day.get('attractions',[]))}")
        if day.get("notes"): print(f"       💡 {day.get('notes')}")
    for h in state.get("hotels", []):
        print(f"  🏨 {h.get('name')} ¥{h.get('price_per_night')}/晚 {h.get('rating')}分 | {h.get('reason','')}")
    print(f"\n✅ 阶段三完成! (自研框架)\n")

# ═══════════════════════════════════════════════════════
# 阶段二
# ═══════════════════════════════════════════════════════

def run_stage2(query: str, max_revisions: int):
    from agents.stage2_state import create_initial_state
    from agents.stage2_graph import build_graph

    graph = build_graph()
    config = {"configurable": {"thread_id": "cli"}}
    init = create_initial_state(query, max_revisions)

    print(f"\n{'='*60}\n  🧳 阶段二: LangGraph 多智能体\n{'='*60}\n  📝 {query}\n")

    for chunk in graph.stream(init, config):
        for node, update in chunk.items():
            if node.startswith("__"): continue
            logs = update.get("logs", [])
            print(f"  [{node}] {logs[-1] if logs else ''}")

    state = graph.get_state(config)
    if state and state.values:
        v = state.values
        print(f"\n{'─'*60}")
        print(f"  📍 {v.get('city')} | 👥{v.get('people')}人 📅{v.get('days')}天")
        print(f"  💰 预算¥{v.get('budget')} | 💸 总费¥{v.get('total_cost',0):.0f} | {v.get('budget_status')}")
        print(f"  🔄 修订{v.get('revision_count',0)}次")
        for day in v.get("itinerary", []):
            print(f"  Day{day.get('day')}: {' → '.join(day.get('attractions',[]))}")
            if day.get("notes"): print(f"       💡 {day.get('notes')}")
        for h in v.get("hotels", []):
            print(f"  🏨 {h.get('name')} ¥{h.get('price_per_night')}/晚 {h.get('rating')}分 | {h.get('reason','')}")
    print(f"\n✅ 阶段二完成!\n")


# ═══════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════

def run_server(host: str, port: int):
    import uvicorn
    from api.server import create_app
    app = create_app()
    print(f"\n🚀 http://{host}:{port}\n📖 http://{host}:{port}/docs\n")
    uvicorn.run(app, host=host, port=port, log_level="info")


# ═══════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="旅游规划帝")
    p.add_argument("--stage1", action="store_true", help="阶段一: 手写三大范式")
    p.add_argument("--stage2", action="store_true", help="阶段二: LangGraph (默认)")
    p.add_argument("--stage3", action="store_true", help="阶段三: 自研框架")
    p.add_argument("--stage4", action="store_true", help="阶段四: 记忆与RAG")
    p.add_argument("--stage5", action="store_true", help="阶段五: MCP+A2A协议")
    p.add_argument("--chat", action="store_true", help="交互对话模式")
    p.add_argument("--mode", choices=["react","plan-solve","reflection","all"], default="all", help="阶段一模式")
    p.add_argument("--mock", action="store_true", help="Mock 模式")
    p.add_argument("--query", default="2个人去北京玩3天，预算3000元", help="旅行查询")
    p.add_argument("--max-revisions", type=int, default=3, help="最大修订次数")
    p.add_argument("--serve", action="store_true", help="启动 API 服务")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args()

    if args.chat:
        from chat import run_chat
        asyncio.run(run_chat(mock=args.mock))
        return

    if args.mock:
        LLMClient.reset_instance()

    if args.serve:
        run_server(args.host, args.port)
    elif args.stage5:
        run_stage5()
    elif args.stage4:
        run_stage4(args.query)
    elif args.stage3:
        run_stage3(args.query, args.max_revisions)
    elif args.stage1:
        run_stage1(args.query, args.mode, args.mock)
    else:
        run_stage2(args.query, args.max_revisions)


if __name__ == "__main__":
    main()
