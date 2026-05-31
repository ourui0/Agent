"""
马蜂窝爬虫 — 目的地攻略页 (公开页面)

URL 格式: https://www.mafengwo.cn/travel-scenic-spot/mafengwo/{city_id}.html
示例: 北京=10065, 成都=10444, 三亚=10068, 上海=10099

提取: 概况/交通/美食/住宿/景点/实用贴士 → Markdown chunk
"""

import logging
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from common.scraper import BaseScraper

logger = logging.getLogger(__name__)

# 城市 ID → 中文名 + URL 后缀
CITY_MAP = {
    "北京": {"id": "10065", "en": "beijing"},
    "成都": {"id": "10444", "en": "chengdu"},
    "三亚": {"id": "10068", "en": "sanya"},
    "上海": {"id": "10099", "en": "shanghai"},
    "西安": {"id": "10031", "en": "xian"},
    "重庆": {"id": "10445", "en": "chongqing"},
    "杭州": {"id": "10032", "en": "hangzhou"},
    "丽江": {"id": "10208", "en": "lijiang"},
    "大理": {"id": "10209", "en": "dali"},
    "厦门": {"id": "10156", "en": "xiamen"},
    "广州": {"id": "10088", "en": "guangzhou"},
    "深圳": {"id": "10089", "en": "shenzhen"},
}

MAFENGWO_GUIDE_URL = "https://www.mafengwo.cn/travel-scenic-spot/mafengwo/{city_id}.html"


class MafengwoScraper(BaseScraper):
    """马蜂窝目的地攻略爬虫。"""

    def __init__(self):
        super().__init__(name="mafengwo")

    @staticmethod
    def get_city_url(city: str) -> Optional[str]:
        """根据城市名获取攻略页 URL。"""
        info = CITY_MAP.get(city)
        if info:
            return MAFENGWO_GUIDE_URL.format(city_id=info["id"])
        return None

    async def scrape_destination(self, city: str, url: str = None) -> List[Dict[str, str]]:
        """
        爬取城市攻略页:
        1. 概况简介 → chunk
        2. 实用攻略 (交通/美食/住宿/景点) → chunks
        3. 小贴士 → chunk
        """
        if url is None:
            url = self.get_city_url(city)
        if url is None:
            logger.warning(f"马蜂窝: 未知城市 {city}, 可用: {list(CITY_MAP.keys())}")
            return []

        html = await self.fetch(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        chunks = []

        # ── 1. 概况 ──
        summary = self._extract_summary(soup, city)
        if summary:
            chunks.extend(self.text_to_chunks(summary, f"mafengwo/{city}/summary"))

        # ── 2. 分区攻略 (交通/美食/住宿/景点/购物) ──
        sections = self._extract_sections(soup, city)
        for section_title, section_text in sections:
            chunks.extend(self.text_to_chunks(section_text, f"mafengwo/{city}/{section_title}"))

        # ── 3. 实用贴士 ──
        tips = self._extract_tips(soup, city)
        if tips:
            chunks.extend(self.text_to_chunks(tips, f"mafengwo/{city}/tips"))

        logger.info(f"🕷️ 马蜂窝 [{city}]: {len(chunks)} 个 chunk")
        return chunks

    # ─── 提取器 ───

    def _extract_summary(self, soup: BeautifulSoup, city: str) -> str:
        """提取城市概况。"""
        # 尝试找 .summary 或 .bd 中的简介文字
        for selector in [".summary", ".bd .txt", ".m-box .bd p"]:
            el = soup.select_one(selector)
            if el:
                text = self.clean_text(el.get_text())
                if len(text) > 30:
                    return f"{city}旅游概况: {text}"
        return ""

    def _extract_sections(self, soup: BeautifulSoup, city: str) -> List[tuple]:
        """
        提取分区攻略标题和内容。
        结构: h3=标题, 后续 p/li=内容
        """
        sections = []
        current_title = ""
        current_lines = []

        # 找所有 h3/h2 标题
        content_area = soup.select_one(".bd, .m-box, article, .section")
        if not content_area:
            content_area = soup

        for tag in content_area.find_all(["h2", "h3", "h4", "p", "li"]):
            if tag.name in ("h2", "h3", "h4"):
                # 遇到新标题 — 保存上一节
                if current_title and len(current_lines) >= 1:
                    text = "\n".join(current_lines)
                    if len(self.clean_text(text)) > 30:
                        sections.append((current_title, text))
                current_title = self.clean_text(tag.get_text())[:30]
                current_lines = []
            elif current_title:
                line = self.clean_text(tag.get_text())
                if len(line) > 10 and not line.startswith(("©", "声明", "版权", "转载")):
                    current_lines.append(line)

        # 最后一节
        if current_title and len(current_lines) >= 1:
            text = "\n".join(current_lines)
            if len(self.clean_text(text)) > 30:
                sections.append((current_title, text))

        return sections

    def _extract_tips(self, soup: BeautifulSoup, city: str) -> str:
        """提取实用贴士。"""
        tips_sections = soup.find_all(text=re.compile(r"实用|贴士|Tips|注意|建议|攻略"))
        lines = []
        for node in tips_sections:
            parent = node.parent
            if parent:
                # 取同级或父级下的列表项
                for li in parent.find_all("li"):
                    text = self.clean_text(li.get_text())
                    if len(text) > 8 and text not in lines:
                        lines.append(text)
        if lines:
            return f"{city} 实用贴士:\n" + "\n".join(lines)
        return ""


# ─── 批量爬取入口 ───

async def scrape_mafengwo_cities(cities: List[str] = None) -> List[Dict[str, str]]:
    """
    批量爬取马蜂窝攻略。
    不传 cities 则爬取全部支持城市。
    """
    scraper = MafengwoScraper()
    all_chunks = []

    targets = cities or list(CITY_MAP.keys())
    for city in targets:
        try:
            chunks = await scraper.scrape_and_import(city)
            all_chunks.extend(chunks)
        except Exception as e:
            logger.error(f"马蜂窝爬取失败 [{city}]: {e}")

    await scraper.close()
    logger.info(f"🏁 马蜂窝批量爬取完成: {len(targets)} 城市, {len(all_chunks)} 个 chunk")
    return all_chunks
