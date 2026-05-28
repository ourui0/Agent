"""
阶段四：旅游自适应 RAG 知识库检索

- 混合检索: BM25 (关键词) + Dense (语义向量) → 融合排序
- 重排机制: 轻量 Cross-Encoder → Top-3 精选
- 文档加载: 支持 txt/md，框架预留 PDF 接口
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from rank_bm25 import BM25Okapi

from .stage4_memory import Embedder

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 文档加载器
# ═══════════════════════════════════════════════════════════════

class TravelDocumentLoader:
    """旅游文档加载器：支持 txt/md 文件，预留 PDF 扩展点。"""

    @staticmethod
    def load_directory(doc_dir: str) -> List[Dict[str, str]]:
        """加载目录下所有文档，返回 [{text, source}] 列表。"""
        docs = []
        if not os.path.isdir(doc_dir):
            return docs

        for fname in sorted(os.listdir(doc_dir)):
            fpath = os.path.join(doc_dir, fname)
            if fname.endswith(('.txt', '.md')):
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 按段落切分
                for para in content.split('\n\n'):
                    para = para.strip()
                    if len(para) > 20:
                        docs.append({"text": para, "source": fname})
        return docs

    @staticmethod
    def from_texts(texts: List[str], source: str = "manual") -> List[Dict[str, str]]:
        """从文本列表直接构建文档。"""
        docs = []
        for t in texts:
            t = t.strip()
            if len(t) > 10:
                docs.append({"text": t, "source": source})
        return docs


# ═══════════════════════════════════════════════════════════════
# 混合检索引擎 (BM25 + Dense)
# ═══════════════════════════════════════════════════════════════

class HybridRetriever:
    """
    混合检索：BM25 (关键词精确匹配) + 语义向量 (语义相似)。

    融合公式: score = α * bm25_score + (1-α) * dense_score
    """

    def __init__(self, alpha: float = 0.3, embed_dim: int = 128):
        self.alpha = alpha  # BM25 权重
        self.embedder = Embedder(dim=embed_dim)
        self._bm25: Optional[BM25Okapi] = None
        self._documents: List[Dict[str, str]] = []
        self._doc_vectors: Optional[np.ndarray] = None
        self._ready = False

    def index(self, documents: List[Dict[str, str]]):
        """构建索引。"""
        if not documents:
            return

        self._documents = documents
        texts = [d["text"] for d in documents]

        # BM25 分词
        tokenized = [self._tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(tokenized)

        # Dense 向量化
        self.embedder.fit(texts)
        vectors = np.array([self.embedder.encode(t) for t in texts], dtype=np.float32)
        # L2 归一化
        norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8
        self._doc_vectors = vectors / norms

        self._ready = True
        logger.info(f"📚 RAG 索引就绪: {len(documents)} 篇文档")

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """简单中文分词 (按字符 bigram)。"""
        # 按字切分 + bigram 覆盖词组
        chars = list(text.replace(' ', ''))
        tokens = chars.copy()
        for i in range(len(chars) - 1):
            tokens.append(chars[i] + chars[i+1])
        return tokens

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        混合检索: BM25 + Dense 融合 → Top-K。
        返回: [{"text":..., "source":..., "bm25_score":..., "dense_score":..., "combined_score":...}, ...]
        """
        if not self._ready:
            return []

        tokenized_query = self._tokenize(query)

        # 1. BM25 检索
        bm25_scores = np.array(self._bm25.get_scores(tokenized_query))

        # 2. Dense 检索
        query_vec = self.embedder.encode(query).astype(np.float32)
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        dense_scores = np.dot(self._doc_vectors, query_vec)

        # 3. 归一化 + 融合
        bm25_norm = self._minmax_norm(bm25_scores)
        dense_norm = self._minmax_norm(dense_scores)
        combined = self.alpha * bm25_norm + (1 - self.alpha) * dense_norm

        # 4. Top-K
        top_indices = np.argsort(combined)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if combined[idx] > 0.05:  # 最低相似度阈值
                doc = self._documents[idx]
                results.append({
                    "text": doc["text"],
                    "source": doc.get("source", ""),
                    "bm25_score": round(float(bm25_norm[idx]), 3),
                    "dense_score": round(float(dense_norm[idx]), 3),
                    "combined_score": round(float(combined[idx]), 3),
                })

        return results

    @staticmethod
    def _minmax_norm(arr: np.ndarray) -> np.ndarray:
        """Min-Max 归一化到 [0, 1]。"""
        a_min, a_max = arr.min(), arr.max()
        if a_max - a_min < 1e-8:
            return np.zeros_like(arr)
        return (arr - a_min) / (a_max - a_min)


# ═══════════════════════════════════════════════════════════════
# 重排器 (Reranker)
# ═══════════════════════════════════════════════════════════════

class LightweightReranker:
    """
    轻量重排器：用规则 + 语义相似度做二次排序。

    规则:
    1. 与 query 的重叠词数越多越好 (精确匹配加分)
    2. Dense 相似度重算 (语义相关加分)
    3. 文档长度惩罚 (太短/太长扣分)
    """

    def __init__(self, embedder: Optional[Embedder] = None):
        self.embedder = embedder or Embedder(dim=128)

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """重排候选文档，返回 Top-K。"""
        if not candidates:
            return []

        query_vec = self.embedder.encode(query).astype(np.float32)
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        query_chars = set(query)

        for cand in candidates:
            text = cand["text"]
            text_vec = self.embedder.encode(text).astype(np.float32)
            text_vec = text_vec / (np.linalg.norm(text_vec) + 1e-8)

            # 语义分数
            dense = float(np.dot(query_vec, text_vec))

            # 词重叠分数
            text_chars = set(text)
            overlap = len(query_chars & text_chars) / max(len(query_chars), 1)

            # 长度惩罚 (最优 50-300 字)
            text_len = len(text)
            if text_len < 20:
                len_penalty = 0.5
            elif text_len > 500:
                len_penalty = 0.7
            else:
                len_penalty = 1.0

            # 综合重排分
            cand["rerank_score"] = round(
                0.5 * dense + 0.3 * overlap + 0.2 * len_penalty, 3
            )

        # 按 rerank_score 排序
        reranked = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)
        return reranked[:top_k]


# ═══════════════════════════════════════════════════════════════
# 旅游知识库 (预置攻略)
# ═══════════════════════════════════════════════════════════════

DEFAULT_TRAVEL_KNOWLEDGE = [
    # 北京
    "故宫旺季门票60元需提前7天预约每天限流8万人次建议上午8:30开门就入场避开人流高峰",
    "八达岭长城距市区70公里建议早7点前从德胜门坐877路直达约2小时车程缆车单程100元往返140元",
    "北京烤鸭推荐四季民福故宫店人均150元可以看到东华门景观需要提前2小时排队取号",
    "颐和园面积约300公顷完整游览需4-5小时建议从东宫门进沿长廊到佛香阁最后从北宫门出",
    # 成都
    "大熊猫基地建议早8点前到达熊猫9点后开始睡觉月亮产房和太阳产房是最佳观赏点门票55元",
    "宽窄巷子免费开放由宽巷子窄巷子井巷子三条巷子组成适合下午到晚上游览品尝三大炮蛋烘糕",
    "都江堰距成都60公里可在犀浦站坐城际列车30分钟到达门票80元建议请讲解员了解水利工程原理",
    "成都火锅推荐小龙坎老火锅春熙路店人均100元必点毛肚鹅肠黄喉记得点微辣因为成都微辣等于外地中辣",
    # 三亚
    "亚龙湾沙滩免费水质最佳时间是上午10点前和下午4点后中午暴晒不宜下水附近海鲜市场可代加工",
    "天涯海角门票旺季101元淡季85元建议下午4点后入园既能避开酷热又能看到日落海景",
    "蜈支洲岛需从码头乘船约20分钟往返船票加门票144元岛上水上项目潜水约429元起建议自备干粮岛上餐饮较贵",
    # 上海
    "外滩最佳观赏时间是傍晚6-8点灯光亮起夜景绝佳南京路步行街从外滩一直延伸到人民广场",
    "上海迪士尼平日门票475元周末665元下载官方APP看实时排队建议先冲飞越地平线和创极速光轮",
    # 通用
    "国内酒店入住时间一般为14:00退房12:00民宿可协商行李寄存大部分酒店提供免费寄存服务",
    "出行前务必检查身份证件故宫长城等热门景点需实名制购票学生证可享门票半价优惠",
    "建议购买旅行意外险约30-50元保障范围包括航班延误行李丢失医疗救助等",
    "国内航班经济舱免费托运20kg手提7kg廉价航空如春秋无免费托运需提前购买行李额",
]

# 小红 书风格攻略
XHS_STYLE_KNOWLEDGE = [
    "姐妹们听劝❗三亚千万不要中午去海滩会晒脱皮❗建议早上8点或下午4点后下水涂SPF50+防晒",
    "北京土著私藏路线🔥故宫→景山公园→北海公园→南锣鼓巷一天走完不绕路全程步行🚶",
    "成都吃货避雷⚠️别去锦里吃小吃贵且不正宗本地人都去建设巷和奎星楼街人均50撑到爆",
    "都江堰一日游攻略💯上午都江堰下午青城山前山⛰️晚上回成都吃火锅一天完美",
]


class TravelRAG:
    """
    旅游 RAG 检索节点 — 供 Agent 编排器调用。

    用法:
        rag = TravelRAG()
        rag.load_knowledge(TravelRAG.default_knowledge())
        results = rag.search("北京故宫怎么玩", top_k=5)
        context = rag.format_context(results)  # → 注入 LLM prompt
    """

    def __init__(self, alpha: float = 0.3):
        self.retriever = HybridRetriever(alpha=alpha)
        self.reranker = LightweightReranker()
        self._loaded = False

    def load_knowledge(self, documents: List[Dict[str, str]]):
        """加载知识库文档并构建索引。"""
        if documents:
            self.retriever.index(documents)
            self._loaded = True

    @staticmethod
    def default_knowledge() -> List[Dict[str, str]]:
        """预置旅游知识库。"""
        docs = TravelDocumentLoader.from_texts(DEFAULT_TRAVEL_KNOWLEDGE, "travel_guide")
        docs += TravelDocumentLoader.from_texts(XHS_STYLE_KNOWLEDGE, "xiaohongshu")
        return docs

    def search(self, query: str, top_k: int = 10, rerank_top_k: int = 3) -> List[Dict[str, Any]]:
        """混合检索 → 重排 → Top-3 精选。"""
        if not self._loaded:
            return []

        # 第一阶段: 混合检索 Top-10
        candidates = self.retriever.search(query, top_k=top_k)

        # 第二阶段: 重排 Top-3
        return self.reranker.rerank(query, candidates, top_k=rerank_top_k)

    def format_context(self, results: List[Dict[str, Any]]) -> str:
        """将检索结果格式化为 LLM 可用的上下文字符串。"""
        if not results:
            return ""

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] ({r.get('source', '')}) {r['text']}")

        return "\n".join(lines)
