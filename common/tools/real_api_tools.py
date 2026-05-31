"""
真实外部 API 工具集

对接:
  - 高德地图 Web 服务 API (POI搜索 / 地理编码 / 天气 / 路径规划)

所有函数均为 async，返回结构化 dict，可直接注册为 MCP 工具。
"""

import asyncio
import json
import logging
from typing import Any

import aiohttp

from common.config import get_config

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 高德地图 API
# ═══════════════════════════════════════════════════════════════

AMAP_BASE = "https://restapi.amap.com/v3"


async def _amap_get(path: str, params: dict) -> dict:
    """高德地图 GET 请求。"""
    cfg = get_config()
    params["key"] = cfg.amap_key
    url = f"{AMAP_BASE}{path}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            if data.get("status") != "1":
                info = data.get('info', 'unknown')
                if 'USERKEY_PLAT_NOMATCH' in str(info):
                    logger.warning(f"高德API Key类型错误: 需要'Web服务'类型Key, 当前为'Web端(JS API)'类型 | 去 console.amap.com 修改Key类型")
                else:
                    logger.warning(f"高德API错误: {info} | {path}")
            return data


async def amap_search_poi(
    keywords: str,
    city: str = "",
    types: str = "",
    offset: int = 10,
    page: int = 1,
) -> dict:
    """
    高德地图 POI 搜索 — 查找酒店/餐厅/景点/医院等。

    参数:
        keywords: 搜索关键词 (如 "火锅", "五星级酒店", "故宫")
        city: 城市名或城市编码 (如 "成都", "010")
        types: POI分类 (如 "餐饮", "住宿", "风景名胜", "医疗")
        offset: 每页条数 (默认10)
        page: 页码 (默认1)

    返回: {"status": "1"/"0", "pois": [...], "count": int}
    """
    params = {"keywords": keywords, "offset": offset, "page": page}
    if city:
        params["city"] = city
    if types:
        params["types"] = types

    data = await _amap_get("/place/text", params)
    pois = data.get("pois", [])

    # 精简字段
    result = {
        "status": data.get("status", "0"),
        "count": int(data.get("count", 0)),
        "pois": [
            {
                "name": p.get("name"),
                "address": p.get("address"),
                "location": p.get("location"),
                "type": p.get("type"),
                "rating": p.get("biz_ext", {}).get("rating", "N/A"),
                "cost": p.get("biz_ext", {}).get("cost", "N/A"),
                "tel": p.get("tel", "N/A"),
            }
            for p in pois
        ],
    }
    logger.info(f"高德POI: '{keywords}' @{city} → {result['count']} 条")
    return result


async def amap_geocode(address: str, city: str = "") -> dict:
    """
    高德地理编码 — 地址 → 经纬度坐标。

    参数:
        address: 地址字符串 (如 "北京市朝阳区阜通东大街6号")
        city: 城市 (可选，提高准确率)

    返回: {"status": "1"/"0", "location": "116.xxx,39.xxx", "formatted_address": "..."}
    """
    params = {"address": address}
    if city:
        params["city"] = city
    data = await _amap_get("/geocode/geo", params)
    geos = data.get("geocodes", [])
    if geos:
        g = geos[0]
        return {
            "status": "1",
            "location": g.get("location"),
            "formatted_address": g.get("formatted_address"),
            "city": g.get("city"),
            "district": g.get("district"),
        }
    return {"status": "0", "location": "", "formatted_address": ""}


async def amap_weather(city: str, extensions: str = "base") -> dict:
    """
    高德天气查询 — 实时天气 / 预报。

    参数:
        city: 城市名或城市编码 (如 "成都", "510100")
        extensions: "base"=实时天气, "all"=未来4天预报

    返回: {"status": "1"/"0", "lives": [...] / "forecasts": [...]}
    """
    data = await _amap_get("/weather/weatherInfo", {"city": city, "extensions": extensions})
    if extensions == "base":
        lives = data.get("lives", [])
        return {"status": data.get("status", "0"), "lives": lives}
    else:
        forecasts = data.get("forecasts", [])
        return {"status": data.get("status", "0"), "forecasts": forecasts}


async def amap_direction(
    origin: str,
    destination: str,
    city: str = "",
    strategy: int = 0,
) -> dict:
    """
    高德路径规划 — 驾车路线 (距离/时间/费用)。

    参数:
        origin: 起点坐标 "116.43,39.92" 或地址
        destination: 终点坐标或地址
        city: 城市 (可选)
        strategy: 0=速度优先, 1=费用优先, 2=距离优先

    返回: {"status": "1"/"0", "distance": "xxx米", "duration": "xxx秒", "taxi_cost": "..."}
    """
    # 驾车API更稳定，不需要city参数
    params = {"origin": origin, "destination": destination, "strategy": strategy,
              "extensions": "base"}
    data = await _amap_get("/direction/driving", params)
    route = data.get("route", {})
    paths = route.get("paths", [{}])
    path = paths[0] if paths else {}
    return {
        "status": data.get("status", "0"),
        "distance": path.get("distance", "N/A"),
        "duration": path.get("duration", "N/A"),
        "taxi_cost": route.get("taxi_cost", "N/A"),
    }


# ═══════════════════════════════════════════════════════════════

# 工具注册表 (供 MCP tools/list 使用)
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# 工具注册表 (供 MCP tools/list 使用)
# ═══════════════════════════════════════════════════════════════

REAL_TOOLS_SCHEMA = [
    {
        "name": "amap_search_poi",
        "description": "高德地图POI搜索: 实时查找周边酒店/餐厅/景点/医院/商场。支持关键词+城市+分类精确搜索。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "搜索关键词"},
                "city": {"type": "string", "description": "城市名或城市编码"},
                "types": {"type": "string", "description": "POI分类: 餐饮/住宿/风景名胜/购物/医疗"},
                "offset": {"type": "integer", "default": 10, "description": "每页条数"},
                "page": {"type": "integer", "default": 1, "description": "页码"},
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "amap_geocode",
        "description": "高德地理编码: 地址→经纬度坐标，用于定位和路径规划。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "地址字符串"},
                "city": {"type": "string", "description": "城市(可选)"},
            },
            "required": ["address"],
        },
    },
    {
        "name": "amap_weather",
        "description": "高德天气查询: 实时天气或未来4天预报。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名"},
                "extensions": {"type": "string", "enum": ["base", "all"], "default": "base", "description": "base=实时, all=预报"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "amap_direction",
        "description": "高德路径规划: 计算两点间驾车路线、距离和时间。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "起点地址或坐标"},
                "destination": {"type": "string", "description": "终点地址或坐标"},
                "strategy": {"type": "integer", "default": 0, "description": "0=速度优先, 1=费用优先, 2=距离优先"},
            },
            "required": ["origin", "destination"],
        },
    },
]

# 工具名 → 异步处理函数
REAL_TOOL_HANDLERS = {
    "amap_search_poi": amap_search_poi,
    "amap_geocode": amap_geocode,
    "amap_weather": amap_weather,
    "amap_direction": amap_direction,
}
