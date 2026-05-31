"""
阶段四：双轨制记忆管理器 (Dual-Track Memory Manager)

短期记忆: Redis 滑动窗口 (最近 N 轮)，LRU 淘汰
长期记忆: FAISS 向量检索用户偏好标签，注入 System Prompt
"""

import asyncio
import json
import logging
import hashlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import redis.asyncio as aioredis
import faiss
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 嵌入器 — 文本 → 向量 (TF-IDF + SVD → 128维)
# ═══════════════════════════════════════════════════════════════

class Embedder:
    """TF-IDF + SVD 降维 → 固定维度向量。"""

    def __init__(self, dim: int = 128):
        self.dim = dim
        self._tfidf: Optional[TfidfVectorizer] = None
        self._svd: Optional[TruncatedSVD] = None
        self._ready = False

    def fit(self, texts: List[str]):
        """用语料训练 TF-IDF 和 SVD。"""
        if len(texts) < 2:
            texts = texts + ["placeholder"]
        self._tfidf = TfidfVectorizer(max_features=2000, analyzer="char_wb", ngram_range=(1, 2))
        tfidf_matrix = self._tfidf.fit_transform(texts)

        n_components = min(self.dim, tfidf_matrix.shape[1] - 1, tfidf_matrix.shape[0] - 1)
        if n_components > 1:
            self._svd = TruncatedSVD(n_components=n_components, random_state=42)
            self._svd.fit(tfidf_matrix)

        self._ready = True
        logger.info(f"Embedder 就绪: {len(self._tfidf.vocabulary_)} 特征 → {self.dim}维")

    def encode(self, text: str) -> np.ndarray:
        """编码为固定维度向量。"""
        if not self._ready:
            self.fit([text, "旅行 旅游 酒店 景点 天气"])
        vec = self._tfidf.transform([text])
        if self._svd:
            vec = self._svd.transform(vec)
        v = vec.toarray()[0] if hasattr(vec, "toarray") else vec[0]
        if len(v) < self.dim:
            v = np.pad(v, (0, self.dim - len(v)))
        return v[:self.dim].astype(np.float32)

    def save(self, path: str):
        """保存 Embedder 状态（TF-IDF + SVD），用于恢复一致的向量空间。"""
        import pickle
        state = {"tfidf": self._tfidf, "svd": self._svd, "dim": self.dim}
        with open(f"{path}.emb", "wb") as f:
            pickle.dump(state, f)

    def load(self, path: str) -> bool:
        """加载 Embedder 状态，恢复一致的向量空间。"""
        import pickle, os
        emb_file = f"{path}.emb"
        if not os.path.exists(emb_file):
            return False
        try:
            with open(emb_file, "rb") as f:
                state = pickle.load(f)
            self._tfidf = state["tfidf"]
            self._svd = state["svd"]
            self.dim = state["dim"]
            self._ready = True
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════
# 双轨制记忆管理器
# ═══════════════════════════════════════════════════════════════

class TravelMemoryManager:
    """
    双轨记忆：短期 (Redis) + 长期 (FAISS)。

    用法:
        mem = TravelMemoryManager(redis_url="redis://localhost")
        await mem.init()

        await mem.add_short_term(session_id, {"role":"user","content":"..."})
        await mem.add_long_term_preference(session_id, "不吃辣", weight=0.9)

        recent = await mem.get_short_term(session_id)
        prefs  = await mem.get_long_term_preferences(session_id, "想去成都")
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        short_term_window: int = 10,
        long_term_top_k: int = 5,
        embed_dim: int = 128,
    ):
        self.redis_url = redis_url
        self.short_term_window = short_term_window
        self.long_term_top_k = long_term_top_k

        self.embedder = Embedder(dim=embed_dim)

        # 延迟初始化
        self._redis: Optional[aioredis.Redis] = None
        self._faiss_index: Optional[faiss.IndexFlatIP] = None

        # FAISS 元数据
        self._pref_texts: List[str] = []
        self._pref_weights: List[float] = []
        self._pref_sessions: List[str] = []

    async def init(self):
        """初始化连接。"""
        self._redis = aioredis.from_url(
            self.redis_url,
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=True,
        )
        await self._redis.ping()
        logger.info("✅ Redis 连接成功")

        self._faiss_index = faiss.IndexFlatIP(self.embedder.dim)
        logger.info(f"✅ FAISS 索引就绪 (dim={self.embedder.dim})")

        self.embedder.fit(["旅行 旅游 酒店 景点 天气 预算 行程 攻略 餐饮 交通"])

    # ─── 短期记忆 (Redis 滑动窗口) ───

    @staticmethod
    def _short_key(session_id: str) -> str:
        return f"travel:short:{session_id}"

    async def add_short_term(self, session_id: str, message: Dict[str, str]):
        """追加一条消息，自动 LRU 裁剪 + TTL。"""
        key = self._short_key(session_id)
        data = json.dumps(message, ensure_ascii=False)

        async with self._redis.pipeline() as pipe:
            await pipe.rpush(key, data)
            await pipe.ltrim(key, -self.short_term_window, -1)
            await pipe.expire(key, 3600)
            await pipe.execute()

    async def get_short_term(self, session_id: str) -> List[Dict[str, str]]:
        """获取最近 N 轮短期记忆。"""
        key = self._short_key(session_id)
        items = await self._redis.lrange(key, 0, -1)
        return [json.loads(item) for item in items]

    # ─── 长期记忆 (FAISS 向量检索) ───

    async def add_long_term_preference(
        self, session_id: str, preference_text: str, weight: float = 0.5,
    ):
        """存储用户偏好到 FAISS。"""
        vec = self.embedder.encode(preference_text).reshape(1, -1)
        faiss.normalize_L2(vec)

        idx = self._faiss_index.ntotal
        self._faiss_index.add(vec)
        self._pref_texts.append(preference_text)
        self._pref_weights.append(weight)
        self._pref_sessions.append(session_id)
        logger.info(f"💾 长期记忆 [{idx}]: {preference_text} (w={weight})")

    async def get_long_term_preferences(
        self, session_id: str, query_context: str = "",
    ) -> List[Dict[str, Any]]:
        """检索与当前查询最相关的长期偏好。"""
        if not query_context or self._faiss_index.ntotal == 0:
            return []

        query_vec = self.embedder.encode(query_context).reshape(1, -1)
        faiss.normalize_L2(query_vec)

        k = min(self.long_term_top_k, self._faiss_index.ntotal)
        distances, indices = self._faiss_index.search(query_vec, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0 and idx < len(self._pref_texts) and float(dist) > 0.2:
                results.append({
                    "preference": self._pref_texts[idx],
                    "weight": self._pref_weights[idx],
                    "score": round(float(dist), 3),
                })

        return results

    # ─── 偏好检测 ───

    PREFERENCE_PATTERNS = [
        ("不吃辣", ["不吃辣", "怕辣", "不能吃辣", "忌辣", "清淡"]),
        ("喜欢民宿", ["民宿", "客栈", "不想住酒店", "有特色"]),
        ("预算紧张", ["省钱", "穷游", "便宜", "经济实惠", "预算有限"]),
        ("腿脚不便", ["腿脚", "走路不便", "不能走远", "行动不便", "老人"]),
        ("喜欢海鲜", ["海鲜", "生蚝", "龙虾", "螃蟹", "刺身"]),
        ("高星酒店", ["五星", "5星", "豪华", "高档", "奢华"]),
        ("亲子游", ["带孩子", "亲子", "小孩", "宝宝", "儿童"]),
    ]

    def detect_preferences(self, text: str) -> List[Tuple[str, float]]:
        """从输入中检测偏好标签。"""
        detected = []
        for tag, keywords in self.PREFERENCE_PATTERNS:
            for kw in keywords:
                if kw in text:
                    detected.append((tag, 0.7))
                    break
        return detected

    # ─── 完整记忆注入 ───

    async def inject_memory_to_prompt(
        self, session_id: str, user_query: str, base_system_prompt: str,
    ) -> str:
        """将短期 + 长期记忆注入 System Prompt。"""
        parts = [base_system_prompt]

        prefs = await self.get_long_term_preferences(session_id, user_query)
        if prefs:
            pref_lines = "\n".join(
                f"- {p['preference']} (置信度: {p['score']:.0%})"
                for p in prefs[:3]
            )
            parts.append(f"\n## 用户长期偏好\n{pref_lines}")

        recent = await self.get_short_term(session_id)
        if recent:
            history_text = "\n".join(
                f"{m['role']}: {m['content'][:100]}" for m in recent[-6:]
            )
            parts.append(f"\n## 近期对话历史\n{history_text}")

        return "\n".join(parts)

    async def close(self):
        """关闭连接。"""
        if self._redis:
            await self._redis.close()


# ═══════════════════════════════════════════════════════════════
# 本地内存模式 (零依赖，无需 Redis)
# ═══════════════════════════════════════════════════════════════

class LocalMemoryManager:
    """
    零依赖本地记忆管理器。接口与 TravelMemoryManager 完全兼容。
    短期: dict + 滑动窗口  长期: FAISS (本地)
    """

    def __init__(self, short_term_window: int = 10, long_term_top_k: int = 5, embed_dim: int = 128):
        self.short_term_window = short_term_window
        self.long_term_top_k = long_term_top_k
        self.embedder = Embedder(dim=embed_dim)
        self._short: Dict[str, List[Dict]] = {}
        self._index = faiss.IndexFlatIP(embed_dim)
        self._texts: List[str] = []
        self._weights: List[float] = []
        self._sessions: List[str] = []

    async def init(self):
        self.embedder.fit(["旅行 旅游 酒店 景点 天气 预算 行程 攻略"])
        logger.info("✅ 本地内存模式就绪 (无需 Redis)")

    async def add_short_term(self, session_id: str, message: Dict[str, str]):
        if session_id not in self._short:
            self._short[session_id] = []
        self._short[session_id].append(message)
        if len(self._short[session_id]) > self.short_term_window:
            self._short[session_id] = self._short[session_id][-self.short_term_window:]

    async def get_short_term(self, session_id: str) -> List[Dict[str, str]]:
        return self._short.get(session_id, [])

    async def add_long_term_preference(self, session_id: str, text: str, weight: float = 0.5):
        vec = self.embedder.encode(text).reshape(1, -1)
        faiss.normalize_L2(vec)
        self._index.add(vec)
        self._texts.append(text)
        self._weights.append(weight)
        self._sessions.append(session_id)

    async def get_long_term_preferences(self, session_id: str, query: str = "") -> list:
        if not query or self._index.ntotal == 0:
            return []
        q = self.embedder.encode(query).reshape(1, -1)
        faiss.normalize_L2(q)
        k = min(self.long_term_top_k, self._index.ntotal)
        d, idx = self._index.search(q, k)
        return [
            {"preference": self._texts[i], "weight": self._weights[i], "score": round(float(d[0][j]), 3)}
            for j, i in enumerate(idx[0]) if i >= 0 and float(d[0][j]) > 0.2
        ]

    async def inject_memory_to_prompt(self, session_id: str, query: str, base: str) -> str:
        parts = [base]

        prefs = await self.get_long_term_preferences(session_id, query)
        if prefs:
            pref_lines = "\n".join(
                f"- {p['preference']} (置信度: {p['score']:.0%})"
                for p in prefs[:3]
            )
            parts.append(f"\n## 用户长期偏好\n{pref_lines}")

        recent = await self.get_short_term(session_id)
        if recent:
            history_text = "\n".join(
                f"{m.get('role', 'unknown')}: {m.get('content', '')[:100]}"
                for m in recent[-6:]
            )
            parts.append(f"\n## 近期对话历史\n{history_text}")

        return "\n".join(parts)

    def detect_preferences(self, text: str) -> list:
        return TravelMemoryManager.PREFERENCE_PATTERNS and [
            (t, 0.7) for t, ks in TravelMemoryManager.PREFERENCE_PATTERNS
            if any(k in text for k in ks)
        ] or []

    async def close(self):
        """本地内存无需释放外部连接，保留数据便于测试和交互会话复用。"""
        return None
