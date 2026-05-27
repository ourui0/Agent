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
