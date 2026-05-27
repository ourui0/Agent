import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册器：管理 Agent 可调用的函数。"""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(self, func: Callable, name: Optional[str] = None,
                 description: Optional[str] = None):
        """注册一个工具函数。"""
        tool_name = name or func.__name__
        sig = inspect.signature(func)
        params = {
            k: str(v.annotation) if v.annotation != inspect.Parameter.empty else "any"
            for k, v in sig.parameters.items()
        }
        self._tools[tool_name] = {
            "func": func,
            "description": description or func.__doc__ or "",
            "parameters": params,
        }
        logger.debug(f"注册工具: {tool_name}")
        return func

    def get(self, name: str) -> Optional[Callable]:
        """获取工具函数。"""
        entry = self._tools.get(name)
        return entry["func"] if entry else None

    def call(self, name: str, **kwargs) -> str:
        """调用工具并返回字符串结果。"""
        func = self.get(name)
        if func is None:
            return f"错误: 未知工具 '{name}'"
        try:
            result = func(**kwargs)
            return str(result)
        except Exception as e:
            return f"工具 '{name}' 执行失败: {e}"

    def list_tools(self) -> str:
        """生成工具列表的描述文本 (用于注入 prompt)。"""
        lines = []
        for name, entry in self._tools.items():
            params_str = ", ".join(
                f"{k}: {v}" for k, v in entry["parameters"].items()
            )
            lines.append(f"- {name}({params_str}): {entry['description']}")
        return "\n".join(lines) if lines else "(无可用工具)"

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())
