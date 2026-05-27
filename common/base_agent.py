import abc
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    """Agent 基类：统一接口，子类只需实现 _run_impl。"""

    def __init__(self, name: str = "BaseAgent", max_iterations: int = 15):
        self.name = name
        self.max_iterations = max_iterations
        self.history: List[Dict[str, Any]] = []

    def run(self, query: str) -> str:
        """公开入口：记录历史，调用子类实现。"""
        logger.info(f"[{self.name}] 收到任务: {query}")
        self.history.append({"role": "user", "content": query})
        result = self._run_impl(query)
        self.history.append({"role": "agent", "content": result})
        return result

    @abc.abstractmethod
    def _run_impl(self, query: str) -> str:
        """子类实现核心推理逻辑。"""
        ...

    def reset(self):
        """重置历史，用于新对话。"""
        self.history.clear()
