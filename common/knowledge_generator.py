"""
DeepSeek 旅游知识生成器 — 批量生成结构化城市攻略

用法:
    python main.py --generate-knowledge          # 生成全部城市
    python main.py --generate-knowledge --scrape-city 成都  # 单城市
"""

import asyncio
import json
import logging
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 支持的城市列表
CITIES = [
    "北京", "成都", "三亚", "上海", "西安", "重庆",
    "杭州", "丽江", "大理", "厦门", "广州", "深圳",
    "南京", "青岛", "桂林", "张家界", "哈尔滨", "拉萨",
    "苏州", "长沙", "武汉", "昆明", "贵阳", "乌鲁木齐",
]

GENERATE_PROMPT = """你是资深旅游攻略写手。请为{city}生成一份详细的旅游攻略。

必须包含以下章节(每个章节用 ## 标题):

## 最佳旅行时间
- 推荐月份、季节特点、注意事项

## 必去景点 (5个)
- 景点名: 一句话亮点, 门票价格, 建议游玩时长

## 美食推荐 (5个)
- 餐厅/小吃名: 特色菜, 人均价格, 位置

## 交通指南
- 机场/火车站到市区、市内交通方式、打车起步价

## 住宿建议
- 推荐区域、预算范围、酒店类型

## 行程推荐
- 3天经典行程 (每天2-3个景点+餐饮安排)

## 实用贴士
- 避坑指南、省钱技巧、安全提示

要求:
- 信息准确、具体可操作，不要泛泛而谈
- 价格用人民币，时间用小时/分钟
- 每条信息独立成行，方便检索"""

OUTPUT_DIR = "data/generated"


def clean_markdown(text: str) -> str:
    """清洗 LLM 输出，提取纯文本段落。"""
    # 去掉 markdown 标记但保留结构
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.startswith("```"):
            continue
        # 保留 ## 标题
        if line.startswith("## "):
            lines.append(line)
        elif len(line) > 15:
            lines.append(re.sub(r'[*_~`]', '', line))
    return "\n".join(lines)


def split_to_chunks(text: str, source: str, max_chars: int = 600) -> List[Dict[str, str]]:
    """将生成的攻略切分为 RAG chunk。"""
    chunks = []
    # 按 ## 标题切分
    sections = re.split(r'\n(?=## )', text)
    for section in sections:
        section = section.strip()
        if not section or len(section) < 30:
            continue

        # 尝试从标题提取城市+主题
        title_match = re.match(r'## (.+)', section)
        topic = title_match.group(1).strip() if title_match else "攻略"

        # 如果段落太长，按句号再切
        if len(section) > max_chars:
            sentences = re.split(r'[。！？\n]', section)
            current = ""
            for s in sentences:
                s = s.strip()
                if not s:
                    continue
                if len(current) + len(s) < max_chars:
                    current += s + "。"
                else:
                    if len(current) > 20:
                        chunks.append({"text": current.rstrip("。"), "source": source})
                    current = s + "。"
            if len(current) > 20:
                chunks.append({"text": current.rstrip("。"), "source": source})
        else:
            chunks.append({"text": section, "source": source})
    return chunks


async def generate_city_knowledge(city: str, api_key: str = None) -> List[Dict[str, str]]:
    """
    使用 DeepSeek 生成单个城市的旅游攻略。

    返回: RAG chunks 列表
    """
    from openai import OpenAI

    api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        logger.warning("DEEPSEEK_API_KEY 未设置，跳过生成")
        return []

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    prompt = GENERATE_PROMPT.format(city=city)

    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是专业旅游攻略写手，回复详尽具体。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=2048,
            )
        )
        content = resp.choices[0].message.content or ""
        if not content:
            return []

        # 清洗 + 切分
        cleaned = clean_markdown(content)
        chunks = split_to_chunks(cleaned, f"deepseek/{city}")

        # 保存原始输出
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        filepath = os.path.join(OUTPUT_DIR, f"{city}.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {city} 旅游攻略 (DeepSeek 生成)\n\n")
            f.write(content)

        logger.info(f"🤖 DeepSeek [{city}]: {len(chunks)} 个 chunk → {filepath}")
        return chunks

    except Exception as e:
        logger.error(f"DeepSeek 生成失败 [{city}]: {e}")
        return []


async def generate_all_knowledge(cities: List[str] = None, api_key: str = None) -> List[Dict[str, str]]:
    """批量生成城市攻略。"""
    targets = cities or CITIES
    all_chunks = []

    # 限流: 每分钟 10 个城市
    sem = asyncio.Semaphore(3)

    async def _gen_one(city: str):
        async with sem:
            return await generate_city_knowledge(city, api_key)

    tasks = [_gen_one(c) for c in targets]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for city, result in zip(targets, results):
        if isinstance(result, Exception):
            logger.error(f"生成异常 [{city}]: {result}")
        else:
            all_chunks.extend(result)

    return all_chunks
