"""
穷游网爬虫 — 目的地攻略页 (公开页面)

URL 格式: https://place.qyer.com/{city_en}/
示例: beijing, chengdu, sanya, shanghai

提取: 概况/必读/交通/美食/景点/购物/安全 → Markdown chunk
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from common.scraper import BaseScraper

logger = logging.getLogger(__name__)

# 城市英文名 → 中文名
CITY_MAP = {
    "北京": "beijing",
    "成都": "chengdu",
    "三亚": "sanya",
    "上海": "shanghai",
    "西安": "xian",
    "重庆": "chongqing",
    "杭州": "hangzhou",
    "丽江": "lijiang",
    "广州": "guangzhou",
    "厦门": "xiamen",
    "深圳": "shenzhen",
    "南京": "nanjing",
    "青岛": "qingdao",
}

QYER_PLACE_URL = "https://place.qyer.com/{en}/"


class QyerScraper(BaseScraper):
    """穷游网目的地攻略爬虫。"""

    def __init__(self):
        super().__init__(name="qyer")

    @staticmethod
    def get_city_url(city: str) -> Optional[str]:
        """根据城市名获取穷游攻略页 URL。"""
        en = CITY_MAP.get(city)
        if en:
            return QYER_PLACE_URL.format(en=en)
        return None

    async def scrape_destination(self, city: str, url: str = None) -> List[Dict[str, str]]:
        """
        爬取穷游目的地页:
        1. 概况 + 必读 → chunk
        2. 各栏目内容 (交通/美食/景点/购物/安全) → chunks
        3. 实用信息 → chunks
        """
        if url is None:
            url = self.get_city_url(city)
        if url is None:
            logger.warning(f"穷游: 未知城市 {city}, 可用: {list(CITY_MAP.keys())}")
            return []

        html = await self.fetch(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        chunks = []

        # ── 1. 简介 ──
        summary = self._extract_text(soup, [".placeinfo .bd", ".summary", "meta[name='description']"])
        if summary:
            chunks.extend(self.text_to_chunks(f"{city}穷游攻略: {summary}", f"qyer/{city}/summary"))

        # ── 2. 必读 (行程/景点/美食/交通等栏目) ──
        sections = self._extract_qyer_sections(soup, city)
        for title, text in sections:
            chunks.extend(self.text_to_chunks(text, f"qyer/{city}/{title}"))

        # ── 3. 所有段落文字 ──
        content_text = self._extract_all_paragraphs(soup)
        if content_text:
            for para in content_text:
                chunks.extend(self.text_to_chunks(para, f"qyer/{city}/guide"))

        logger.info(f"🕷️ 穷游 [{city}]: {len(chunks)} 个 chunk")
        return chunks

    # ─── 提取器 ───

    def _extract_text(self, soup: BeautifulSoup, selectors: list) -> str:
        """尝试多个 CSS 选择器提取文本。"""
        for sel in selectors:
            if sel.startswith("meta"):
                el = soup.select_one(sel)
                if el and el.get("content"):
                    return self.clean_text(el["content"])
            else:
                el = soup.select_one(sel)
                if el:
                    text = self.clean_text(el.get_text())
                    if len(text) > 30:
                        return text
        return ""

    def _extract_qyer_sections(self, soup: BeautifulSoup, city: str) -> List[tuple]:
        """
        提取穷游的板块栏目。
        穷游页面通常用 .item 或 .section 区分栏目。
        """
        sections = []
        # 找所有栏目标题和内容
        seen_texts = set()

        for container in soup.select(".item, .section, .module, .guide-item, .info-item"):
            title_el = container.select_one("h2, h3, h4, .title, .tit")
            title = self.clean_text(title_el.get_text()) if title_el else ""

            # 取内容文字
            text_parts = []
            for p in container.select("p, li, .txt, .desc, .content"):
                t = self.clean_text(p.get_text())
                if len(t) > 10 and t not in seen_texts:
                    text_parts.append(t)
                    seen_texts.add(t)

            if text_parts:
                label = title or "攻略"
                sections.append((f"{label}", "\n".join(text_parts)))

        return sections

    def _extract_all_paragraphs(self, soup: BeautifulSoup) -> List[str]:
        """提取所有有意义的段落文字。"""
        # 排除脚本/样式/导航
        for tag in soup.select("script, style, nav, footer, header, .nav, .footer, .header"):
            tag.decompose()

        paragraphs = []
        seen = set()

        for p in soup.select("p, .txt, .desc"):
            text = self.clean_text(p.get_text())
            # 只保留有意义的 (至少包含中文)
            if len(text) > 20 and re.search(r'[\u4e00-\u9fff]', text) and text not in seen:
                paragraphs.append(text)
                seen.add(text)

        return paragraphs


# ─── 批量爬取入口 ───

async def scrape_qyer_cities(cities: List[str] = None) -> List[Dict[str, str]]:
    """批量爬取穷游攻略。"""
    scraper = QyerScraper()
    all_chunks = []

    targets = cities or list(CITY_MAP.keys())
    for city in targets:
        try:
            chunks = await scraper.scrape_and_import(city)
            all_chunks.extend(chunks)
        except Exception as e:
            logger.error(f"穷游爬取失败 [{city}]: {e}")

    await scraper.close()
    logger.info(f"🏁 穷游批量爬取完成: {len(targets)} 城市, {len(all_chunks)} 个 chunk")
    return all_chunks
