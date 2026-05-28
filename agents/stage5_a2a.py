"""
阶段五：A2A 跨平台会话协议栈 + ANP 路由器

A2A (Agent-to-Agent) 协议:
  - 结构化消息模型 (sender_uri, receiver_uri, intent, payload, conversation_id)
  - 谈判 FSM: PROPOSE → COUNTER → ACCEPT/REJECT
  - 安全中间件: 反欺诈/金额拦截

ANP (Agent Network Protocol) 路由器:
  - URI 寻址: anp://domain/agent-path
  - EventBus 集成: 监听 outbound_negotiation 事件
  - WebSocket 传输: 跨平台 Agent 通信
"""

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# A2A 结构化消息模型
# ═══════════════════════════════════════════════════════════════

class NegotiationIntent(str, Enum):
    """A2A 谈判意图。"""
    PROPOSE = "propose"     # 我方提案
    COUNTER = "counter"     # 对方还价
    ACCEPT = "accept"       # 接受
    REJECT = "reject"       # 拒绝
    INQUIRY = "inquiry"     # 询价
    CONFIRM = "confirm"     # 确认成交


class NegotiationState(str, Enum):
    """谈判 FSM 状态。"""
    IDLE = "idle"
    PROPOSING = "proposing"       # 等待对方响应
    COUNTERING = "countering"     # 收到还价，我方决策中
    NEGOTIATING = "negotiating"   # 多轮协商中
    ACCEPTED = "accepted"         # 达成一致
    REJECTED = "rejected"         # 谈判破裂
    TIMEOUT = "timeout"           # 超时


@dataclass
class A2AMessage:
    """
    ANP 标准结构化消息。

    字段:
      sender_uri:    发送方 URI  (anp://travel-agent.local/planner)
      receiver_uri:  接收方 URI  (anp://ctrip.com/hotel-agent)
      intent:        消息意图 (propose/counter/accept/reject)
      payload:       业务载荷 (价格/酒店信息/折扣方案)
      conversation_id: 会话 ID (同一次谈判共享)
      timestamp:     时间戳 (ISO 8601)
    """
    sender_uri: str
    receiver_uri: str
    intent: NegotiationIntent
    payload: Dict[str, Any]
    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: str = field(default_factory=lambda: asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else "")

    def to_json(self) -> str:
        return json.dumps({
            "protocol": "ANP/1.0",
            "sender_uri": self.sender_uri,
            "receiver_uri": self.receiver_uri,
            "intent": self.intent.value,
            "payload": self.payload,
            "conversation_id": self.conversation_id,
            "timestamp": self.timestamp,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> "A2AMessage":
        d = json.loads(data) if isinstance(data, str) else data
        return cls(
            sender_uri=d["sender_uri"],
            receiver_uri=d["receiver_uri"],
            intent=NegotiationIntent(d["intent"]),
            payload=d.get("payload", {}),
            conversation_id=d.get("conversation_id", ""),
            timestamp=d.get("timestamp", ""),
        )


# ═══════════════════════════════════════════════════════════════
# 安全中间件
# ═══════════════════════════════════════════════════════════════

class A2ASecurityMiddleware:
    """
    A2A 安全中间件 — 拦截恶意消息。

    规则:
      1. 金额异常检测: 对方报价偏离市场价 > 50% → 拦截
      2. URI 白名单: 只与受信任的外部 Agent 通信
      3. 频率限制: 同一 conversation 的消息速率限制
    """

    TRUSTED_DOMAINS = [
        "ctrip.com",
        "meituan.com",
        "amap.com",
        "qunar.com",
        "fliggy.com",
    ]

    def __init__(self):
        self._msg_counts: Dict[str, int] = {}
        self._blocked: List[str] = []

    def validate(self, message: A2AMessage) -> Tuple[bool, str]:
        """
        验证消息安全性。
        返回 (is_safe, reason)。
        """
        # 1. URI 白名单
        domain = self._extract_domain(message.receiver_uri)
        if domain and domain not in self.TRUSTED_DOMAINS:
            return False, f"不受信任的域: {domain}"

        # 2. 金额异常检测
        price = message.payload.get("price", 0)
        market_price = message.payload.get("market_price", price)
        if market_price > 0 and price > 0:
            deviation = abs(price - market_price) / market_price
            if deviation > 0.5:
                return False, f"价格偏离市场价 {deviation:.0%}，疑似欺诈"

        # 3. 频率限制
        cid = message.conversation_id
        self._msg_counts[cid] = self._msg_counts.get(cid, 0) + 1
        if self._msg_counts[cid] > 20:
            return False, f"会话 {cid} 消息频率过高"

        return True, "ok"

    def block(self, message: A2AMessage, reason: str):
        """记录被拦截的消息。"""
        self._blocked.append(f"[{message.conversation_id}] {reason}")
        logger.warning(f"🛡️ A2A 安全拦截: {reason}")

    @staticmethod
    def _extract_domain(uri: str) -> Optional[str]:
        if "://" in uri:
            return uri.split("://")[1].split("/")[0]
        return None


# ═══════════════════════════════════════════════════════════════
# 谈判有限状态机 (Negotiation FSM)
# ═══════════════════════════════════════════════════════════════

class NegotiationFSM:
    """
    A2A 谈判有限状态机。

    生命周期:
      IDLE → PROPOSING → NEGOTIATING → ACCEPTED/REJECTED

    状态转换:
      propose()  → IDLE → PROPOSING
      counter()  → PROPOSING → NEGOTIATING
      accept()   → NEGOTIATING → ACCEPTED
      reject()   → NEGOTIATING → REJECTED
      timeout()  → any → TIMEOUT
    """

    def __init__(self, conversation_id: str, max_rounds: int = 5):
        self.conversation_id = conversation_id
        self.state = NegotiationState.IDLE
        self.max_rounds = max_rounds
        self.round = 0
        self.history: List[Dict[str, Any]] = []

    def propose(self, proposal: Dict[str, Any]) -> A2AMessage:
        """发起提案。"""
        self._guard_state(NegotiationState.IDLE, "只能从 IDLE 发起提案")
        self.state = NegotiationState.PROPOSING
        self.round = 1
        self.history.append({"round": 1, "action": "propose", "data": proposal})
        return self._build_msg(NegotiationIntent.PROPOSE, proposal)

    def counter(self, counter_offer: Dict[str, Any]) -> A2AMessage:
        """收到还价 → 进入协商状态。"""
        self.state = NegotiationState.NEGOTIATING
        self.round += 1
        if self.round > self.max_rounds:
            self.state = NegotiationState.TIMEOUT
            logger.warning(f"谈判 {self.conversation_id} 超时 ({self.max_rounds}轮)")
            return self._build_msg(NegotiationIntent.REJECT, {"reason": "max_rounds_exceeded"})
        self.history.append({"round": self.round, "action": "counter", "data": counter_offer})
        return self._build_msg(NegotiationIntent.COUNTER, counter_offer)

    def accept(self, final_terms: Dict[str, Any]) -> A2AMessage:
        """接受谈判结果。"""
        self.state = NegotiationState.ACCEPTED
        self.history.append({"round": self.round, "action": "accept", "data": final_terms})
        logger.info(f"✅ 谈判 {self.conversation_id} 达成一致: {final_terms}")
        return self._build_msg(NegotiationIntent.ACCEPT, final_terms)

    def reject(self, reason: str = "") -> A2AMessage:
        """拒绝谈判。"""
        self.state = NegotiationState.REJECTED
        self.history.append({"round": self.round, "action": "reject", "reason": reason})
        logger.info(f"❌ 谈判 {self.conversation_id} 破裂: {reason}")
        return self._build_msg(NegotiationIntent.REJECT, {"reason": reason})

    def _guard_state(self, expected: NegotiationState, msg: str):
        if self.state != expected:
            raise RuntimeError(f"{msg} (当前状态: {self.state})")

    def _build_msg(self, intent: NegotiationIntent, payload: dict) -> A2AMessage:
        return A2AMessage(
            sender_uri="anp://travel-agent.local/planner",
            receiver_uri="anp://ctrip.com/hotel-agent",
            intent=intent,
            payload={**payload, "round": self.round, "state": self.state.value},
            conversation_id=self.conversation_id,
        )


# ═══════════════════════════════════════════════════════════════
# ANP 路由器
# ═══════════════════════════════════════════════════════════════

class ANPRouteEntry:
    """ANP 路由表条目。"""
    def __init__(self, uri: str, transport: str, endpoint: str, agent_type: str):
        self.uri = uri
        self.transport = transport  # websocket / grpc / http
        self.endpoint = endpoint
        self.agent_type = agent_type


class AgentNetworkRouter:
    """
    ANP 路由器 — 基于 URI 的 Agent 寻址与消息路由。

    用法:
        router = AgentNetworkRouter()
        router.register("anp://ctrip.com/hotel-agent",
                        transport="http", endpoint="https://api.ctrip.com/agent")

        # EventBus 集成
        bus.subscribe("orchestrator:outbound_negotiation", router.on_negotiation_event)

        # 发送消息
        msg = A2AMessage(sender_uri="...", receiver_uri="anp://ctrip.com/hotel-agent", ...)
        response = await router.route(msg)
    """

    def __init__(self, bus=None):
        self._routes: Dict[str, ANPRouteEntry] = {}
        self.bus = bus

    def register(self, uri: str, transport: str = "http", endpoint: str = "", agent_type: str = "generic"):
        """注册一个外部 Agent 路由。"""
        self._routes[uri] = ANPRouteEntry(uri, transport, endpoint, agent_type)
        logger.info(f"🌐 ANP 路由注册: {uri} → {transport}://{endpoint}")

    def unregister(self, uri: str):
        self._routes.pop(uri, None)

    def resolve(self, uri: str) -> Optional[ANPRouteEntry]:
        """解析 URI 到路由条目。"""
        if uri in self._routes:
            return self._routes[uri]
        # 尝试前缀匹配
        for route_uri, entry in self._routes.items():
            if uri.startswith(route_uri):
                return entry
        return None

    async def route(self, message: A2AMessage) -> Optional[A2AMessage]:
        """
        路由一个 A2A 消息到目标 Agent。

        返回对方的响应消息，或 None (如果路由失败)。
        """
        entry = self.resolve(message.receiver_uri)
        if not entry:
            logger.warning(f"ANP 路由失败: 未找到 {message.receiver_uri}")
            return None

        logger.info(f"📡 ANP 路由: {message.sender_uri} → {message.receiver_uri} [{message.intent.value}]")

        if entry.transport == "http":
            return await self._send_http(entry, message)
        elif entry.transport == "mock":
            return await self._send_mock(entry, message)
        else:
            logger.error(f"不支持的传输: {entry.transport}")
            return None

    async def on_negotiation_event(self, event_type: str, data: Dict):
        """
        EventBus 回调: 拦截 outbound_negotiation 事件。
        自动路由到目标外部 Agent。
        """
        message = data.get("message")
        if not isinstance(message, A2AMessage):
            return

        logger.info(f"📡 EventBus → ANP: {message.intent.value}")
        response = await self.route(message)
        if response and self.bus:
            await self.bus.emit("anp:response_received", {
                "conversation_id": message.conversation_id,
                "response": response,
            })

    async def _send_http(self, entry: ANPRouteEntry, message: A2AMessage) -> Optional[A2AMessage]:
        """HTTP 传输 (实际项目中用 aiohttp/httpx)。"""
        # Mock HTTP 调用
        logger.info(f"  HTTP POST {entry.endpoint}")
        return self._mock_external_response(message)

    async def _send_mock(self, entry: ANPRouteEntry, message: A2AMessage) -> Optional[A2AMessage]:
        """Mock 传输 (直接返回模拟响应)。"""
        return self._mock_external_response(message)

    def _mock_external_response(self, message: A2AMessage) -> Optional[A2AMessage]:
        """模拟外部 Agent 响应。"""
        payload = message.payload

        if message.intent == NegotiationIntent.PROPOSE:
            # 外部 Agent 还价: 降价 10-20%
            original = payload.get("price", 1000)
            discount = 0.85
            counter_price = int(original * discount)
            return A2AMessage(
                sender_uri=message.receiver_uri,
                receiver_uri=message.sender_uri,
                intent=NegotiationIntent.COUNTER,
                payload={
                    "price": counter_price,
                    "original_price": original,
                    "discount": f"{1-discount:.0%}",
                    "agent": "携程特价Agent",
                    "offer_id": str(uuid.uuid4())[:8],
                },
                conversation_id=message.conversation_id,
            )

        if message.intent == NegotiationIntent.COUNTER:
            # 二次还价: 接受/拒绝
            price = payload.get("price", 0)
            if price > 100:
                return A2AMessage(
                    sender_uri=message.receiver_uri,
                    receiver_uri=message.sender_uri,
                    intent=NegotiationIntent.ACCEPT,
                    payload={"final_price": price, "status": "confirmed"},
                    conversation_id=message.conversation_id,
                )

        return None


# ═══════════════════════════════════════════════════════════════
# A2A 会话管理器
# ═══════════════════════════════════════════════════════════════

class A2ASessionManager:
    """
    A2A 会话管理器 — 管理多个并发的跨 Agent 谈判。

    用法:
        mgr = A2ASessionManager(router, security=security_middleware)

        # 发起谈判
        session_id = await mgr.start_negotiation(
            "anp://ctrip.com/hotel-agent",
            {"hotel": "希尔顿", "price": 1200, "budget": 800}
        )

        # 继续谈判
        result = await mgr.continue_negotiation(session_id)
    """

    def __init__(self, router: AgentNetworkRouter, security: Optional[A2ASecurityMiddleware] = None):
        self.router = router
        self.security = security or A2ASecurityMiddleware()
        self._sessions: Dict[str, NegotiationFSM] = {}
        self._pending_responses: Dict[str, asyncio.Queue] = {}

    async def start_negotiation(
        self,
        target_uri: str,
        proposal: Dict[str, Any],
        source_uri: str = "anp://travel-agent.local/planner",
    ) -> Dict[str, Any]:
        """
        发起一次 A2A 谈判。

        返回: {"status": "accepted"|"rejected"|"timeout", "terms": {...}, "history": [...]}
        """
        fsm = NegotiationFSM(str(uuid.uuid4())[:12])
        self._sessions[fsm.conversation_id] = fsm

        # 1. PROPOSE
        msg = fsm.propose(proposal)
        msg.sender_uri = source_uri
        msg.receiver_uri = target_uri

        if not self.security.validate(msg)[0]:
            return {"status": "rejected", "reason": "安全拦截"}

        response = await self.router.route(msg)
        if not response:
            fsm.reject("无响应")
            return {"status": "timeout", "reason": "目标 Agent 无响应"}

        # 2. 处理 COUNTER
        if response.intent == NegotiationIntent.COUNTER:
            fsm.counter(response.payload)

            # 我方决策: 价格是否在预算内
            budget = proposal.get("budget", float("inf"))
            counter_price = response.payload.get("price", float("inf"))

            if counter_price <= budget:
                # 可以接受 → 再还一轮争取更好价格
                newer_offer = {"price": int(counter_price * 0.95), "message": "再便宜5%就成交"}
                msg2 = fsm.counter(newer_offer)
                msg2.sender_uri = source_uri
                msg2.receiver_uri = target_uri

                resp2 = await self.router.route(msg2)
                if resp2 and resp2.intent == NegotiationIntent.ACCEPT:
                    final = fsm.accept(resp2.payload)
                    return {
                        "status": "accepted",
                        "terms": resp2.payload,
                        "history": fsm.history,
                        "rounds": fsm.round,
                    }

            # 拒绝
            fsm.reject(f"价格 {counter_price} 超出预算 {budget}")
            return {"status": "rejected", "reason": "超出预算", "history": fsm.history}

        if response.intent == NegotiationIntent.ACCEPT:
            fsm.accept(response.payload)
            return {"status": "accepted", "terms": response.payload, "history": fsm.history}

        fsm.reject("意外响应")
        return {"status": "rejected", "reason": "unexpected_response"}

    def get_session(self, conversation_id: str) -> Optional[NegotiationFSM]:
        return self._sessions.get(conversation_id)


# ═══════════════════════════════════════════════════════════════
# 阶段五演示入口
# ═══════════════════════════════════════════════════════════════

async def demo_stage5():
    """阶段五独立演示: MCP + A2A 完整流程。"""
    from agents.stage5_mcp import MCPClientBridge, MockTransport, MCPToolAdapter
    from common import ToolRegistry

    print("=" * 60)
    print("  🌐 阶段五: MCP + A2A + ANP 协议栈演示")
    print("=" * 60)

    # ── Part 1: MCP ──
    print("\n── MCP 协议 ──")
    bridge = MCPClientBridge(transport=MockTransport("amap+fs"))
    await bridge.connect()
    await bridge.initialize()

    tools = await bridge.list_tools()
    print(f"  发现 {len(tools)} 个工具:")
    for t in tools:
        print(f"    🔧 {t['name']}: {t['description'][:50]}")

    resources = await bridge.list_resources()
    print(f"  发现 {len(resources)} 个资源:")
    for r in resources:
        print(f"    📁 {r['uri']}")

    result = await bridge.call_tool("amap_search_poi", {
        "keywords": "火锅", "city": "成都", "types": "餐饮"
    })
    print(f"  工具调用结果: {result['content'][0]['text'][:80]}...")

    # 注册到 ToolRegistry
    registry = ToolRegistry()
    adapter = MCPToolAdapter(bridge)
    count = await adapter.register_all(registry)
    print(f"  已注册 {count} 个 MCP 工具到 ToolRegistry")

    # ── Part 2: A2A ──
    print("\n── A2A 谈判协议 ──")
    router = AgentNetworkRouter()
    router.register("anp://ctrip.com/hotel-agent", transport="mock")
    router.register("anp://meituan.com/discount-agent", transport="mock")
    router.register("anp://fliggy.com/flight-agent", transport="mock")

    security = A2ASecurityMiddleware()
    session_mgr = A2ASessionManager(router, security)

    # 场景: 酒店超预算，向携程特价Agent申请折扣
    result = await session_mgr.start_negotiation(
        target_uri="anp://ctrip.com/hotel-agent",
        proposal={
            "hotel": "希尔顿度假村",
            "price": 1200,
            "budget": 800,
            "check_in": "2026-06-01",
            "nights": 3,
        },
    )

    print(f"  谈判结果: {result['status']}")
    print(f"  条款: {result.get('terms', {})}")
    print(f"  轮次: {result.get('rounds', 0)}")
    for h in result.get("history", []):
        print(f"    Round {h['round']}: {h['action']}")

    await bridge.close()
    print("\n✅ 阶段五演示完成!\n")
