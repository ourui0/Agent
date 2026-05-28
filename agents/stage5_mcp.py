"""
阶段五：MCP (Model Context Protocol) Client 桥接器

基于 JSON-RPC 2.0 标准:
- tools/list → 动态发现外部 MCP Server 的工具
- resources/list → 动态发现外部数据资源
- tools/call → 代理执行外部工具，结果合并到 TravelState

传输层: stdio / HTTP / WebSocket (可插拔)
"""

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# JSON-RPC 2.0 报文模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class JSONRPCRequest:
    """JSON-RPC 2.0 请求。"""
    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    jsonrpc: str = "2.0"
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class JSONRPCResponse:
    """JSON-RPC 2.0 响应。"""
    id: str
    result: Any = None
    error: Optional[Dict[str, Any]] = None
    jsonrpc: str = "2.0"

    @property
    def ok(self) -> bool:
        return self.error is None


# ═══════════════════════════════════════════════════════════════
# 传输层抽象
# ═══════════════════════════════════════════════════════════════

class MCPTransport(ABC):
    """MCP 传输层抽象基类。"""

    @abstractmethod
    async def connect(self): ...

    @abstractmethod
    async def send(self, message: bytes): ...

    @abstractmethod
    async def receive(self) -> bytes: ...

    @abstractmethod
    async def close(self): ...


class StdioTransport(MCPTransport):
    """stdio 传输: 通过子进程 stdin/stdout 通信。"""

    def __init__(self, command: List[str]):
        self.command = command
        self._process: Optional[asyncio.subprocess.Process] = None

    async def connect(self):
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info(f"MCP stdio 已连接: {' '.join(self.command)}")

    async def send(self, message: bytes):
        if self._process and self._process.stdin:
            self._process.stdin.write(message + b"\n")
            await self._process.stdin.drain()

    async def receive(self) -> bytes:
        if self._process and self._process.stdout:
            line = await self._process.stdout.readline()
            return line.strip()
        return b""

    async def close(self):
        if self._process:
            self._process.terminate()
            await self._process.wait()


class HTTPTransport(MCPTransport):
    """HTTP 传输: 通过 HTTP POST 通信 (用于远端 MCP Server)。"""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    async def connect(self):
        logger.info(f"MCP HTTP 端点: {self.endpoint}")

    async def send(self, message: bytes) -> bytes:
        import urllib.request
        req = urllib.request.Request(
            self.endpoint,
            data=message,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, urllib.request.urlopen, req)
        return resp.read()

    async def receive(self) -> bytes:
        return b""  # HTTP 是请求-响应模式

    async def close(self): pass


class MockTransport(MCPTransport):
    """Mock 传输: 用于本地测试和演示。"""

    def __init__(self, server_name: str = "mock-server"):
        self.server_name = server_name
        self._pending: List[bytes] = []

    async def connect(self):
        logger.info(f"MCP Mock 传输就绪: {self.server_name}")

    async def send(self, message: bytes):
        self._pending.append(message)

    async def receive(self) -> bytes:
        if self._pending:
            req_data = json.loads(self._pending.pop(0))
            return json.dumps(self._mock_handle(req_data)).encode()
        return b""

    async def close(self): pass

    def _mock_handle(self, request: dict) -> dict:
        """Mock 服务端响应。"""
        method = request.get("method", "")
        rid = request.get("id", "")

        # Handle initialize
        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": self.server_name, "version": "1.0.0"},
                    "capabilities": {"tools": {}, "resources": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "tools": [
                        {
                            "name": "amap_search_poi",
                            "description": "高德地图POI搜索: 查找周边酒店/餐厅/医院",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "keywords": {"type": "string", "description": "搜索关键词"},
                                    "city": {"type": "string", "description": "城市"},
                                    "types": {"type": "string", "description": "POI类型: 酒店|餐饮|医院"},
                                },
                                "required": ["keywords", "city"],
                            },
                        },
                        {
                            "name": "amap_geocode",
                            "description": "高德地理编码: 地址→坐标",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "address": {"type": "string", "description": "详细地址"},
                                },
                                "required": ["address"],
                            },
                        },
                        {
                            "name": "fs_read_file",
                            "description": "读取本地文件内容",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string", "description": "文件路径"},
                                },
                                "required": ["path"],
                            },
                        },
                    ]
                },
            }

        if method == "resources/list":
            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "resources": [
                        {"uri": "file:///travel/beijing-guide.md", "name": "北京攻略", "mimeType": "text/markdown"},
                        {"uri": "file:///travel/chengdu-food.md", "name": "成都美食地图", "mimeType": "text/markdown"},
                        {"uri": "calendar://google/primary", "name": "Google日历", "mimeType": "application/json"},
                    ],
                },
            }

        if method == "tools/call":
            tool_name = request.get("params", {}).get("name", "")
            args = request.get("params", {}).get("arguments", {})
            result = self._mock_tool_call(tool_name, args)
            return {"jsonrpc": "2.0", "id": rid, "result": result}

        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}}

    def _mock_tool_call(self, name: str, args: dict) -> dict:
        """模拟工具调用结果。"""
        if name == "amap_search_poi":
            poi_type = args.get("types", "酒店")
            city = args.get("city", "北京")
            return {
                "content": [
                    {"type": "text", "text": f"[{city}] {poi_type}搜索结果:\n"
                     f"1. {city}大酒店 ★4.5  ¥380/晚\n2. {city}客栈 ★4.2  ¥180/晚\n3. {city}青旅 ★3.8  ¥60/晚"}
                ],
            }
        if name == "amap_geocode":
            return {"content": [{"type": "text", "text": "坐标: 116.397, 39.908 (北京天安门)"}]}
        if name == "fs_read_file":
            return {"content": [{"type": "text", "text": "# 旅行攻略\n推荐景点: 故宫、长城、颐和园"}]}
        return {"content": [{"type": "text", "text": f"工具 {name} 执行完成"}]}


# ═══════════════════════════════════════════════════════════════
# MCP Client 桥接器
# ═══════════════════════════════════════════════════════════════

class MCPClientBridge:
    """
    MCP 客户端桥接器 — 连接外部 MCP Server，动态发现 + 代理执行工具。

    用法:
        bridge = MCPClientBridge(transport=MockTransport("amap"))
        await bridge.connect()
        await bridge.initialize()

        tools = await bridge.list_tools()        # → 高德POI搜索、地理编码...
        resources = await bridge.list_resources() # → 本地文件、Google日历...

        result = await bridge.call_tool("amap_search_poi",
            {"keywords": "火锅", "city": "成都", "types": "餐饮"})
    """

    def __init__(self, transport: MCPTransport):
        self.transport = transport
        self._server_info: Dict[str, Any] = {}
        self._tools: List[Dict] = []
        self._resources: List[Dict] = []
        self._initialized = False
        self._callbacks: Dict[str, List[Callable]] = {}

    async def connect(self):
        """建立传输层连接。"""
        await self.transport.connect()

    async def initialize(self):
        """MCP 握手: initialize 请求 → 确认协议版本和能力。"""
        req = JSONRPCRequest(method="initialize", params={
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": True},
            },
            "clientInfo": {"name": "travel-agent", "version": "3.0.0"},
        })
        resp = await self._rpc_call(req)
        if resp.ok:
            self._server_info = resp.result
            self._initialized = True
            logger.info(f"✅ MCP 握手完成: {self._server_info.get('serverInfo', {}).get('name', 'unknown')}")
        else:
            logger.warning(f"MCP 握手: 非标准响应，尝试直接使用")

        # 发送 initialized 通知
        await self._rpc_notify("notifications/initialized", {})

    async def list_tools(self) -> List[Dict]:
        """tools/list: 动态获取服务端工具列表。"""
        req = JSONRPCRequest(method="tools/list", params={})
        resp = await self._rpc_call(req)
        if resp.ok:
            self._tools = resp.result.get("tools", [])
            logger.info(f"🔧 MCP 工具发现: {len(self._tools)} 个 → {[t['name'] for t in self._tools]}")
        return self._tools

    async def list_resources(self) -> List[Dict]:
        """resources/list: 动态获取服务端资源列表。"""
        req = JSONRPCRequest(method="resources/list", params={})
        resp = await self._rpc_call(req)
        if resp.ok:
            self._resources = resp.result.get("resources", [])
            logger.info(f"📁 MCP 资源发现: {len(self._resources)} 个")
        return self._resources

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        tools/call: 代理执行外部 MCP 工具。

        返回 MCP 标准格式: {"content": [{"type": "text", "text": "..."}]}
        """
        req = JSONRPCRequest(method="tools/call", params={
            "name": name,
            "arguments": arguments,
        })
        logger.info(f"🔧 MCP 调用: {name}({arguments})")
        resp = await self._rpc_call(req)
        if resp.ok:
            return resp.result
        return {"content": [{"type": "text", "text": f"Error: {resp.error}"}]}

    def on_tool_update(self, callback: Callable):
        """注册工具列表变更回调。"""
        self._callbacks.setdefault("tools/changed", []).append(callback)

    # ─── 内部 JSON-RPC 通信 ───

    async def _rpc_call(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """发送 JSON-RPC 请求并等待响应。"""
        payload = json.dumps({
            "jsonrpc": request.jsonrpc,
            "method": request.method,
            "params": request.params,
            "id": request.id,
        }, ensure_ascii=False)

        # HTTP transport: send already returns response
        if isinstance(self.transport, HTTPTransport):
            raw_bytes = await self.transport.send(payload.encode())
            raw = raw_bytes.decode() if raw_bytes else "{}"
            return self._parse_response(raw, request.id)

        # Stream transport: send request, then read responses until matching ID
        await self.transport.send(payload.encode())
        for _ in range(10):  # Max 10 reads to find matching response
            raw_bytes = await self.transport.receive()
            if not raw_bytes:
                return JSONRPCResponse(id=request.id, error={"code": -32000, "message": "No response"})
            raw = raw_bytes.decode()
            data = json.loads(raw) if isinstance(raw, str) else raw
            if data.get("id") == request.id:
                return JSONRPCResponse(
                id=data.get("id", request.id),
                result=data.get("result"),
                    error=data.get("error"),
                )
        return JSONRPCResponse(id=request.id, error={"code": -32000, "message": "No matching response"})

    async def _rpc_notify(self, method: str, params: Dict):
        """发送 JSON-RPC 通知 (无 id，无响应)。"""
        payload = json.dumps({
            "jsonrpc": "2.0", "method": method, "params": params,
        }, ensure_ascii=False)
        await self.transport.send(payload.encode())

    async def close(self):
        await self.transport.close()


# ═══════════════════════════════════════════════════════════════
# MCP 工具注册器 (桥接 MCP 工具到自研框架 ToolRegistry)
# ═══════════════════════════════════════════════════════════════

class MCPToolAdapter:
    """
    将 MCP Server 的工具适配为自研框架的 @tool 函数。

    用法:
        adapter = MCPToolAdapter(bridge)
        registry = ToolRegistry()
        await adapter.register_all(registry)
        # → registry 中自动添加 amap_search_poi, amap_geocode, fs_read_file
    """

    def __init__(self, bridge: MCPClientBridge):
        self.bridge = bridge

    async def register_all(self, registry) -> int:
        """将 MCP Server 的所有工具注册到 ToolRegistry。"""
        tools = await self.bridge.list_tools()
        count = 0
        for tool_def in tools:
            name = tool_def["name"]
            desc = tool_def.get("description", "")
            schema = tool_def.get("inputSchema", {})

            # 创建动态函数
            async def make_tool_func(tool_name, bridge_ref):
                async def tool_func(**kwargs):
                    result = await bridge_ref.call_tool(tool_name, kwargs)
                    contents = result.get("content", [])
                    return "\n".join(c.get("text", "") for c in contents)
                tool_func.__name__ = tool_name
                tool_func.__doc__ = desc
                return tool_func

            func = await make_tool_func(name, self.bridge)
            registry.register(func, name=name, description=desc)
            count += 1

        logger.info(f"🔌 MCP 适配: {count} 个工具已注册到 ToolRegistry")
        return count
