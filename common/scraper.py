"""
通用爬虫基类 — 马蜂窝 + 穷游网 共享基础设施。

特性: 异步请求 / 速率限制 / 反爬伪装 / HTML 清洗 / 自动入库 RAG
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ─── 伪装请求头 ───
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


class RateLimiter:
    """异步速率限制器 — 两次请求间隔 1-3 秒随机。"""

    def __init__(self, min_delay: float = 1.0, max_delay: float = 3.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._last_request = 0.0

    async def wait(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_delay:
            await asyncio.sleep(self.min_delay - elapsed + random.uniform(0, self.max_delay - self.min_delay))
        self._last_request = time.monotonic()


class BaseScraper(ABC):
    """爬虫基类: 提供 fetch / parse / save 通用能力。"""

    def __init__(self, name: str, output_dir: str = "data/scraped"):
        self.name = name
        self.output_dir = output_dir
        self.rate_limiter = RateLimiter()
        self._session: Optional[aiohttp.ClientSession] = None
        os.makedirs(output_dir, exist_ok=True)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._session

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None

    async def fetch(self, url: str, retries: int = 3) -> Optional[str]:
        """GET 请求，带重试。"""
        session = await self._get_session()
        await self.rate_limiter.wait()

        for attempt in range(retries):
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.text()
                    elif resp.status == 403:
                        logger.warning(f"403 被拒绝: {url}")
                        await asyncio.sleep(5 * (attempt + 1))
                    elif resp.status == 404:
                        logger.warning(f"404: {url}")
                        return None
                    else:
                        logger.warning(f"HTTP {resp.status}: {url}")
                        await asyncio.sleep(2)
            except asyncio.TimeoutError:
                logger.warning(f"超时 第{attempt+1}次: {url}")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"请求失败 [{url}]: {e}")
                await asyncio.sleep(2)
        return None

    def clean_text(self, text: str) -> str:
        """清洗文本: 去多余空白、控制字符。"""
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()

    def text_to_chunks(self, text: str, source: str, max_len: int = 500) -> List[Dict[str, str]]:
        """将长文本按句号/换行切分为 RAG 友好的 chunk。"""
        if len(text) <= max_len:
            return [{"text": text, "source": source}] if len(text) > 20 else []

        chunks = []
        # 按句号+换行切分
        sentences = re.split(r'[。！？\n]+', text)
        current = ""
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if len(current) + len(s) < max_len:
                current += s + "。"
            else:
                if len(current) > 20:
                    chunks.append({"text": current.rstrip("。"), "source": source})
                current = s + "。"
        if len(current) > 20:
            chunks.append({"text": current.rstrip("。"), "source": source})
        return chunks

    def save_chunks(self, chunks: List[Dict[str, str]], filename: str):
        """保存为 Markdown 文件到 data/scraped/。"""
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            # 标题
            f.write(f"# {self.name} · {filename.replace('.md','')}\n\n")
            for i, c in enumerate(chunks):
                f.write(f"{c['text']}\n\n")
        logger.info(f"💾 保存: {filepath} ({len(chunks)} 片段)")

    @abstractmethod
    async def scrape_destination(self, city: str, url: Optional[str] = None) -> List[Dict[str, str]]:
        """爬取单个目的地攻略。返回 RAG chunks。"""
        ...

    async def scrape_and_import(self, city: str, url: Optional[str] = None) -> List[Dict[str, str]]:
        """爬取 → 清洗 → 存文件 → 返回 chunks。url=None 时自动从 get_city_url() 获取。"""
        logger.info(f"🕷️ [{self.name}] 爬取: {city}")
        chunks = await self.scrape_destination(city, url)
        if chunks:
            safe_name = re.sub(r'[^\w]', '_', city)
            self.save_chunks(chunks, f"{self.name}_{safe_name}.md")
        return chunks
