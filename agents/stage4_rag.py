"""
阶段四：旅游自适应 RAG 知识库检索

- 混合检索: BM25 (关键词) + Dense (语义向量) → 融合排序
- 重排机制: 轻量 Cross-Encoder → Top-3 精选
- 文档加载: 支持 PDF / 图片(OCR) / Markdown / TXT 全格式
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import faiss
from rank_bm25 import BM25Okapi

from .stage4_memory import Embedder

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 文档加载器
# ═══════════════════════════════════════════════════════════════

class TravelDocumentLoader:
    """旅游文档加载器：支持 PDF / 图片(OCR) / Markdown / TXT 全格式。

    支持的格式:
      .pdf  → PyMuPDF (fitz) 提取文字，pdfplumber 备选
      .png/.jpg/.jpeg/.bmp/.webp → pytesseract OCR 识别
      .md/.txt → 直接读取，按段落切分

    用法:
        docs = TravelDocumentLoader.load_directory("data/")     # 扫目录
        docs = TravelDocumentLoader.load_file("guide.pdf")      # 单文件
        docs = TravelDocumentLoader.from_texts(["攻略1","攻略2"]) # 直接文本
    """

    # ── 格式检测 ──
    PDF_EXTS = {'.pdf'}
    IMG_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tiff'}
    TEXT_EXTS = {'.txt', '.md', '.markdown', '.rst'}
    SUPPORTED_EXTS = PDF_EXTS | IMG_EXTS | TEXT_EXTS

    @classmethod
    def load_file(cls, filepath: str) -> List[Dict[str, str]]:
        """自动检测格式并加载单个文件。"""
        ext = os.path.splitext(filepath)[1].lower()
        fname = os.path.basename(filepath)

        if ext in cls.PDF_EXTS:
            return cls._load_pdf(filepath, fname)
        elif ext in cls.IMG_EXTS:
            return cls._load_image(filepath, fname)
        elif ext in cls.TEXT_EXTS:
            return cls._load_text(filepath, fname)
        else:
            logger.warning(f"不支持的文件格式: {ext}")
            return []

    @classmethod
    def load_directory(cls, doc_dir: str, recursive: bool = False) -> List[Dict[str, str]]:
        """扫描目录，加载所有支持的文档格式。

        Args:
            doc_dir: 目录路径
            recursive: 是否递归子目录
        """
        docs = []
        if not os.path.isdir(doc_dir):
            logger.warning(f"目录不存在: {doc_dir}")
            return docs

        for fname in sorted(os.listdir(doc_dir)):
            fpath = os.path.join(doc_dir, fname)
            if os.path.isfile(fpath):
                ext = os.path.splitext(fname)[1].lower()
                if ext in cls.SUPPORTED_EXTS:
                    docs.extend(cls.load_file(fpath))
            elif os.path.isdir(fpath) and recursive:
                docs.extend(cls.load_directory(fpath, recursive=True))

        logger.info(f"📂 {doc_dir}: 加载 {len(docs)} 个文本片段")
        return docs

    # ── 格式处理器 ──

    @classmethod
    def _load_pdf(cls, filepath: str, source: str) -> List[Dict[str, str]]:
        """PDF 解析: PyMuPDF 优先，pdfplumber 备选。"""
        docs = []

        # 方案1: PyMuPDF (快速稳定)
        try:
            import fitz
            doc = fitz.open(filepath)
            for page_num, page in enumerate(doc):
                text = page.get_text().strip()
                if len(text) > 15:
                    docs.append({"text": text, "source": f"{source}#p{page_num+1}"})
            doc.close()
            if docs:
                logger.info(f"📄 PDF(PyMuPDF): {source} → {len(docs)} 页")
                return docs
        except Exception as e:
            logger.debug(f"PyMuPDF 解析失败, 尝试 pdfplumber: {e}")

        # 方案2: pdfplumber (备选)
        try:
            import pdfplumber
            with pdfplumber.open(filepath) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text and len(text.strip()) > 15:
                        docs.append({"text": text.strip(), "source": f"{source}#p{page_num+1}"})
            if docs:
                logger.info(f"📄 PDF(pdfplumber): {source} → {len(docs)} 页")
                return docs
        except Exception as e:
            logger.warning(f"PDF 解析失败 [{source}]: {e}")

        return docs

    @classmethod
    def _load_image(cls, filepath: str, source: str) -> List[Dict[str, str]]:
        """图片 OCR: pytesseract + Pillow。

        注: 需要安装 tesseract 二进制 (brew install tesseract)。
        如果 tesseract 未安装，返回空列表并提示。
        """
        try:
            from PIL import Image
            import pytesseract

            img = Image.open(filepath)
            # 预处理: 转灰度 + 提高对比度 (提升OCR准确率)
            img = img.convert('L')
            text = pytesseract.image_to_string(img, lang='chi_sim+eng').strip()

            if len(text) > 10:
                logger.info(f"🖼️ OCR: {source} → {len(text)} 字符")
                return [{"text": text, "source": source}]
            else:
                logger.warning(f"OCR 结果过短 [{source}]: {text[:50]}")
                return []

        except ImportError:
            logger.warning("pytesseract 未安装，跳过图片OCR。pip install pytesseract")
            return []
        except Exception as e:
            # tesseract 二进制未安装时的友好提示
            if 'tesseract' in str(e).lower() or 'not installed' in str(e).lower():
                logger.warning(f"tesseract 未安装，跳过图片OCR。brew install tesseract")
            else:
                logger.warning(f"图片OCR失败 [{source}]: {e}")
            return []

    @classmethod
    def _load_text(cls, filepath: str, source: str) -> List[Dict[str, str]]:
        """文本文件: 直接读取，按双换行切段落。"""
        docs = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Markdown: 去掉常见标记符号，保留文字
            if source.endswith('.md'):
                import re
                content = re.sub(r'^#{1,6}\s+', '', content, flags=re.MULTILINE)  # 标题
                content = re.sub(r'[*_~`>|]', '', content)  # 格式符号
                content = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', content)  # 链接

            # 按段落切分
            for para in content.split('\n\n'):
                para = para.strip()
                if len(para) > 15:
                    docs.append({"text": para, "source": source})

            logger.info(f"📝 文本: {source} → {len(docs)} 段落")
        except Exception as e:
            logger.warning(f"文本读取失败 [{source}]: {e}")

        return docs

    @staticmethod
    def from_texts(texts: List[str], source: str = "manual") -> List[Dict[str, str]]:
        """从文本列表直接构建文档 (兼容旧接口)。"""
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

    def __init__(self, alpha: float = 0.3, embed_dim: int = 128,
                 index_dir: str = "data/faiss_index"):
        self.alpha = alpha
        self.embedder = Embedder(dim=embed_dim)
        self._bm25: Optional[BM25Okapi] = None
        self._documents: List[Dict[str, str]] = []
        self._ready = False
        self._vector_store = VectorStore(dim=embed_dim, path=index_dir)

    def index(self, documents: List[Dict[str, str]], save: bool = True):
        """构建索引 + 可选持久化保存。"""
        if not documents:
            return

        self._documents = documents
        texts = [d["text"] for d in documents]

        # BM25
        tokenized = [self._tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(tokenized)

        # Dense 向量化 → VectorStore
        self.embedder.fit(texts)
        vectors = np.array([self.embedder.encode(t) for t in texts], dtype=np.float32)

        self._vector_store.clear()
        self._vector_store.add(vectors, documents)

        self._ready = True
        logger.info(f"📚 RAG 索引就绪: {len(documents)} 篇文档")

        if save:
            self.save()

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

        # 2. Dense 检索 (VectorStore)
        query_vec = self.embedder.encode(query).astype(np.float32)
        vs_results = self._vector_store.search(query_vec, top_k=max(top_k * 3, 30))
        # 构建 dense_scores (对齐 documents 顺序)
        dense_scores = np.zeros(len(self._documents), dtype=np.float32)
        for idx, score in vs_results:
            if idx < len(dense_scores):
                dense_scores[idx] = float(score)

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

    def save(self, path: Optional[str] = None):
        """保存 BM25 + VectorStore + Embedder 到磁盘。"""
        self._vector_store.save(path)
        save_path = path if path else self._vector_store.base_path
        self.embedder.save(save_path)

    def load(self, path: Optional[str] = None) -> bool:
        """从磁盘加载索引。成功返回 True。"""
        if not self._vector_store.load(path):
            return False
        if self._vector_store._documents:
            self._documents = self._vector_store._documents
            load_path = path if path else self._vector_store.base_path
            texts = [d["text"] for d in self._documents]
            # 尝试加载 Embedder 状态，失败则回退到重新 fit
            if not self.embedder.load(load_path):
                self.embedder.fit(texts)
            tokenized = [self._tokenize(t) for t in texts]
            self._bm25 = BM25Okapi(tokenized)
            self._ready = True
            logger.info(f"📂 RAG 索引已加载: {len(self._documents)} 篇")
            return True
        return False

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
# ═══════════════════════════════════════════════════════════════
# 预置旅游知识库 (可从 data/ 目录加载 .md/.txt/.pdf/.png 等)
# ═══════════════════════════════════════════════════════════════

def _load_knowledge_base(data_dir: str = "data") -> List[Dict[str, str]]:
    """从 data/ + data/scraped/ + data/generated/ 加载全部知识库。"""
    all_docs = []
    dirs = [data_dir, f"{data_dir}/scraped", f"{data_dir}/generated"]
    
    for d in dirs:
        if os.path.isdir(d):
            docs = TravelDocumentLoader.load_directory(d)
            if docs:
                all_docs.extend(docs)
    
    if all_docs:
        logger.info(f"📂 知识库: {len(all_docs)} 片段 (来自 {len(dirs)} 个目录)")
        return all_docs

    # 回退: 内置旅游知识
    logger.info("无知识库文件，使用内置文本")
    return TravelDocumentLoader.from_texts([
        "三亚不要中午去海滩会晒脱皮，建议早上8点或下午4点后下水，涂SPF50+防晒",
        "北京故宫→景山公园→北海公园→南锣鼓巷一天走完不绕路，全程步行",
        "成都别去锦里吃小吃，贵且不正宗，本地人去建设巷和奎星楼街，人均50撑到爆",
        "都江堰一日游: 上午都江堰下午青城山前山，晚上回成都吃火锅，一天完美",
        "出行通用: 提前预订至少省30%，酒店占预算40%餐饮30%交通20%门票10%",
        "三亚亚龙湾沙质最细适合游泳，大东海性价比高，三亚湾看日落最佳",
    ], "builtin")


class TravelRAG:
    """
    旅游 RAG 检索节点 — 供 Agent 编排器调用。

    用法:
        rag = TravelRAG()
        rag.load_knowledge(TravelRAG.default_knowledge())
        results = rag.search("北京故宫怎么玩", top_k=5)
        context = rag.format_context(results)  # → 注入 LLM prompt
    """

    def __init__(self, alpha: float = 0.3, index_dir: str = "data/faiss_index"):
        self.retriever = HybridRetriever(alpha=alpha, index_dir=index_dir)
        self.reranker = LightweightReranker()
        self._loaded = False
        self._index_dir = index_dir

    def load_knowledge(self, documents: List[Dict[str, str]]):
        """加载知识库文档并构建索引 + 持久化保存。"""
        if documents:
            self.retriever.index(documents, save=True)
            self._loaded = True

    def load_from_disk(self) -> bool:
        """从磁盘恢复索引 (跳过文档解析，秒级启动)。"""
        ok = self.retriever.load(self._index_dir)
        if ok:
            self._loaded = True
        return ok

    @staticmethod
    def default_knowledge() -> List[Dict[str, str]]:
        """加载知识库: 从 data/ 目录读取文件 → 内置文本回退。"""
        return _load_knowledge_base("data")

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

# ═══════════════════════════════════════════════════════════════
# 4. 持久化向量存储 (FAISS 磁盘索引)
# ═══════════════════════════════════════════════════════════════

class VectorStore:
    """
    FAISS 持久化向量存储 — 支持增量追加 + 磁盘保存/加载。

    每次 index() 后自动保存，下次启动 load() 即可恢复，无需重建索引。

    用法:
        store = VectorStore(dim=128, path="data/faiss_index")
        store.add(vectors, documents)
        store.save()

        # 重启后
        store2 = VectorStore(path="data/faiss_index")
        store2.load()
        results = store2.search(query_vec, top_k=5)
    """

    def __init__(self, dim: int = 128, path: str = "data/faiss_index"):
        self.dim = dim
        self.base_path = path
        self.index: Optional[faiss.IndexFlatIP] = None
        self._documents: List[Dict[str, str]] = []
        self._id_to_idx: Dict[str, int] = {}  # doc_id → FAISS 内部 offset

    @property
    def count(self) -> int:
        return self.index.ntotal if self.index else 0

    # ── 向量操作 ──

    def add(self, vectors: np.ndarray, documents: List[Dict[str, str]]):
        """
        追加向量 + 文档到存储。

        vectors: [N, dim] float32, 需已 L2 归一化
        documents: 对应元数据列表
        """
        if self.index is None:
            self.index = faiss.IndexFlatIP(self.dim)

        if len(vectors) == 0:
            return

        # L2 归一化 (确保内积 = 余弦相似度)
        faiss.normalize_L2(vectors)
        start_idx = self.index.ntotal

        self.index.add(vectors)

        for i, doc in enumerate(documents):
            doc_id = doc.get("id", f"doc_{start_idx + i}")
            self._id_to_idx[doc_id] = start_idx + i
        self._documents.extend(documents)

        logger.info(f"📥 VectorStore: +{len(vectors)} 条 → 共 {self.count} 条")

    def search(self, query_vec: np.ndarray, top_k: int = 10) -> List[Tuple[int, float]]:
        """
        向量检索 — 返回 (doc_offset, similarity_score) 列表。
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        q = query_vec.reshape(1, -1).astype(np.float32)
        faiss.normalize_L2(q)
        scores, indices = self.index.search(q, min(top_k, self.index.ntotal))
        return [(int(indices[0][i]), float(scores[0][i])) for i in range(len(indices[0])) if indices[0][i] >= 0]

    def get_document(self, idx: int) -> Optional[Dict[str, str]]:
        """按 offset 取文档。"""
        if 0 <= idx < len(self._documents):
            return self._documents[idx]
        return None

    # ── 持久化 ──

    def save(self, path: Optional[str] = None):
        """
        保存到磁盘:
          {path}.index  → FAISS 向量索引
          {path}.meta   → 文档元数据 (JSON)
        """
        save_path = path or self.base_path
        if self.index is None:
            logger.warning("VectorStore: 无数据可保存")
            return

        # 保存 FAISS 索引
        faiss.write_index(self.index, f"{save_path}.index")

        # 保存元数据
        import json as _json
        meta = {
            "dim": self.dim,
            "count": self.count,
            "documents": self._documents,
            "id_to_idx": self._id_to_idx,
        }
        with open(f"{save_path}.meta.json", "w", encoding="utf-8") as f:
            _json.dump(meta, f, ensure_ascii=False, indent=2)

        logger.info(f"💾 VectorStore 已保存: {self.count} 条 → {save_path}.index + .meta.json")

    def load(self, path: Optional[str] = None):
        """
        从磁盘加载。加载后可直接 search()。
        返回 True 表示加载成功。
        """
        load_path = path or self.base_path
        import json as _json

        index_file = f"{load_path}.index"
        meta_file = f"{load_path}.meta.json"

        if not os.path.exists(index_file) or not os.path.exists(meta_file):
            logger.info(f"VectorStore: 无已保存索引 ({load_path})")
            return False

        try:
            self.index = faiss.read_index(index_file)
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = _json.load(f)
            self.dim = meta["dim"]
            self._documents = meta["documents"]
            self._id_to_idx = meta.get("id_to_idx", {})

            logger.info(f"📂 VectorStore 已加载: {self.count} 条 (dim={self.dim})")
            return True
        except Exception as e:
            logger.warning(f"VectorStore 加载失败: {e}")
            self.index = faiss.IndexFlatIP(self.dim)
            return False

    def clear(self):
        """清空存储。"""
        self.index = faiss.IndexFlatIP(self.dim)
        self._documents = []
        self._id_to_idx = {}
