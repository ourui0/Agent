"""
阶段四：上下文压缩与指代消解管道

- 指代消解: 用 LLM 将 "它" / "那里" / "那个" 消解为明确实体
- 摘要压缩: 当短期记忆超 10 轮时，压缩 1-7 轮为背景摘要
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 指代消解器
# ═══════════════════════════════════════════════════════════════

COREF_RESOLVE_PROMPT = """你是指代消解专家。将用户输入中的模糊代词替换为明确的实体。

## 对话上下文
{context}

## 用户最新输入
{user_input}

## 任务
把用户输入中的模糊指代（它、那里、那个、这个、这里、他、她）替换为上下文中对应的明确实体。

## 格式
只返回消解后的句子，不要任何解释。

## 示例
上下文: "推荐了成都丽思卡尔顿酒店"
输入: "帮我把价格改成1000"
输出: "帮我把成都丽思卡尔顿酒店的价格改成1000"

上下文: "建议去故宫"
输入: "那里的门票多少钱"
输出: "故宫的门票多少钱"
"""


class CoreferenceResolver:
    """
    指代消解器：用 LLM 将模糊代词替换为明确实体。

    用法:
        resolver = CoreferenceResolver()
        resolved = await resolver.resolve("那里的门票多少钱", context=["建议去故宫"])
        # → "故宫的门票多少钱"
    """

    def __init__(self):
        self._cache: Dict[str, str] = {}
        self._cache_limit = 500

    async def resolve(
        self,
        user_input: str,
        context: List[str],
    ) -> str:
        """
        消解用户输入中的模糊指代。
        context: 最近的对话上下文 (entity 列表或完整的句子列表)
        """
        # 快速检查：是否有明显的指代词
        pronouns = re.findall(r'它|那里|那个|这个|这里|他|她|那儿|那儿|那边|这边', user_input)
        if not pronouns:
            return user_input

        # 缓存检查
        cache_key = f"{user_input}|{'|'.join(context[-3:])}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            from common.llm_client import LLMClient
            llm = LLMClient.get()

            context_text = "\n".join(f"- {c}" for c in context[-5:])
            prompt = COREF_RESOLVE_PROMPT.format(
                context=context_text,
                user_input=user_input,
            )

            resolved = llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
            ).strip()

            # 清理 LLM 输出 (去掉引号/解释)
            resolved = resolved.strip('"\'')

            logger.info(f"🔄 指代消解: '{user_input[:50]}' → '{resolved[:50]}'")

            # 缓存
            if len(self._cache) < self._cache_limit:
                self._cache[cache_key] = resolved

            return resolved

        except Exception as e:
            logger.warning(f"指代消解失败: {e}，返回原始输入")
            return user_input

    async def resolve_fast(self, user_input: str, recent_entities: List[str]) -> str:
        """
        快速消解 (不调 LLM)：仅当对话中有明确 entity 时进行简单替换。
        用于低延迟场景。
        """
        pronouns = re.findall(r'它|那里|那个|这个|这里|他|她|那儿|那边|这边', user_input)
        if not pronouns or not recent_entities:
            return user_input

        # 简单策略：用最近的 entity 替换第一个指代词
        result = user_input
        for pronoun in pronouns[:2]:  # 最多替换 2 个
            if recent_entities and pronoun in result:
                entity = recent_entities[-1]  # 取最近的
                result = result.replace(pronoun, entity, 1)

        if result != user_input:
            logger.info(f"⚡ 快速消解: '{user_input[:40]}' → '{result[:40]}'")

        return result


# ═══════════════════════════════════════════════════════════════
# 上下文压缩器
# ═══════════════════════════════════════════════════════════════

COMPRESS_PROMPT = """你是对话压缩专家。将以下多轮对话压缩为一段精炼的背景摘要。

## 原始对话
{dialogues}

## 任务
提取关键信息：目的地、预算、人数、天数、偏好、特殊要求、已确认的行程安排。
压缩为 3-5 句话的背景摘要，保留所有关键决策信息。

## 格式
只返回摘要文本，不要任何标签或解释。
"""


class ContextCompressor:
    """
    上下文压缩器。

    用法:
        compressor = ContextCompressor(compress_threshold=10, keep_recent=3)

        # 添加消息
        await compressor.add_message(session_id, {"role":"user","content":"..."})

        # 当达到阈值时自动压缩
        summary = await compressor.maybe_compress(session_id)
    """

    def __init__(
        self,
        compress_threshold: int = 10,
        keep_recent: int = 3,
    ):
        self.compress_threshold = compress_threshold  # 多少轮后触发压缩
        self.keep_recent = keep_recent                # 保留最近 N 轮不压缩

        # 内存缓冲：{session_id: [(timestamp, {role, content}), ...]}
        self._buffer: Dict[str, List[Dict]] = {}

        # 压缩后的摘要
        self._summaries: Dict[str, str] = {}

        # 压缩任务状态
        self._compressing: Dict[str, bool] = {}

    async def add_message(self, session_id: str, message: Dict[str, str]):
        """添加一条消息到上下文缓冲。"""
        if session_id not in self._buffer:
            self._buffer[session_id] = []
        self._buffer[session_id].append(message)

    async def maybe_compress(self, session_id: str) -> Optional[str]:
        """
        检查是否需要压缩。如果缓冲超阈值，异步触发压缩任务。
        返回压缩后的摘要（如果有），或 None。
        """
        buffer = self._buffer.get(session_id, [])
        if len(buffer) < self.compress_threshold:
            return None

        # 防止重复压缩
        if self._compressing.get(session_id):
            return None

        self._compressing[session_id] = True
        try:
            return await self._compress(session_id)
        finally:
            self._compressing[session_id] = False

    async def _compress(self, session_id: str) -> str:
        """执行压缩：将前 N 轮对话压缩为摘要，保留最近 K 轮。"""
        buffer = self._buffer.get(session_id, [])
        if not buffer:
            return ""

        # 分割：前 threshold-keep_recent 轮 → 压缩 | 最近 keep_recent 轮 → 保留
        compress_part = buffer[:max(0, len(buffer) - self.keep_recent)]
        keep_part = buffer[-self.keep_recent:]

        if len(compress_part) < 3:
            return self._summaries.get(session_id, "")

        # 构建对话文本
        dialogue_text = "\n".join(
            f"{m['role']}: {m['content'][:150]}" for m in compress_part
        )

        try:
            from common.llm_client import LLMClient
            llm = LLMClient.get()

            prompt = COMPRESS_PROMPT.format(dialogues=dialogue_text)
            summary = llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
            ).strip()

            # 存储摘要 + 清理缓冲
            self._summaries[session_id] = summary
            self._buffer[session_id] = keep_part

            logger.info(
                f"📦 压缩完成: {len(compress_part)} 轮 → "
                f"{len(summary)} 字符摘要 + 保留 {len(keep_part)} 轮"
            )
            return summary

        except Exception as e:
            logger.error(f"压缩失败: {e}")
            return self._summaries.get(session_id, "")

    def get_context(
        self,
        session_id: str,
        resolved_query: str,
    ) -> Dict[str, Any]:
        """
        获取当前会话的压缩后上下文。

        返回: {
            "summary": "背景摘要",
            "recent_messages": [{...}, ...],
            "compressed_rounds": 被压缩的轮数,
        }
        """
        summary = self._summaries.get(session_id, "")
        recent = self._buffer.get(session_id, [])
        compressed_rounds = 0

        # 如果有压缩摘要，额外的 old rounds 已被清理
        if summary:
            compressed_rounds = max(0, self.compress_threshold - self.keep_recent)

        return {
            "summary": summary,
            "recent_messages": recent[-self.keep_recent:] if recent else [],
            "compressed_rounds": compressed_rounds,
            "resolved_query": resolved_query,
        }

    async def clear(self, session_id: str):
        """清除指定会话的所有上下文。"""
        self._buffer.pop(session_id, None)
        self._summaries.pop(session_id, None)
        self._compressing.pop(session_id, None)
