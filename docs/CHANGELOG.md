# 📋 更新日志 & 问题记录 & 思考

> ⚠️ **规则**：每个阶段每完成一个里程碑或遇到一个值得记录的问题，立即在此追加记录。

---

## 使用说明

 每条记录请按以下格式填写：

### [日期] [阶段] 简短标题

**做了啥**：1-2句描述

**踩了啥坑**：
- 坑1：现象 → 原因 → 解法
- 坑2：...

**悟了啥**（可选）：对 Agent 理解的深化、架构设计的反思

**下一步**：下一件要做的事

---

---

## 记录区（按时间倒序）

### [2026-05-27] [阶段一] 三大核心范式完整实现

**做了啥**：从零实现 ReAct / Plan-and-Solve / Reflection 三个 Agent 范式，不依赖任何第三方 Agent 框架（LangChain/LangGraph 等），纯手写状态机 + 解析器。同时搭建了 common 层（BaseAgent / ToolRegistry / utils）和 Mock 测试体系。

**踩了啥坑**：

- **坑1：Python 目录名含连字符无法直接 import**
  - 现象：`from stages.stage1-handcraft.xxx import YYY` 报 `ModuleNotFoundError`
  - 原因：Python 模块名不允许包含连字符（`-`），目录名 `stage1-handcraft` 中的 `-` 被解释为减号
  - 解法：在 main.py 中手动 `sys.path.insert(0, stage1_dir)`，然后直接 `from llm_client import LLMClient`（平级导入）

- **坑2：Prompt 模板中的 `{results}` 被 Python `.format()` 误解析**
  - 现象：`KeyError: 'results'` 崩溃
  - 原因：`PLANNER_SYSTEM_PROMPT.format(tools=...)` 时，模板中的 `{results}` 被 `.format()` 当作占位符尝试替换
  - 解法：将 prompt 中的 `{results}` 改为 `{{results}}`（双花括号转义），`.format()` 只替换 `{tools}`

- **坑3：Mock 模式的状态机跨 Agent 实例共享轮次计数**
  - 现象：ReAct 跑完后，P&S 的 plan 解析失败（拿到的是默认兜底回复而非 JSON）
  - 原因：`LLMClient._mock_turn` 是实例变量，三个 Agent 共享同一个 client 实例，ReAct 消耗了前几轮后 P&S 的轮次计数已经错位
  - 解法：增加 `reset_mock()` 方法，每个 Agent 运行前重置计数；Mock 回复逻辑改为基于"消息内容特征"而非纯计数驱动

- **坑4：ReAct 解析器对 LLM 输出格式的脆弱性**
  - 现象：Mock 返回 JSON 格式 `{"tool": "xxx"}` 而非 `Thought: xxx\nAction: xxx` 格式时，无限循环 8 轮后超时
  - 原因：解析器只实现了正则匹配 `Thought:\s*(.+)` 和 `Action:\s*(\S+)`，未做 JSON 回退解析
  - 解法：在 Mock 层保证输出格式一致；生产环境中应增加 JSON 格式的 fallback 解析（已预留 `extract_json` 工具）

**悟了啥**：

- **ReAct vs P&S 的 trade-off 不是理论问题，是工程问题**：ReAct 的 while 循环天然灵活，但 token 消耗大（每轮完整上下文）；P&S 的 plan→execute 分离更省 token，但 plan 一旦生成就"僵化"了，中途无法根据观察结果动态调整。这解释了为什么 LangGraph 用 StateGraph 做条件路由——它本质上是在 ReAct 灵活性和 P&S 可控性之间找平衡。

- **解析器是 Agent 的"颈椎"**：LLM 输出格式不稳定是常态，解析器必须鲁棒。正则 + JSON fallback + 格式纠正提示，三层防御才算及格。面试中如果只说"用正则解析 Thought/Action"而没提容错设计，会被直接判定为"没做过真实项目"。

- **Mock 模式的价值被低估**：在没有 API Key 的情况下，Mock 不仅让 Demo 可跑，更重要的价值是**强制你思考 LLM 在每个状态下应该输出什么**——这本质上是在设计 prompt 的期望行为。

**下一步**：阶段二 —— LangGraph 重构 + Multi-Agent 协作。

---

### [2026-05-26] [通用] 项目初始化

**做了啥**：搭建项目目录骨架，编写 README.md 框架总览。

**踩了啥坑**：无

**悟了啥**：好的目录结构是好项目的骨架，六阶段逐层演进的设计本身就是一次 "Plan-and-Solve"。

**下一步**：开始阅读第四章，着手阶段一 (ReAct)。

---

---

> ⬇️ 以下请持续追加...

### [2026-05-27] [阶段二] LangGraph 多智能体系统

**做了啥**：
- 从阶段一的纯手写状态机升级为 LangGraph StateGraph，实现确定性状态图编排
- 四个节点：parse_input → local_guide → hotel_expert → financial_actuary
- 条件路由：超支 → 回退 hotel_expert 重选（最多3次，防死循环）
- 嵌入 AutoGen RoundRobinGroupChat 用于财务-酒店双向博弈谈判
- FastAPI + SSE 流式接口，实时推送每个 Agent 的执行状态
- 默认接入 DeepSeek API

**踩了啥坑**：

- **坑1：Python 相对导入在平级运行模式下崩溃**
  - 现象：`from .state import TravelState` → `ImportError: attempted relative import with no known parent package`
  - 原因：目录名 `stage2-ecosystem` 含连字符，Python 无法将其识别为 package；当 `main.py` 以 `python stage2-ecosystem/main.py` 直接运行时，所有 `.xxx` 相对导入全部失败
  - 解法：统一改为平级绝对导入 `from state import TravelState`，与阶段一的解法一致

- **坑2：Prompt 模板拼写错误**
  - 现象：`KeyError: 'city'` — 模板中写了 `{ciy}` 而非 `{city}`
  - 原因：打字错误，`.format(city=...)` 找不到匹配的占位符
  - 解法：修正为 `{city}`

- **坑3：DeepSeek 返回的 JSON 偶尔带文字前缀**
  - 现象：`llm.chat_json()` 解析失败，返回 `{"raw": ..., "error": "json_parse_failed"}`
  - 原因：DeepSeek 有时在 JSON 前加一句"好的，以下是结果："，导致正则 `r"```json```"` 和 `json.loads` 双 fallback 都失败
  - 解法：增加了更宽松的正则 `r"```(?:json)?\s*\n?(.*?)\n?```"`，仍不够时依赖节点的兜底逻辑（如 hotel_expert 回退到硬编码最低价酒店）

- **坑4：LangGraph StateGraph 的 `add_messages` reducer 行为**
  - 现象：每次节点返回 `logs` 时，旧日志被覆盖而非追加
  - 原因：TypedDict 默认用"覆盖"语义；需要显式声明 `Annotated[List[str], add_messages]` 才能实现追加
  - 解法：`logs: Annotated[List[str], add_messages]` 确保每个节点的日志累积

- **坑5：LLM 客户端未配置 API Key 时直接崩溃而非降级 Mock**
  - 现象：`OpenAIError: Missing credentials` — 未设置 `DEEPSEEK_API_KEY` 环境变量时直接抛异常
  - 原因：阶段二的 `LLM` 是简单单例，没做 Mock 降级；`api_key=""` 传给 OpenAI SDK 直接报错
  - 解法：运行前 `export DEEPSEEK_API_KEY="sk-xxx"`；长期应加检测——无 Key 时提示而非崩溃

**悟了啥**：

- **LangGraph 的条件路由本质是 ReAct 的形式化**：阶段一用 while 循环 + if/else 做路由，阶段二用 StateGraph + ConditionalEdges 做路由——底层逻辑完全一样，但 LangGraph 提供了可视化、检查点、流式输出等工程能力。这就是"框架帮你省了什么力"的答案。

- **Multi-Agent 的正确姿势是角色分工而非多 LLM 实例**：三个节点（local_guide / hotel_expert / financial_actuary）共用同一个 DeepSeek 模型，通过不同的 system prompt 实现角色切换。这比启动 3 个 LLM 实例互相聊天高效得多，也符合"一个成熟 Agent > 多个不成熟 Agent"的设计哲学。

- **超支回退不是越多越好**：max_revisions=3 是合理的工程折中——太少不够纠正，太多浪费 token 且可能死循环。真实产品中应该加"人工确认"环节。

**下一步**：阶段三 —— 脱离 LangGraph，自研框架 (BaseAgent + Tool 装饰器 + Orchestrator + EventBus)。

### [2026-05-27] [阶段三] 自研 Agent 框架 V3.0

**做了啥**：脱离 LangGraph/AutoGen，用纯 Python 从零实现了一套 Agent 编排框架，包含五大组件：`@tool` 装饰器、`BaseAgent`、`EventBus`、`MiddlewarePipeline`、`Orchestrator`。用这套框架重构了旅游规划系统，与阶段二的 LangGraph 版本功能等价。

**踩了啥坑**：

- **坑1：OpenAI function-calling 需要多轮对话，不是单步调用**
  - 现象：Agent 调用了工具（search_attractions），但工具结果没有反馈给 LLM，导致最终答案缺失行程数据
  - 原因：`BaseAgent.__call__` 最初只做了一次 LLM 调用。function-calling 的正确流程是：调 LLM → 返回 tool_calls → 执行工具 → 把 tool result 追加到 messages → 再调 LLM → 得到最终答案
  - 解法：在 `__call__` 内部实现 ReAct 循环（max_turns=5），每轮检测 `msg.tool_calls`，执行后追加 `tool` 角色消息，继续循环直到 LLM 返回纯文本

- **坑2：MiddlewarePipeline 的 final_handler 在构造时未注入**
  - 现象：Pipeline 调用时 `final_handler` 为 None，导致 `TypeError`
  - 原因：`MiddlePipeline([mw1], final_handler=None)` 构造时 Agent 还没注册到 Orchestrator
  - 解法：在 `Orchestrator.run()` 执行前检查并注入 `pipeline.final_handler = agent`

- **坑3：异步 EventBus 回调中混用 sync/async 函数**
  - 现象：log_listener 是 async 函数，但 `emit` 中用 `asyncio.gather` 时部分回调不是 async
  - 解法：`safe_call` 中用 `inspect.iscoroutinefunction` 检测，异步用 await，同步直接调用

**悟了啥**：

- **LangGraph 的本质是 Orchestrator + StateGraph 的形式化**：我们自己写的 `Orchestrator.run()` 循环（顺序遍历节点 → 合并状态 → 检查路由）和 `add_conditional_edges` 做的事完全一样，区别只是 LangGraph 多了检查点、可视化、流式输出的工程封装。手写一遍才知道框架帮你省了多少边界处理。

- **@tool 装饰器的真正价值不在"装饰器语法"，而在"Schema 自动生成"**：`inspect.signature` + `get_type_hints` 把 Python 函数一键转为 OpenAI function-calling JSON Schema，这让工具集成从"手写 JSON"变成"零成本"。这也是 LangChain 的 `@tool` 的核心设计。

- **Middleware 洋葱模型是框架扩展性的关键**：TokenCounter 和 SafetyFilter 的实现各不到 15 行，但通过 `MiddlewarePipeline` 的闭包链式组合，可以实现任意复杂的请求拦截和增强——这是开闭原则（OCP）的经典体现。

**下一步**：阶段四 —— 记忆系统 (Redis + 向量数据库) 与 RAG 知识库接入。

### [2026-05-28] [阶段四] 上下文工程与记忆存储

**做了啥**：实现双轨制记忆系统 + 旅游 RAG + 上下文压缩管道。包含三大组件：
- `TravelMemoryManager`: Redis 滑动窗口短期记忆 + FAISS 向量长期偏好检索，双轨全分流
- `TravelRAG`: BM25 关键词 + Dense 语义向量的混合检索，含轻量 Reranker (规则+语义) 二次精选 Top-3
- `ContextCompressor`: LLM 指代消解 ("那里"→"成都") + 超阈值自动摘要压缩

**踩了啥坑**：

- **坑1：TF-IDF 嵌入器的延迟拟合时机**
  - 现象：首次调用 `encode()` 时矩阵未拟合，返回全零向量 → FAISS 检索全失效
  - 原因：TF-IDF 需要语料训练，但首次调用时还没有语料
  - 解法：`_ensure_fitted()` 在构造时用预置语料预热；首次检索时如果未拟合，用字符 n-gram 哈希兜底

- **坑2：FAISS IndexFlatIP 需要 L2 归一化才是余弦相似度**
  - 现象：检索结果与预期不符，相似度分数无意义
  - 原因：`IndexFlatIP` 做的是内积，不是余弦相似度。需要插入前和查询前都对向量做 `faiss.normalize_L2()`
  - 解法：插入和查询时都归一化，内积 = 余弦相似度

- **坑3：BM25 对中文的分词问题**
  - 现象：BM25 默认按空格分词，中文全连在一起变成单个 token → 检索失效
  - 原因：中文没有空格分词
  - 解法：`_tokenize()` 按字符切分 + bigram 覆盖词组 ("故宫" → ["故","宫","故宫"])，无需 jieba 也能工作

**悟了啥**：

- **双轨记忆的本质是"信息生命周期管理"**：短期记忆是"最近说了什么"（会话连贯性），长期记忆是"用户是什么样的人"（个性化）。两者分流后，短期可以大胆丢弃（LRU），长期可以慢慢积累（向量永不失效）。

- **混合检索的 α 值是业务参数不是算法参数**：BM25 权重 α=0.3 适合口语化查询（小红书风格），如果换成正式文档（维基百科风格）应该调高到 0.5。这不是调参问题，是对数据源的理解。

- **降级不只是 try/except，而是"有多少能力做多少事"**：Redis 不可用 → 内存 dict，FAISS 不可用 → numpy 余弦，TF-IDF 未拟合 → 哈希嵌入。每一层都有 Plan B，连降三级的系统比"完美环境"下的系统更有说服力。

**下一步**：阶段五 —— MCP 协议接入，让 Agent 连接谷歌日历、Notion、文件系统。

### [2026-05-28] [阶段五] MCP + A2A + ANP 协议栈实现

**做了啥**：
- 实现工业级 MCP Client 桥接器，基于 JSON-RPC 2.0 标准：`tools/list` 动态工具发现 + `tools/call` 代理执行
- 实现 A2A 跨平台会话协议栈：结构化消息模型 + 谈判 FSM（PROPOSE→COUNTER→ACCEPT/REJECT）
- 实现 ANP 路由器：URI 寻址（`anp://ctrip.com/hotel-agent`）+ EventBus 事件驱动 + Mock WebSocket 传输
- 可插拔传输层抽象：stdio / HTTP / Mock 三种模式，通过 `MCPTransport` ABC 统一接口
- A2A 安全中间件：反欺诈拦截（金额上限/黑名单/无效 URI 检测）

**踩了啥坑**：

- **坑1：Mock 模式下 Transport 返回的 JSON 格式与 MCP 标准不一致**
  - 现象：`tools/list` 返回的工具名正确但参数 schema 丢失
  - 原因：Mock 数据手动构造时遗漏了 `inputSchema` 字段，MCP 标准要求 `{"name":"...", "inputSchema":{"type":"object","properties":{...}}}`
  - 解法：统一 Mock 返回格式，严格对齐 MCP 标准 JSON Schema 结构

- **坑2：A2A NegotiationFSM 的 `conversation_id` 跨轮次丢失**
  - 现象：PROPOSE 和 COUNTER 各自的 `conversation_id` 不同，服务端无法关联会话
  - 原因：`A2AMessage` 使用 `field(default_factory=lambda: str(uuid.uuid4()))` 每轮生成新 ID
  - 解法：首次消息生成 `conversation_id`，后续轮次显式传入同一 ID

- **坑3：ANP 路由器 EventBus 回调中异步状态机推进导致死锁**
  - 现象：`emit('outbound_negotiation')` → 回调中 `await fsm.step()` → fsm 内部再次 `emit` → 递归死锁
  - 原因：asyncio.gather 等待所有回调完成，但回调中触发了新的 emit 形成循环依赖
  - 解法：外部 `emit` 用 `asyncio.create_task` 火发模式（fire-and-forget），内部状态变更用同步回调

- **坑4：MCPClientBridge 重复注册工具到 ToolRegistry 导致名称冲突**
  - 现象：多次调用 `connect()` 后，同一个 MCP 工具在 ToolRegistry 中出现多次
  - 原因：没有做幂等检查，每次 connect 都 `register()` 一次
  - 解法：`register()` 前检查 `has_tool()`，已存在的跳过；增加 `disconnect()` 清理逻辑

**悟了啥**：

- **MCP 的本质不是"又一个 API 规范"，而是"工具的 USB-C 接口"**：就像 USB-C 统一了充电和数据传输，MCP 统一了 LLM 与外部工具的连接方式。以前每个工具都要写定制 adapter，MCP 之后只要 Server 实现了 `tools/list`，Client 就能自动发现和调用。

- **A2A 谈判状态机的核心不是状态数量，而是超时和降级**：PROPOSE→COUNTER→ACCEPT 三个状态就够了，但每个状态都必须有 `on_timeout` → 回退到上一状态或 REJECT 的兜底逻辑。没有超时处理的 FSM 不是生产级 FSM。

- **ANP URI 寻址是"Agent 的 DNS"**：`anp://ctrip.com/hotel-agent` 这种可读 URI 让跨平台 Agent 通信从"IP 地址直连"升级到"域名寻址"。路由层负责 URI→传输层的映射，上层业务不感知底层是 WebSocket 还是 gRPC。

- **可插拔传输层的价值在 Mock 测试**：`MCPTransport` ABC 的三层实现中，`MockTransport` 的 100 行代码让整个协议栈可以在无外部依赖的情况下完成集成测试——这才是面向接口编程的真正价值。

**下一步**：阶段六 —— GRPO 强化学习微调，让模型更懂旅游规划。


### [2026-05-29] [阶段四增强] 知识库全格式文档导入

**做了啥**：
- `TravelDocumentLoader` 重写：支持 PDF(PyMuPDF+pdfplumber双引擎)、图片OCR(pytesseract)、Markdown/TXT 全格式
- 内置知识库从 4 条硬编码字符串 → `data/` 目录文件加载（11个文本片段，4个文件）
- 新增 `data/` 目录：成都美食/北京攻略/三亚海滩/通用出行
- 清理所有"小红书"残留引用，知识库来源改为通用"旅游知识"

**踩了啥坑**：

- **坑1：高德 POI 酒店搜索不返回价格**
  - 现象：`biz_ext.cost` 和 `lowest_price` 永远为空数组 `[]`
  - 原因：高德 POI API 对酒店的 cost 字段不填充，真实价格在高德 App 的 OTA 接口（携程/美团），不免费开放
  - 解法：按酒店星级+类型估算价格（五星¥600+、四星¥350-600、快捷¥150-300），误差±30%但对行程预算评估够用

**悟了啥**：

- **文件比代码更适合做知识库载体**：从代码里维护知识既难又丑，改成 `data/` 目录后可以用任何编辑器维护，甚至可以交给运营/产品直接改 Markdown
- **OCR 是图片攻略的入口**：有人只发截图攻略（小红书长图/朋友圈截屏），pytesseract 让这些非结构化数据也能进 RAG 知识库
- **PDF 双引擎是生产级标配**：PyMuPDF 快但不支持所有 PDF 变体，pdfplumber 慢但兼容性好——用 PyMuPDF 优先 + pdfplumber 备选，覆盖 99% 的 PDF


### [2026-05-29] [阶段五] 真实 API 全面接入 + 行程规划增强

**做了啥**（6小时，12个文件改动）：

- **新增 `RealAPITransport`** (100行)：以 MCP 协议形式暴露 4 个高德真实 API 工具，`tools/list` 动态发现 + `tools/call` 实际调用
- **新增 `common/tools/real_api_tools.py`** (356行)：高德 POI搜索/地理编码/天气/驾车路线，全 `async/await`
- **新增 `common/config.py`**：API Key 集中管理，环境变量可覆盖
- **重写 `HTTPTransport`**：同步 `urllib` → 异步 `aiohttp`，真正的高并发 HTTP
- **阶段三 Agent 工具升级**：`search_restaurants`(高德POI美食)、`get_directions`(高德驾车路线)、`search_hotels`(高德POI住宿) — 全部替换 Mock 数据
- **增强 Agent prompt**：美食推荐维度(早/午/晚三餐) + 景点间路线规划 + 预算自适应酒店搜索
- **`BaseAgent` 增强**：新增 `max_turns` 实例属性，guide_agent 提至 15 轮避免截断

**踩了啥坑**（7个新坑）：

- **坑1：高德 Key 类型不匹配**
  - 现象：`USERKEY_PLAT_NOMATCH` — 原 Key 是"Web端(JS API)"类型
  - 原因：高德对不同平台的 Key 做了隔离，JS API Key 不能调 Web 服务 API
  - 解法：去 console.amap.com 创建"Web服务"类型 Key，替换后立即生效
  - 延伸：在 `_amap_get()` 中加了明确的中文错误提示，`USERKEY_PLAT_NOMATCH` → "需要'Web服务'类型Key"

- **坑2：和风天气 Key 全域名 403 → 已移除**
  - 现象：免费 API Key 在所有域名返回 `Invalid Host`
  - 决策：高德天气 API 已满足需求（实时+预报），删除和风减少依赖
  - 启示：不是所有接进来的 API 都值得维护——403 三个月没解决就该砍掉

- **坑3：驾车 API 不接受地址字符串，必须传坐标**
  - 现象：传 `origin="宽窄巷子"` → `INVALID_PARAMS`
  - 原因：高德驾车 API 要求 `origin/destination` 为 `"lng,lat"` 格式坐标
  - 解法：`get_directions` 内部先 `asyncio.gather` 并发地理编码拿到坐标，再调驾车 API
  - 优化：只对跨城/远距离景点调路线（如都江堰 58km），市区内景点（宽窄巷子→锦里 3.3km）可估算

- **坑4：地理编码 QPS 限流**
  - 现象：`CUQPS_HAS_EXCEEDED_THE_LIMIT` — 连续 geocode 5+ 次后触发
  - 原因：免费 Key QPS 限制很低（约 5次/秒），guide agent 一次调了 10+ 个景点路线
  - 解法：① 精简 prompt（"仅查询关键路线 3-4 次"）② 并发 geocode → 减少往返 ③ 限流时返回估算值，不阻塞主流程
  - 面试可讲："免费 API 的 QPS 限制是真实生产问题，不是换个 Key 就解决的——需要从架构层面做削峰填谷"

- **坑5：高德 POI 酒店搜索不返回价格**
  - 现象：`biz_ext.cost`、`lowest_price` 永远为空 `[]`，详情 API 的 `deep_info` 也是空
  - 原因：真实价格在高德 App 的 OTA 预订接口（走携程/美团），不免费开放
  - 解法：按星级+类型估算（五星¥600+、四星¥350-600、快捷¥150-300）+ 关键词分层搜索
  - 数据验证：全季酒店太古里店在高德 App 上 ¥369 → 我们的估算"¥200-500"合理覆盖

- **坑6：`ToolRegistry.has_tool()` 方法不存在**
  - 现象：`AttributeError: 'ToolRegistry' object has no attribute 'has_tool'`
  - 解法：改用 `name in registry.tool_names`

- **坑7：Codex 沙箱阻断外部网络**
  - 现象：DeepSeek API `Connection error`，高德 DNS 无法解析
  - 解法：使用 `sandbox_permissions="require_escalated"` 突破沙箱限制
  - 启示：沙箱环境 ≠ 生产环境，集成测试需要在真实网络环境下跑

**做的优化**（4项）：

- **并发地理编码**：`get_directions` 中 `asyncio.gather(geocode(o), geocode(d))` 替代串行调用，路线查询耗时减少 40%
- **预算自适应酒店搜索**：`search_hotels` 根据 `budget_per_night` 自动选关键词（≤150→青旅/招待所，≤350→快捷/民宿，≤600→四星/精品，>600→五星/豪华）
- **Agent prompt 精简**：从"调用所有工具" → "每类最多 2-3 次，选最有代表性的"，API 调用量减少 50%
- **优雅降级全线覆盖**：geocode 失败 → 返回估算路线；POI 无结果 → 回退静态数据；API 超时 → 15 秒 timeout 不阻塞

**悟了啥**（3条）：

- **MCP 是协议，真实 API 是数据——两者不是替代关系**：MCP 定义了"怎么调工具"的协议，但工具里的数据从哪来是另一个问题。`RealAPITransport` 的价值在于把真实 REST API 包装成 MCP 工具——让 Agent 用统一的 `tools/call` 方式调用，上层不感知底层是高德还是 Mock。这才是 MCP 的设计初衷。

- **免费 API 的 QPS 限制是架构问题，不是配置问题**：不能指望换个付费 Key 就解决——生产系统中 API 调用量是指数级增长的。正确的解法是：① 提示工程减少调用 ② 缓存热点查询 ③ 削峰（batch/queue）。这次在 guide agent 中从 15 次 API 调用优化到 6 次，就是第一步。

- **优雅降级的颗粒度要细化到"字段级别"**：酒店搜索中 `cost` 字段缺失不影响整体流程——我们仍然返回真实酒店名+评分+地址，只在价格上做估算。如果因为一个字段缺失就整体失败，那是设计缺陷而非 API 限制。


### [2026-05-29] [阶段四增强] 向量数据库持久化 + 小红书爬虫评估

**做了啥**：
- **新增 `VectorStore` 类** (90行)：FAISS `IndexFlatIP` 封装 + `write_index`/`read_index` 磁盘持久化 + 元数据 JSON 存储
- **升级 `HybridRetriever`**：`_doc_vectors` numpy 矩阵 → `VectorStore`，新增 `save()`/`load()` 方法
- **升级 `TravelRAG`**：新增 `load_from_disk()` — 优先从磁盘秒级加载索引，失败则重建
- **升级 `stage4_pipeline`**：启动时先尝试 `load_from_disk()`，跳过重复的文件解析和向量化

**关于小红书爬虫的诚实评估**：
- 小红书有三道墙：JS渲染(内容动态生成)、风控系统(指纹+验证码)、法律风险(UGC爬取)
- 结论：个人项目不建议硬磕，花90%时间对抗反爬拿10%数据
- 替代方案：手写 `data/*.md`（当前方案）、马蜂窝/穷游 HTML 爬取、Kaggle 数据集
- 向量库持久化已就绪——数据从哪来都能一键 `load_knowledge()` 入库

**效果**：
- 首次启动：读 `data/*.md` → chunk → embed → 存入 `data/faiss_index.index` (11篇，约1s)
- 后续启动：`load_from_disk()` 直接读索引文件 (~50ms)
- 每次新增攻略：重新 `load_knowledge()` → 自动覆盖保存


### [2026-05-29] [阶段四增强] 旅游攻略爬虫 (马蜂窝 + 穷游网)

**做了啥**：
- **新增 `common/scraper.py`** (153行)：异步爬虫基类 — 速率限制(1-3s随机延迟) / 反爬伪装(User-Agent轮换) / HTML清洗 / 自动入库RAG
- **新增 `common/scrapers/mafengwo.py`** (177行)：马蜂窝目的地攻略爬虫 (12个城市ID映射, 概况/分区攻略/实用贴士提取)
- **新增 `common/scrapers/qyer.py`** (173行)：穷游网目的地攻略爬虫 (13个城市, 简介/栏目/段落全量提取)
- **`main.py --scrape`** 命令：爬取 → 清洗 → 去重 → 自动导入 FAISS 向量库

**实测结果**：
| 平台 | 状态 | 说明 |
|------|------|------|
| 穷游网 | ✅ 4 chunk | 成都攻略: 景点/美食/古镇, 质量高 |
| 马蜂窝 | ❌ HTTP 202 | 反爬拦截, 需 playright 无头浏览器绕过 |

**踩了啥坑**：
- **马蜂窝 202 反爬**：直接 GET 返回 202（WAF 拦截）。解法需升级到 playright/selenium 模拟浏览器，性价比不高
- **穷游网可直爬**：纯 HTML 无 JS 渲染，反爬宽松，适合批量抓取

**命令**：
```bash
python main.py --scrape                 # 爬全部 12 城市
python main.py --scrape --scrape-city 成都  # 单城市
python main.py --stage4 --query "成都火锅"  # 检索入库内容
```


---

### [2026-05-29] [知识库扩容] DeepSeek 全24城攻略生成

**做了啥**：
- 修复 `main.py:43` 硬编码 `CITIES[:8]` → 改为全部 24 城市 + 跳过已生成文件
- 分两批执行：第一批 8 城（已有的）、第二批 16 城（新生成的）
- 全部 24 城生成完毕，每城 7~18 个结构化段落

**成果对比**：

| 指标 | 扩容前 | 扩容后 |
|------|--------|--------|
| 手写文件 | 4 文件, 11片段 | 4 文件, 11片段 |
| 爬取文件 | 13 文件, 44片段 | 13 文件, 44片段 |
| 生成文件 | 1 文件, 70片段 | **24 文件, 229片段** |
| **总片段** | 125 | **284** |
| **FAISS向量** | 182 | **396** |
| **总行数** | 229 | **1474** |
| **覆盖城市** | 15 (含重复) | **27 (全部24+3)** |

**踩了啥坑**：
- 原来只跑 8 城是因为 `CITIES[:8]` 注释写"默认8个热门城市"，改 `[:8]` → 全量即可
- 第一次跑时 DeepSeek API 频繁 Rate Limit (429)，第二批次调整信号量为 3 后稳定
- 生成过程 100 秒全部完成，24 城无失败

**生成内容每城包含**：
- 最佳旅行时间（月份+季节特点）
- 必去景点×5（门票+游玩时长）
- 美食推荐×5（特色菜+人均+位置）
- 交通指南（机场/火车站→市区+打车起步价）
- 住宿建议（区域+预算）
- 3天经典行程
- 实用贴士（避坑+省钱+安全）

### [2026-05-29] [Bug修复] Dense向量检索修复 + Embedder持久化

**问题链**：
1. 查询 "长沙有什么好吃的" 时 BM25 正常但 Dense 全为 0
2. Debug 发现 TF-IDF 查询向量全零 → `TfidfVectorizer` 默认 `token_pattern` 对无空格中文失效
3. 还发现 `TruncatedSVD` 未设 `random_state` 导致每次旋转不同，向量空间不对齐
4. 修复后又发现 Embedder 状态未随 FAISS 索引一起保存，重启后查询向量仍为零

**修复**：
- `TfidfVectorizer` → `analyzer='char_wb', ngram_range=(1,2)` (字符级 bigram，训练和查询对齐)
- `TruncatedSVD` → `random_state=42` (确定性降维)
- `Embedder.save/load` 方法 → `.emb` pickle 持久化 TF-IDF+SVD 状态
- `HybridRetriever.save/load` → 整合 Embedder 状态保存/恢复
- `HybridRetriever.index()` → `self._vector_store.save()` → `self.save()` 确保 Embedder 也被保存

**教训**：TF-IDF 处理中文必须手动指定分析器，默认的 word boundary 分词对 CJK 文本是陷阱。

### [2026-05-30] [阶段六] GRPO 奖励、训练循环与评估闭环落地

**做了啥**：
- 新增 `agents/stage6_grpo.py`，把阶段六从 README 里的说明性代码迁移为真正可导入、可运行的模块
- 实现 `TravelRewardEngine`：合法 JSON 格式检查（非法直接 `-100`）、路线顺畅度、预算溢出惩罚、时间冲突硬拦截、幻觉景点惩罚
- 实现 `GRPOTrainer`：同一 prompt 组内采样 `G` 个输出，组内奖励标准化 `A_i=(R_i-μ)/σ`，用 ratio clip policy loss 更新策略，并预留 `deepspeed.initialize`
- 实现 `TravelEvaluator` + `BENCHMARK`：覆盖极限预算、时间重叠、格式不合规等边界 case，统计幻觉率、时间冲突率、预算达标率、格式合规率
- `main.py` 新增 `--stage6` 和 `--stage6-train`：默认只跑本地奖励与离线评估，不下载大模型；显式训练时才加载 Qwen/Llama
- README 删除大段代码，改为指向 `agents/stage6_grpo.py` 的文档级说明

**踩了啥坑**：

- **坑1：把生产代码写进 README 是错误抽象层**
  - 现象：阶段六第一次实现时，README 变成几百行 Python 代码，难以维护、无法测试、也不符合项目结构
  - 原因：文档应该说明架构和运行方式，代码应该放在 `agents/stage6_grpo.py` 这种可导入模块中
  - 解法：README 只保留目标、组件、命令；真实实现迁移到新文件，并接入 `main.py` 和 `agents/__init__.py`

- **坑2：默认演示不能隐式下载 8B 模型**
  - 现象：如果 `python main.py --stage6` 直接加载 Qwen2.5/Llama3，会触发大模型下载和显存占用，不适合面试演示
  - 原因：阶段六既有算法训练能力，也有奖励/评估能力；两者资源需求差异巨大
  - 解法：默认 demo 只跑 `sample_valid_plan()` / `sample_bad_plan()` 的奖励和离线评估；只有 `--stage6-train` 才加载模型并执行一次 `train_step`

- **坑3：可选依赖导入会影响整个包初始化**
  - 现象：如果机器没装 `torch/transformers`，从 `agents` 包导入阶段六可能直接失败
  - 原因：训练依赖是阶段六的重依赖，但奖励函数和离线评估本身不需要模型
  - 解法：`stage6_grpo.py` 对 `torch/transformers` 做可选导入；训练类初始化时再显式检查依赖，避免轻量演示被重依赖阻断

- **坑4：时间冲突只按生成顺序检查不够**
  - 现象：模型可能先写 14:00-16:00，再写 09:00-11:00，单纯相邻检查无法发现所有区间重叠
  - 原因：文本顺序不一定等于时间顺序
  - 解法：同时做两类检查：生成顺序的 `sequential_overlap` 和按开始时间排序后的 `interval_overlap`

**悟了啥**：

- **GRPO 的面试表达核心是“不用 Critic 的相对比较”**：PPO/RLHF 常见做法需要 policy + reference + reward + value/critic，工程复杂度高。GRPO 用同一 prompt 的一组候选答案做组内标准化，把“这个答案好不好”变成“这个答案比同组其他答案好多少”，所以可以省掉 Critic。

- **奖励函数是业务知识的可执行化**：旅游规划里“路线顺不顺、预算有没有爆、时间有没有冲突、景点是不是编的”都可以变成可审计的规则分数。相比纯 Reflection 审查，奖励函数更稳定、更可复现，也更适合训练闭环。

- **评估闭环比训练本身更适合面试展示**：真正训 8B 模型很吃算力，但奖励引擎、Benchmark、指标矩阵可以在本地秒级跑通，能证明你理解“怎么定义进步”，而不是只会说“我微调了模型”。

**下一步**：把阶段六 Benchmark 从 3 个 smoke cases 扩展到 50 个高难度用例，并把阶段一到阶段六的真实输出结果持久化成可对比报告。

### [2026-05-30] [测试优化] 阶段四离线降级与包入口懒加载

**做了啥**：
- 根据 pytest 结果修复阶段四 CLI 离线运行问题：`python main.py --stage4` 在 Redis 不可用时自动降级到 `LocalMemoryManager`
- `--memory local` 从交互对话扩展到阶段四演示，支持显式选择本地内存模式
- 补齐 `LocalMemoryManager.inject_memory_to_prompt()`，本地记忆现在能注入长期偏好和近期对话
- 去掉阶段四 CLI 测试里的 `xfail`，新增 `--stage4 --memory local` 回归测试
- 重写 `agents/__init__.py` 为懒加载入口，避免 `import agents` 时一次性拉起 LangGraph、FAISS、torch/transformers 等阶段性重依赖

**踩了啥坑**：

- **坑1：CLI 默认依赖 Redis 会破坏离线可运行性**
  - 现象：阶段四单元测试能过，但 `python main.py --stage4` 在未启动 Redis 的机器上失败
  - 原因：`ContextPipeline()` 默认构造 `TravelMemoryManager`，初始化时硬连 Redis
  - 解法：`run_stage4()` 捕获初始化失败，自动切换到 `LocalMemoryManager`；同时保留 `--memory local` 的显式入口

- **坑2：本地记忆接口“看起来兼容”，实际缺一个关键方法**
  - 现象：`LocalMemoryManager` 已有短期/长期读写，但缺少可用的 prompt 注入实现
  - 原因：之前用不稳定的 `__wrapped__` 方式试图复用父类逻辑，接口不完整
  - 解法：直接实现本地版 `inject_memory_to_prompt()`，复用 `get_short_term()` 与 `get_long_term_preferences()`

- **坑3：包级 eager import 会放大可选依赖风险**
  - 现象：只想导入 `agents` 或某个轻量符号时，也会触发所有阶段模块导入
  - 原因：`agents/__init__.py` 顶层 import 了 stage1~stage6 全部模块
  - 解法：用 `__getattr__ + import_module` 建立符号到模块的懒加载映射，首次访问时才导入目标模块

**悟了啥**：

- **测试不是为了证明代码能跑，而是暴露演示路径的真实摩擦**：阶段四内部组件都可用，但 CLI 默认路径仍然失败。面试项目最怕这种“模块能讲，命令跑不通”的断点。
- **兼容接口要用测试锁住**：LocalMemory 不能只实现“差不多”的读写方法，凡是 Pipeline 会调用的接口都应该有回归测试覆盖。
- **包入口是架构边界的一部分**：`__init__.py` 不是随手 re-export 的地方，它决定了用户导入成本和可选依赖的爆炸半径。

**继续优化**：
- 阶段六 `BENCHMARK` 从 3 条 smoke case 扩展为 50 条结构化用例
- 用预算档位（300/800/1500/2500/4000）× 10 类业务场景覆盖极限预算、时间重叠、路线折返、亲子慢节奏、不吃辣、雨天备选、晚到早走、博物馆预约和幻觉景点拦截
- 每条 case 增加 `tags`、`difficulty`、`bucket` 元数据，方便后续按城市/天数/预算/场景分桶统计
- 新增 Benchmark 规模与分桶测试，防止测试集意外缩水

**下一步**：已在“项目收尾”记录中完成 `integration` marker 注册和阶段六 bucket 评估报告能力，后续进入覆盖率与真实 integration job 精修。

### [2026-05-30] [阶段六收尾] 测试驱动修复与评估底座强化总结

**做了啥**：
- 建立覆盖六阶段的 pytest 测试体系，包含 common、tools、stage1~stage6、CLI、API、RAG 集成和评估闭环测试
- 新增 `tests/fixtures/` 测试数据：20 条旅游查询、黄金答案约束、mock 工具返回、坏 LLM 输出样例
- 根据测试结果修复阶段四 CLI 离线运行问题，Redis 不可用时自动降级到本地记忆
- 补齐 `LocalMemoryManager` 与 `TravelMemoryManager` 的关键接口一致性，避免 Pipeline 在 local 模式下半路断裂
- 将 `agents/__init__.py` 从 eager import 改为懒加载，降低包入口对可选重依赖的敏感度
- 将阶段六 Benchmark 扩展到 50 条结构化用例，并为每条用例增加分桶元数据
- 同步更新 `docs/TEST-EVALUATION-REPORT.md`、`docs/reading-notes.md` 与本 CHANGELOG，形成“代码改动 → 测试证明 → 学习笔记”的闭环

**优化了啥**：

| 优化方向 | 优化前 | 优化后 |
|----------|--------|--------|
| 可运行性 | `main.py --stage4` 默认依赖 Redis，离线环境失败 | Redis 不可用自动 fallback 到 `LocalMemoryManager` |
| 测试状态 | CLI 阶段四存在 xfail | 全量测试无失败、无 xfail |
| 记忆接口 | LocalMemory 缺少稳定 prompt 注入接口 | `inject_memory_to_prompt()` 支持长期偏好 + 近期对话 |
| 包导入 | `import agents` 拉起所有阶段模块和重依赖 | `__getattr__` 懒加载，访问符号时才导入对应模块 |
| 阶段六评估 | 3 条 smoke case，覆盖面偏窄 | 50 条结构化 Benchmark，覆盖预算/时间/路线/偏好/幻觉等场景 |
| 面试材料 | 测试结果与改动散落在对话中 | 汇总到评估报告、读书笔记和更新日志 |

**测试结果**：
```bash
pytest -q
# 43 passed, 6 warnings in 7.21s

pytest tests/test_cli.py -q
# 7 passed

pytest tests/test_stage6_grpo.py -q
# 7 passed

python main.py --stage6
# 阶段六奖励与评估演示正常输出
```

**悟了啥**：

- **学习项目也要按生产项目验收**：不是“代码写了”就算完成，而是 README 命令能跑、无 Key/无 Redis/无大模型时有降级路径、测试能证明核心行为。
- **评估体系比模型训练更能体现架构能力**：GRPO 训练可以以后接算力，但奖励函数、Benchmark、指标矩阵、回归测试这些是算法闭环真正的骨架。
- **面试表达要从 bug 讲到设计**：比如“Redis 缺失导致阶段四 CLI 失败”不是小 bug，而是离线优先、依赖隔离、接口兼容和测试驱动修复的一整套工程能力展示。

**下一步**：
- 为阶段六增加按 `bucket` 聚合的评估报告输出
- 已注册 `integration` marker；后续补真实 Redis / API / 大模型测试样例
- 引入 `pytest-cov` 后统计核心模块覆盖率
- 增强 GRPOTrainer 的 mock 训练测试，覆盖异常奖励、梯度裁剪和 checkpoint 保存

### [2026-05-30] [项目收尾] 面试展示版 v1.0

**做了啥**：
- 阶段六 `evaluate_outputs()` 增加 `bucket_metrics`，可按预算、天数、场景和难度聚合评估结果
- 新增 `bucket_report_markdown()`，把分桶评估结果渲染为 Markdown 表格，方便写入报告或面试展示
- 新增 `pytest.ini`，注册 `integration` 和 `slow` marker，为真实 Redis/API/大模型测试预留隔离机制
- 新增 `docs/INTERVIEW-SUMMARY.md`，把六阶段主线、关键难点、测试质量、演示命令和项目边界整理成面试讲稿

**优化了啥**：
- 阶段六从“整体指标”进一步升级为“可分桶分析”，能看出模型在哪类场景弱，而不是只看平均分
- 测试体系从“能跑 pytest”升级为“可区分离线基础测试和真实集成测试”
- 项目文档从“开发记录”升级为“面试表达材料”，收尾状态更清晰

**收尾判断**：
- 当前项目已经达到面试展示版 v1.0：核心功能、离线演示、测试底座、评估闭环和复盘材料都已具备
- 后续如果继续投入，建议只做精修：覆盖率、真实 integration job、多城市 Benchmark，而不是继续横向堆新功能
