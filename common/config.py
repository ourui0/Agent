"""
API Key 配置管理

加载优先级: 环境变量 > config.py 默认值
可在 ~/.zshrc 或运行时 export 覆盖。

用法:
    from common.config import get_config
    cfg = get_config()
    print(cfg.amap_key)
"""

import os
from dataclasses import dataclass, field


@dataclass
class APIConfig:
    """集中管理所有外部 API Key。"""

    # 高德地图 (Web服务 API)
    amap_key: str = "0bfb0b5f4396f5b3683ad16838e913f4"
    amap_secret: str = "dc4d1f6195a4c2d3602f9dd32ba51848"  # JS API 安全密钥, REST 服务不需要

    # DeepSeek (已在 llm_client.py 中通过环境变量加载)
    # deepseek_key 由 DEEPSEEK_API_KEY 环境变量提供

    @classmethod
    def from_env(cls) -> "APIConfig":
        """从环境变量覆盖默认值。"""
        return cls(
            amap_key=os.getenv("AMAP_KEY", cls.amap_key),
            amap_secret=os.getenv("AMAP_SECRET", cls.amap_secret),
        )


# 全局单例
_config: APIConfig | None = None


def get_config() -> APIConfig:
    global _config
    if _config is None:
        _config = APIConfig.from_env()
    return _config


def reset_config():
    global _config
    _config = None
