"""
TravelAgent Framework V3.0 — 自研 Agent 编排底座。
纯 Python 实现，零第三方 Agent 框架依赖 (仅 openai + pydantic)。

组件:
  1. @tool 装饰器    — 一键注册函数为 LLM 可调用工具
  2. BaseAgent       — 单步决策 (Reasoning & Acting)
  3. EventBus        — 异步发布/订阅
  4. Middleware      — 洋葱模型拦截链
  5. Orchestrator    — 状态机编排器 (节点流 + 条件回溯)
"""

import asyncio
import inspect
import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, get_type_hints

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 1. @tool 装饰器
# ═══════════════════════════════════════════════════════════════

class ToolMetadata(BaseModel):
    """工具元数据 — 从函数签名自动提取。"""
    name: str
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    func: Optional[Callable] = None

    class Config:
        arbitrary_types_allowed = True


# Python type → JSON Schema type 映射
_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


def tool(name: Optional[str] = None, description: Optional[str] = None):
    """
    装饰器：将普通函数一键注册为 Agent 可调用的工具。
    自动提取函数名、docstring、参数类型注解，生成 OpenAI function-calling Schema。

    用法:
        @tool(description="查询城市天气")
        def get_weather(city: str, date: str = "today") -> str: ...
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").strip().split("\n")[0]

        hints = get_type_hints(func) if hasattr(func, '__annotations__') else {}
        sig = inspect.signature(func)

        properties = {}
        required = []
        for param_name, param in sig.parameters.items():
            param_type = hints.get(param_name, str)
            json_type = _TYPE_MAP.get(param_type, "string")

            param_desc = ""
            if func.__doc__:
                for line in func.__doc__.split("\n"):
                    line = line.strip()
                    if line.startswith(f"{param_name}:"):
                        param_desc = line.split(":", 1)[1].strip()
                        break

            properties[param_name] = {
                "type": json_type,
                "description": param_desc or f"参数 {param_name}",
            }
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_desc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

        func.__tool_meta__ = ToolMetadata(
            name=tool_name,
            description=tool_desc,
            parameters=schema,
            func=func,
        )
        return func

    # 允许 @tool 或 @tool(name="...") 两种用法
    if callable(name):
        f, name = name, None
        return decorator(f)
    return decorator


# ═══════════════════════════════════════════════════════════════
# 2. BaseAgent — 单步决策 (Reasoning & Acting)
# ═══════════════════════════════════════════════════════════════

class BaseAgent:
    """
    自研 Agent 基类。持有 LLM 客户端和工具集，通过 __call__ 执行单步推理。

    用法:
        agent = BaseAgent(
            name="酒店专家",
            system_prompt="你是酒店推荐专家...",
            tools=[search_hotels, compare_prices],
        )
        update = await agent(state)
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: Optional[List[Callable]] = None,
        temperature: float = 0.3,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.temperature = temperature

        # 注册工具
        self._tools: Dict[str, ToolMetadata] = {}
        self._tool_schemas: List[Dict] = []
        if tools:
            for t in tools:
                meta = getattr(t, '__tool_meta__', None)
                if meta:
                    self._tools[meta.name] = meta
                    self._tool_schemas.append(meta.parameters)

    async def __call__(self, state: dict, max_turns: int = 5) -> dict:
        """
        ReAct 式多轮推理: 调 LLM → 执行工具 → 观察 → 再调 LLM → ... → 最终答案。
        最多 max_turns 轮，防止死循环。
        """
        from common.llm_client import LLMClient
        llm = LLMClient.get()

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_user_message(state)},
        ]

        tool_defs = None
        if self._tool_schemas:
            tool_defs = [
                {"type": "function", "function": s["function"]}
                for s in self._tool_schemas
            ]

        for turn in range(1, max_turns + 1):
            try:
                if tool_defs and not llm.mock_mode and llm.client:
                    resp = llm.client.chat.completions.create(
                        model=llm.model, messages=messages,
                        tools=tool_defs, temperature=self.temperature,
                    )
                    msg = resp.choices[0].message

                    # ── 工具调用 ──
                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_name = tc.function.name
                            tool_args = json.loads(tc.function.arguments)
                            tool_meta = self._tools.get(tool_name)
                            if tool_meta and tool_meta.func:
                                result = str(tool_meta.func(**tool_args))
                                logger.info(f"  [{self.name}] 🔧 {tool_name}({tool_args}) → {result[:60]}")
                                # 将 assistant 的 tool_call 和 tool 结果追加回消息
                                messages.append({
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [{
                                        "id": tc.id, "type": "function",
                                        "function": {"name": tool_name, "arguments": tc.function.arguments},
                                    }],
                                })
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": result,
                                })
                        continue  # 继续下一轮

                    # ── 文本回复 (最终答案) ──
                    content = msg.content or ""
                    return self._parse_response(content, state)

                else:
                    # Mock 模式 / 无工具 — 直接 chat
                    if tool_defs:
                        td_text = "\n".join(
                            f"- {td['function']['name']}: {td['function']['description']}"
                            for td in tool_defs
                        )
                        messages[0]["content"] += (
                            f"\n\n可用工具:\n{td_text}\n"
                            '工具调用格式: {"tool":"工具名","args":{...}}\n'
                            '最终答案格式: {"answer":"...", ...}\n'
                            '如果不需要工具，直接返回最终 JSON 答案。'
                        )
                    raw = llm.chat(messages, self.temperature)
                    return self._parse_response(raw, state)

            except Exception as e:
                logger.error(f"[{self.name}] 第{turn}轮失败: {e}")
                if turn == max_turns:
                    return {"error": str(e)}
                continue

        return {"error": f"超过最大轮次 {max_turns}"}

    def _build_user_message(self, state: dict) -> str:
        """子类重写：将 state 转为 LLM 可读的 prompt。"""
        return json.dumps(state, ensure_ascii=False, indent=2)

    def _format_tool_result(self, tool_name: str, args: dict, result: Any) -> dict:
        """格式化工具调用结果为状态更新。"""
        return {
            f"_tool_{tool_name}": str(result),
            f"_tool_{tool_name}_args": args,
        }

    def _parse_response(self, raw: str, state: dict) -> dict:
        """
        解析 LLM 回复为状态增量。
        子类可重写以实现自定义解析。
        """
        # 尝试 JSON
        try:
            import re
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            return json.loads(raw.strip())
        except (json.JSONDecodeError, AttributeError):
            pass

        # 尝试 tool_call 格式
        try:
            import re
            m = re.search(r'"tool"\s*:\s*"(\w+)"', raw)
            if m:
                tool_name = m.group(1)
                args_match = re.search(r'"args"\s*:\s*(\{.*?\})', raw, re.DOTALL)
                args = json.loads(args_match.group(1)) if args_match else {}
                tool_meta = self._tools.get(tool_name)
                if tool_meta and tool_meta.func:
                    result = tool_meta.func(**args)
                    return {f"_tool_{tool_name}": str(result)}

            m = re.search(r'"answer"\s*:\s*"(.+?)"', raw)
            if m:
                return {"final_answer": m.group(1)}
        except Exception:
            pass

        return {"response": raw.strip()}


# ═══════════════════════════════════════════════════════════════
# 3. EventBus — 异步发布/订阅
# ═══════════════════════════════════════════════════════════════

class EventBus:
    """
    异步发布/订阅总线。
    - subscribe(event_type, callback): 注册监听器
    - async emit(event_type, data):     异步广播到所有监听器

    用法:
        bus = EventBus()
        bus.subscribe("agent:step", log_listener)
        await bus.emit("agent:step", {"agent": "hotel", "action": "推荐酒店"})
    """

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable):
        """注册一个事件监听器。"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug(f"EventBus: {event_type} ← {callback.__name__}")

    def unsubscribe(self, event_type: str, callback: Callable):
        """取消注册。"""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb != callback
            ]

    async def emit(self, event_type: str, data: Dict[str, Any]):
        """
        异步广播事件到所有订阅者。
        所有回调并发执行，单个失败不影响其他。
        """
        callbacks = self._subscribers.get(event_type, [])
        if not callbacks:
            return

        logger.debug(f"EventBus: emit '{event_type}' → {len(callbacks)} 个监听器")

        async def safe_call(cb: Callable):
            try:
                if inspect.iscoroutinefunction(cb):
                    await cb(event_type, data)
                else:
                    cb(event_type, data)
            except Exception as e:
                logger.error(f"EventBus 回调 {cb.__name__} 失败: {e}")

        await asyncio.gather(*[safe_call(cb) for cb in callbacks])


# ═══════════════════════════════════════════════════════════════
# 4. Middleware — 洋葱模型拦截链
# ═══════════════════════════════════════════════════════════════

class Middleware(ABC):
    """
    中间件基类 — 洋葱模型。
    子类实现 __call__，在 next_call 前后插入逻辑。

    用法:
        class LoggingMiddleware(Middleware):
            async def __call__(self, state, next_call):
                print("→ 进入")
                result = await next_call(state)
                print("← 离开")
                return result
    """

    @abstractmethod
    async def __call__(self, state: dict, next_call: Callable) -> dict:
        ...


class TokenCounterMiddleware(Middleware):
    """统计每次 Agent 调用的估计 token 消耗。"""

    def __init__(self):
        self.total_tokens = 0

    async def __call__(self, state: dict, next_call: Callable) -> dict:
        # 进入: 估算输入 token
        input_chars = len(json.dumps(state, ensure_ascii=False))
        input_tokens = input_chars // 4

        result = await next_call(state)

        # 离开: 估算输出 token
        output_chars = len(json.dumps(result, ensure_ascii=False))
        output_tokens = output_chars // 4

        self.total_tokens += input_tokens + output_tokens
        logger.info(f"  📊 Tokens: in≈{input_tokens} out≈{output_tokens} total≈{self.total_tokens}")
        return result


class SafetyFilterMiddleware(Middleware):
    """安全过滤：拦截包含敏感词的输入。"""

    BLOCKED_WORDS = ["hack", "exploit", "bypass", "illegal"]

    async def __call__(self, state: dict, next_call: Callable) -> dict:
        query = state.get("user_query", "")
        for word in self.BLOCKED_WORDS:
            if word.lower() in query.lower():
                logger.warning(f"🛑 SafetyFilter 拦截: 包含敏感词 '{word}'")
                return {"error": f"输入包含不允许的内容: {word}", "blocked": True}
        return await next_call(state)


class MiddlewarePipeline:
    """
    中间件管道 — 将多个中间件链式组合为洋葱模型。

    执行顺序:
      输入 → M1.before → M2.before → Agent.__call__ → M2.after → M1.after → 输出

    用法:
        pipeline = MiddlewarePipeline(
            [TokenCounterMiddleware(), SafetyFilterMiddleware()],
            final_handler=agent,
        )
        result = await pipeline(state)
    """

    def __init__(self, middlewares: List[Middleware], final_handler: Callable):
        self.middlewares = middlewares
        self.final_handler = final_handler

    async def __call__(self, state: dict) -> dict:
        """递归构建洋葱调用链。"""
        handler = self.final_handler
        for mw in reversed(self.middlewares):
            outer = mw

            async def make_chain(outer_mw, inner_handler):
                async def wrapper(s):
                    return await outer_mw(s, inner_handler)
                return wrapper

            handler = await self._wrap(outer, handler)
        return await handler(state)

    @staticmethod
    async def _wrap(mw: Middleware, inner: Callable) -> Callable:
        """闭包：将中间件包裹在内部处理器外。"""
        async def wrapped(state: dict) -> dict:
            return await mw(state, inner)
        return wrapped


# ═══════════════════════════════════════════════════════════════
# 5. Orchestrator — 状态机编排器
# ═══════════════════════════════════════════════════════════════

class Orchestrator:
    """
    自研编排器 — 替代 LangGraph 的 StateGraph。
    功能：节点注册 → 顺序/条件路由 → 回溯循环 → 状态持久化。

    用法:
        orch = Orchestrator(bus=event_bus, max_backtracks=3)

        orch.add_node("parse", parse_agent, pipeline=pipeline1)
        orch.add_node("guide", guide_agent, pipeline=pipeline2)
        orch.add_node("hotel", hotel_agent)
        orch.add_node("finance", finance_agent)

        # 条件路由：finance 超支 → 回到 hotel
        def route_after_finance(state):
            if state.get("budget_status") == "over_budget":
                return "hotel", True  # (目标节点, 是否为回溯)
            return None, False

        orch.set_route("finance", route_after_finance)

        final_state = await orch.run(initial_state)
    """

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        max_backtracks: int = 3,
    ):
        self.bus = bus or EventBus()
        self.max_backtracks = max_backtracks

        # 节点注册表
        self._nodes: Dict[str, BaseAgent] = {}
        self._pipelines: Dict[str, Optional[MiddlewarePipeline]] = {}
        self._order: List[str] = []  # 节点执行顺序

        # 条件路由: {node_name: Callable[[state], (next_node, is_backtrack)]}
        self._routes: Dict[str, Callable] = {}

        # 运行状态
        self._state: Dict[str, Any] = {}
        self._backtrack_count: Dict[str, int] = {}

    def add_node(
        self,
        name: str,
        agent: BaseAgent,
        pipeline: Optional[MiddlewarePipeline] = None,
    ):
        """注册一个节点。"""
        self._nodes[name] = agent
        self._pipelines[name] = pipeline
        self._order.append(name)
        self._backtrack_count[name] = 0
        logger.info(f"Orchestrator: +节点 '{name}' ({agent.name})")

    def set_route(
        self,
        node_name: str,
        route_fn: Callable[[dict], Tuple[Optional[str], bool]],
    ):
        """
        设置条件路由。
        route_fn(state) → (next_node_name, is_backtrack)
        - next_node_name: 下一个节点名，返回 None 表示用默认顺序
        - is_backtrack: True 表示这是回退操作（计入回溯计数）
        """
        self._routes[node_name] = route_fn

    async def run(self, initial_state: dict) -> dict:
        """
        执行编排循环。
        按顺序激活节点，支持条件路由和回溯限制。
        每次节点执行后通过 EventBus 广播状态变更。
        """
        self._state = dict(initial_state)
        self._state["_backtrack_count"] = 0
        self._state["_node_order"] = list(self._order)
        self._state["_current_node"] = ""

        pos = 0
        while pos < len(self._order):
            node_name = self._order[pos]
            agent = self._nodes[node_name]
            pipeline = self._pipelines.get(node_name)

            logger.info(f"▶ Orchestrator: [{node_name}] {agent.name}")
            self._state["_current_node"] = node_name

            # 执行节点 (通过中间件管道)
            try:
                if pipeline:
                    # 确保 pipeline 的 final_handler 指向当前 agent
                    if not pipeline.final_handler:
                        pipeline.final_handler = agent
                    update = await pipeline(self._state)
                else:
                    update = await agent(self._state)
            except Exception as e:
                logger.error(f"节点 '{node_name}' 异常: {e}")
                update = {"error": str(e)}

            # 合并状态
            self._state.update(update)

            # 广播事件
            await self.bus.emit("node:complete", {
                "node": node_name,
                "agent": agent.name,
                "update": update,
                "state_snapshot": self._sanitize_state(),
            })

            # 检查条件路由
            route_fn = self._routes.get(node_name)
            if route_fn:
                next_node, is_backtrack = route_fn(self._state)

                if next_node and is_backtrack:
                    # 回溯
                    bt_count = self._backtrack_count.get(node_name, 0) + 1
                    self._backtrack_count[node_name] = bt_count
                    self._state["_backtrack_count"] = bt_count

                    if bt_count >= self.max_backtracks:
                        logger.warning(
                            f"⛔ Orchestrator: 回溯达上限 ({bt_count}/{self.max_backtracks})，强制前进"
                        )
                        pos += 1
                    else:
                        logger.warning(
                            f"↩ Orchestrator: 回溯到 '{next_node}' ({bt_count}/{self.max_backtracks})"
                        )
                        await self.bus.emit("orchestrator:backtrack", {
                            "from": node_name,
                            "to": next_node,
                            "count": bt_count,
                            "max": self.max_backtracks,
                        })
                        # 跳转到目标节点
                        if next_node in self._order:
                            pos = self._order.index(next_node)
                            continue

                elif next_node and not is_backtrack:
                    # 跳转到指定节点（非回溯）
                    if next_node in self._order:
                        pos = self._order.index(next_node)
                        continue

            # 默认：前进到下一个节点
            pos += 1

        logger.info("✅ Orchestrator: 编排完成")
        self._state["_current_node"] = "__done__"
        await self.bus.emit("orchestrator:complete", {
            "state_snapshot": self._sanitize_state(),
        })
        return self._state

    def _sanitize_state(self) -> dict:
        """过滤内部字段，返回干净的状态快照。"""
        return {
            k: v for k, v in self._state.items()
            if not k.startswith("_")
        }


# ═══════════════════════════════════════════════════════════════
# 辅助：将普通函数转为异步兼容的 BaseAgent 节点
# ═══════════════════════════════════════════════════════════════

class FunctionalAgent(BaseAgent):
    """
    函数式 Agent：将纯函数包装为 BaseAgent 节点。
    适用于不需要 LLM 的确定性节点（如 parse、计算）。
    """

    def __init__(self, name: str, func: Callable[[dict], dict]):
        super().__init__(name=name, system_prompt="")
        self._func = func

    async def __call__(self, state: dict) -> dict:
        result = self._func(state)
        if inspect.iscoroutine(result):
            result = await result
        return result
# ═══════════════════════════════════════════════════════════════
# 补充：Orchestrator 的同步运行入口 (兼容客户端只需 async run)
# ═══════════════════════════════════════════════════════════════

    async def run_node(self, node_name: str) -> dict:
        """
        执行单个节点。自动选择 pipeline 或直接调用 agent。
        """
        agent = self._nodes[node_name]
        pipeline = self._pipelines.get(node_name)

        if pipeline and hasattr(pipeline, 'final_handler'):
            # pipeline 已包装 agent
            pass
        elif pipeline:
            # pipeline 需要注入 final_handler
            pipeline.final_handler = agent

        if pipeline and pipeline.final_handler:
            return await pipeline(self._state)
        else:
            result = await agent(self._state)
            return result

# 修复 Orchestrator.run 内部的节点执行逻辑
# (用 run_node 替换内联的 pipeline/agent 调用)
