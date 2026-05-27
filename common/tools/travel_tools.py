"""
旅游助手工具集 — 全阶段共享。
阶段一: Agent 直接调用 — 阶段四: 替换为 RAG 检索 — 阶段五: 替换为 MCP 协议。
"""

import random
from datetime import datetime
from typing import Optional, List, Dict, Any

# ═══════════════════════════════════════════════════════
# 数据源 (阶段四/五替换为真实 API / RAG / MCP)
# ═══════════════════════════════════════════════════════

WEATHER_DB = {
    "三亚": {"晴": 32, "多云": 30, "阵雨": 28},
    "北京": {"晴": 25, "多云": 22, "阴": 18},
    "上海": {"小雨": 24, "多云": 26, "晴": 28},
    "成都": {"阴": 20, "小雨": 18, "多云": 22},
    "拉萨": {"晴": 18, "多云": 15, "阴": 12},
    "东京": {"晴": 26, "小雨": 22, "多云": 24},
    "曼谷": {"晴": 35, "多云": 33, "阵雨": 30},
}

ATTRACTIONS_DB: Dict[str, List[str]] = {
    "三亚": ["亚龙湾", "天涯海角", "南山寺", "蜈支洲岛", "三亚湾"],
    "北京": ["故宫", "长城", "颐和园", "天坛", "798艺术区", "南锣鼓巷"],
    "上海": ["外滩", "迪士尼", "豫园", "南京路", "田子坊"],
    "成都": ["大熊猫基地", "宽窄巷子", "锦里", "都江堰", "青城山"],
    "拉萨": ["布达拉宫", "大昭寺", "纳木错", "八廓街", "羊卓雍措"],
    "东京": ["浅草寺", "秋叶原", "涩谷", "新宿御苑"],
    "曼谷": ["大皇宫", "卧佛寺", "考山路", "水上市场"],
}

HOTELS_DB: List[Dict[str, Any]] = [
    {"name": "青年旅舍", "price": 60, "rating": 3.5, "location": "市中心"},
    {"name": "如家快捷", "price": 180, "rating": 3.8, "location": "交通枢纽"},
    {"name": "精品民宿", "price": 280, "rating": 4.5, "location": "景区附近"},
    {"name": "花园假日酒店", "price": 380, "rating": 4.3, "location": "商业区"},
    {"name": "海景国际大酒店", "price": 680, "rating": 4.7, "location": "海边"},
    {"name": "希尔顿度假村", "price": 1200, "rating": 4.9, "location": "度假区"},
]

ATTRACTION_COST: Dict[str, float] = {
    "故宫": 60, "长城": 40, "颐和园": 30, "天坛": 34,
    "大熊猫基地": 55, "迪士尼": 399, "南山寺": 129,
    "大皇宫": 120,
}
DEFAULT_ATTRACTION_COST = 50

CURRENCY_RATES = {
    "USD": 7.24, "EUR": 7.85, "JPY": 0.048, "THB": 0.20,
    "KRW": 0.0054, "GBP": 9.15, "CNY": 1.0,
}

# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════

def get_weather(city: str, date: Optional[str] = None) -> str:
    """查询指定城市的天气。"""
    if city not in WEATHER_DB:
        return f"暂无{city}的天气数据。已知城市: {', '.join(WEATHER_DB.keys())}"
    weather_type, temp = random.choice(list(WEATHER_DB[city].items()))
    date = date or datetime.now().strftime("%Y-%m-%d")
    tips = "适合出行！" if temp > 20 and "雨" not in weather_type else "建议带伞。"
    return f"{date} {city}天气: {weather_type}，温度 {temp}°C。{tips}"


def search_attractions(city: str, top_k: int = 3) -> str:
    """搜索城市热门景点。"""
    if city not in ATTRACTIONS_DB:
        return f"暂无{city}的景点数据。"
    spots = ATTRACTIONS_DB[city][:top_k]
    return f"{city}热门景点: " + "、".join(spots)


def search_hotels(city: str, budget_per_night: float = 500) -> str:
    """按预算搜索酒店。"""
    candidates = [h for h in HOTELS_DB if h["price"] <= budget_per_night]
    if not candidates:
        return f"在{city}未找到每晚 {budget_per_night} 元以下的酒店。"
    best = max(candidates, key=lambda h: h["rating"])
    return f"{city} 推荐 {best['name']}，每晚 ¥{best['price']}，评分 {best['rating']}/5.0"


def search_flights(origin: str, destination: str, date: Optional[str] = None) -> str:
    """搜索机票。"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    price = random.randint(500, 3000)
    airlines = ["国航", "东航", "南航", "海航", "春秋"]
    airline = random.choice(airlines)
    return f"{date} {origin} → {destination} | {airline} | ¥{price} | 约{random.randint(2,5)}小时"


def convert_currency(amount: float, from_currency: str, to_currency: str = "CNY") -> str:
    """货币换算。"""
    rate = CURRENCY_RATES.get(from_currency.upper())
    if rate is None:
        return f"不支持的货币类型: {from_currency}"
    return f"{amount} {from_currency.upper()} = {amount * rate:.2f} {to_currency.upper()}"


def split_bill(total: float, num_people: int) -> str:
    """账单 AA 拆分。"""
    if num_people <= 0:
        return "人数必须大于0"
    return f"总金额 ¥{total}，{num_people}人，每人 ¥{total / num_people:.2f}"


def check_visa(nationality: str, destination: str) -> str:
    """查询签证要求。"""
    visa_map = {
        ("中国", "泰国"): "免签，停留不超过30天",
        ("中国", "日本"): "需提前办理旅游签证",
        ("中国", "韩国"): "济州岛免签，其他地区需签证",
        ("美国", "中国"): "需办理旅游签证 (L签证)",
    }
    return visa_map.get((nationality, destination), f"请查询最新签证政策: {nationality} → {destination}")


# ═══════════════════════════════════════════════════════
# 工具注册清单 (供 ToolRegistry 使用)
# ═══════════════════════════════════════════════════════

TOOL_FUNCTIONS = [
    (get_weather, "get_weather", "查询指定城市的天气"),
    (search_attractions, "search_attractions", "搜索城市热门景点"),
    (search_hotels, "search_hotels", "按预算搜索酒店"),
    (search_flights, "search_flights", "搜索机票"),
    (convert_currency, "convert_currency", "货币换算"),
    (split_bill, "split_bill", "账单AA拆分"),
    (check_visa, "check_visa", "查询签证要求"),
]
