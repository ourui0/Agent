import asyncio
import json

from agents.stage4_compressor import ContextCompressor, CoreferenceResolver
from agents.stage4_memory import LocalMemoryManager
from agents.stage4_pipeline import ContextPipeline
from agents.stage4_rag import HybridRetriever, TravelDocumentLoader, TravelRAG
from agents.stage5_a2a import (
    A2AMessage,
    A2ASecurityMiddleware,
    AgentNetworkRouter,
    NegotiationFSM,
    NegotiationIntent,
    NegotiationState,
)
from agents.stage5_mcp import JSONRPCRequest, MCPClientBridge, MockTransport


def test_stage4_local_memory_read_write_and_preferences():
    async def scenario():
        mem = LocalMemoryManager(short_term_window=2)
        await mem.init()
        await mem.add_short_term("s1", {"role": "user", "content": "我不吃辣"})
        await mem.add_short_term("s1", {"role": "assistant", "content": "记住了"})
        await mem.add_short_term("s1", {"role": "user", "content": "去成都"})
        recent = await mem.get_short_term("s1")
        assert len(recent) == 2
        assert recent[-1]["content"] == "去成都"

        detected = mem.detect_preferences("我不吃辣，预算有限")
        assert ("不吃辣", 0.7) in detected
        await mem.add_long_term_preference("s1", "不吃辣", 0.9)
        prefs = await mem.get_long_term_preferences("s1", "成都清淡餐厅")
        assert isinstance(prefs, list)

        prompt = await mem.inject_memory_to_prompt("s1", "成都清淡餐厅", "BASE")
        assert "BASE" in prompt
        assert "近期对话历史" in prompt
        assert "去成都" in prompt

    asyncio.run(scenario())


def test_stage4_document_loader_and_rag_search(tmp_path):
    md = tmp_path / "chengdu.md"
    md.write_text("# 成都\n\n成都火锅和熊猫基地很有名，但不吃辣可以选择茶馆和人民公园。", encoding="utf-8")
    txt = tmp_path / "sanya.txt"
    txt.write_text("三亚海滩适合上午和傍晚游玩，亚龙湾水质较好。", encoding="utf-8")

    docs = TravelDocumentLoader.load_directory(str(tmp_path))
    assert len(docs) >= 2

    rag = TravelRAG(index_dir=str(tmp_path / "idx"))
    rag.load_knowledge(docs)
    results = rag.search("成都不吃辣", top_k=5, rerank_top_k=2)
    assert results
    assert "成都" in rag.format_context(results)


def test_stage4_context_pipeline_with_local_components(tmp_path):
    async def scenario():
        memory = LocalMemoryManager()
        await memory.init()
        rag = TravelRAG(index_dir=str(tmp_path / "idx"))
        rag.load_knowledge(TravelDocumentLoader.from_texts([
            "成都不吃辣可以去人民公园喝茶，也可以选择清淡川菜。",
            "北京故宫需要提前预约，适合上午参观。",
        ], source="test"))
        pipeline = ContextPipeline(memory=memory, rag=rag)
        await pipeline.init()
        state = await pipeline.enhance_state({"user_query": "我不吃辣，想去成都"}, "s1")
        assert state["session_id"] == "s1"
        assert "rag_context" in state
        await pipeline.record_interaction("s1", "我不吃辣", "已记录")
        assert len(await memory.get_short_term("s1")) == 2

    asyncio.run(scenario())


def test_stage4_compressor_fast_resolve_and_summary(monkeypatch):
    async def scenario():
        resolver = CoreferenceResolver()
        assert await resolver.resolve_fast("那里的门票多少钱", ["故宫"]) == "故宫的门票多少钱"
        compressor = ContextCompressor(compress_threshold=4, keep_recent=1)
        for i in range(4):
            await compressor.add_message("s1", {"role": "user", "content": f"第{i}轮 成都 预算"})
        summary = await compressor.maybe_compress("s1")
        assert isinstance(summary, str)
        ctx = compressor.get_context("s1", "成都")
        assert "recent_messages" in ctx

    asyncio.run(scenario())


def test_stage5_mcp_mock_jsonrpc_tools_flow():
    async def scenario():
        req = JSONRPCRequest(method="tools/list")
        assert req.jsonrpc == "2.0"
        assert req.id

        bridge = MCPClientBridge(MockTransport("test"))
        await bridge.connect()
        await bridge.initialize()
        tools = await bridge.list_tools()
        assert any(t["name"] == "amap_search_poi" for t in tools)
        result = await bridge.call_tool("amap_search_poi", {"keywords": "火锅", "city": "成都"})
        assert "content" in result
        assert "成都" in result["content"][0]["text"]
        await bridge.close()

    asyncio.run(scenario())


def test_stage5_a2a_fsm_router_and_security():
    fsm = NegotiationFSM("cid", max_rounds=3)
    msg = fsm.propose({"price": 1000, "budget": 800})
    assert fsm.state == NegotiationState.PROPOSING
    counter = fsm.counter({"price": 850})
    assert counter.intent == NegotiationIntent.COUNTER
    accepted = fsm.accept({"final_price": 800})
    assert accepted.intent == NegotiationIntent.ACCEPT

    router = AgentNetworkRouter()
    router.register("anp://ctrip.com/hotel-agent", transport="mock")
    assert router.resolve("anp://ctrip.com/hotel-agent") is not None
    assert router.resolve("anp://unknown.com/agent") is None

    security = A2ASecurityMiddleware()
    unsafe_domain = A2AMessage(
        sender_uri="anp://travel-agent.local/planner",
        receiver_uri="anp://evil.com/hotel-agent",
        intent=NegotiationIntent.PROPOSE,
        payload={"price": 100, "market_price": 100},
    )
    assert security.validate(unsafe_domain)[0] is False

    unsafe_price = A2AMessage(
        sender_uri="anp://travel-agent.local/planner",
        receiver_uri="anp://ctrip.com/hotel-agent",
        intent=NegotiationIntent.PROPOSE,
        payload={"price": 1000, "market_price": 100},
    )
    assert security.validate(unsafe_price)[0] is False
