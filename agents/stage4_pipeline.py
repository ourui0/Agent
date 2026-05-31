"""
阶段四：上下文工程集成管道

将 Memory + RAG + Compressor 注入到自研框架的 Orchestrator 中。
每个节点执行前自动增强 State 的上下文。
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

from .stage4_memory import TravelMemoryManager
from .stage4_rag import TravelRAG
from .stage4_compressor import CoreferenceResolver, ContextCompressor

logger = logging.getLogger(__name__)


class ContextPipeline:
    """
    上下文工程管道 — 在 Agent 执行前增强 State。

    流程:
      用户输入
        → 指代消解 (CoreferenceResolver)
        → RAG 检索 (TravelRAG)
        → 记忆注入 (MemoryManager: 长期偏好 + 短期历史)
        → 增强后的 State → Agent 执行
        → 执行结果 → 写入短期记忆
        → 检查是否需要压缩 (ContextCompressor)
    """

    def __init__(
        self,
        memory: Optional[TravelMemoryManager] = None,
        rag: Optional[TravelRAG] = None,
        resolver: Optional[CoreferenceResolver] = None,
        compressor: Optional[ContextCompressor] = None,
    ):
        self.memory = memory or TravelMemoryManager()
        self.rag = rag or self._build_default_rag()
        self.resolver = resolver or CoreferenceResolver()
        self.compressor = compressor or ContextCompressor(
            compress_threshold=10,
            keep_recent=3,
        )

    @staticmethod
    def _build_default_rag() -> TravelRAG:
        rag = TravelRAG(alpha=0.3, index_dir="data/faiss_index")
        # 优先从磁盘加载 (秒级), 失败则重建索引
        if rag.load_from_disk():
            logger.info("📂 从磁盘恢复 RAG 索引")
        else:
            rag.load_knowledge(TravelRAG.default_knowledge())
            logger.info("🔨 重建 RAG 索引并保存")
        return rag

    async def init(self):
        """初始化所有组件连接。"""
        try:
            await self.memory.init()
        except Exception as e:
            logger.warning(f"Redis/FAISS ({e})")
            raise RuntimeError(
                "Redis/FAISS not available. Start Redis: redis-server"
            ) from e
        logger.info("✅ ContextPipeline 就绪")

    async def enhance_state(
        self,
        state: dict,
        session_id: Optional[str] = None,
    ) -> dict:
        """
        增强 State：指代消解 → RAG → 记忆注入。

        返回增强后的 state (新增字段不影响原有字段)。
        """
        session_id = session_id or state.get("session_id", str(uuid.uuid4())[:8])
        state["session_id"] = session_id

        user_query = state.get("user_query", "")

        # 1. 短期记忆上下文 (用于指代消解)
        recent = await self.memory.get_short_term(session_id)
        context_entities = [
            m.get("content", "") for m in recent[-5:]
            if m.get("role") in ("assistant", "system")
        ]

        # 2. 指代消解
        resolved_query = await self.resolver.resolve(user_query, context_entities)
        if resolved_query != user_query:
            state["resolved_query"] = resolved_query
            state["original_query"] = user_query
            logger.info(f"🔄 指代消解: '{user_query[:40]}' → '{resolved_query[:40]}'")
        else:
            resolved_query = user_query

        # 3. RAG 检索 (用消解后的查询)
        rag_results = self.rag.search(resolved_query, top_k=10, rerank_top_k=3)
        if rag_results:
            rag_context = self.rag.format_context(rag_results)
            state["rag_context"] = rag_context
            logger.info(f"📚 RAG 检索: {len(rag_results)} 条相关知识")

        # 4. 长期偏好注入
        prefs = await self.memory.get_long_term_preferences(session_id, resolved_query)
        if prefs:
            state["long_term_preferences"] = prefs

        # 5. 自动偏好检测
        detected = self.memory.detect_preferences(user_query)
        for tag, weight in detected:
            await self.memory.add_long_term_preference(session_id, tag, weight)

        # 6. 压缩检查
        summary = await self.compressor.maybe_compress(session_id)
        if summary:
            state["compressed_summary"] = summary

        return state

    async def record_interaction(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        state_update: Optional[dict] = None,
    ):
        """
        记录一轮交互：写入短期记忆 + 压缩器缓冲。
        """
        await self.memory.add_short_term(
            session_id,
            {"role": "user", "content": user_message},
        )
        await self.memory.add_short_term(
            session_id,
            {"role": "assistant", "content": assistant_message[:500]},
        )
        await self.compressor.add_message(
            session_id,
            {"role": "user", "content": user_message},
        )
        await self.compressor.add_message(
            session_id,
            {"role": "assistant", "content": assistant_message[:300]},
        )

    async def build_enhanced_prompt(
        self,
        base_prompt: str,
        state: dict,
    ) -> str:
        """
        构建增强后的 System Prompt (融合记忆 + RAG + 压缩摘要)。
        """
        parts = [base_prompt]

        # 压缩摘要
        summary = state.get("compressed_summary", "")
        if summary:
            parts.append(f"\n## 历史对话摘要\n{summary}")

        # 长期偏好
        prefs = state.get("long_term_preferences", [])
        if prefs:
            pref_lines = "\n".join(
                f"- {p['preference']}" for p in prefs[:3]
            )
            parts.append(f"\n## 用户偏好\n{pref_lines}")

        # RAG 上下文
        rag = state.get("rag_context", "")
        if rag:
            parts.append(f"\n## 相关知识库\n{rag}")

        # 消解后的查询提示
        resolved = state.get("resolved_query", "")
        if resolved and resolved != state.get("user_query", ""):
            parts.append(f"\n注意: 用户实际想问的是「{resolved}」")

        return "\n".join(parts)

    async def close(self):
        """关闭所有连接。"""
        await self.memory.close()


# ═══════════════════════════════════════════════════════════════
# 简化的阶段四演示入口
# ═══════════════════════════════════════════════════════════════

async def demo_stage4():
    """阶段四独立演示。"""
    pipeline = ContextPipeline()
    await pipeline.init()

    session_id = "demo-session"

    # 模拟多轮对话
    conversations = [
        "我想去成都旅游，3天时间，预算2000",
        "我不吃辣，有什么清淡的推荐？",
        "那里有什么好玩的景点？",  # ← 需要指代消解: "那里" → "成都"
        "帮我把住宿预算调低一点，我喜欢青年旅舍",
    ]

    for query in conversations:
        state = {"user_query": query, "session_id": session_id}
        state = await pipeline.enhance_state(state, session_id)

        print(f"\n{'='*50}")
        print(f"📝 原始: {query}")
        if state.get("resolved_query"):
            print(f"🔄 消解: {state['resolved_query']}")
        if state.get("rag_context"):
            print(f"📚 RAG: {state['rag_context'][:120]}...")
        if state.get("long_term_preferences"):
            print(f"💾 偏好: {[p['preference'] for p in state['long_term_preferences']]}")
        if state.get("compressed_summary"):
            print(f"📦 摘要: {state['compressed_summary'][:100]}...")

        # 记录交互
        await pipeline.record_interaction(
            session_id, query,
            f"好的，关于{query[:20]}的建议是...",
        )

    await pipeline.close()
