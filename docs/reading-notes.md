# 📖 读书笔记

> 记录对应书籍章节的阅读心得。

---

## 格式模板

### [日期] 章节名

**核心概念**：用自己的话总结 3-5 个关键概念

**金句摘录**：原文中让你印象深刻的话

**与项目的关联**：这个概念在旅游助手里怎么落地

**疑问**：还没想明白的地方

---

---

## 笔记区

### [2026-05-27] 第五、六章：LangGraph 生态与多智能体协作

**核心概念**：

- **StateGraph 状态机编排**：LangGraph 的核心不是"让 LLM 更聪明"，而是"让 LLM 的调用流程可控"。StateGraph 把手工的 while 循环 + if/else 路由提升为显式图结构，节点是纯函数，边是流转规则，条件路由用函数动态决策下一步。这本质上是把 ReAct 的隐式控制流形式化。

- **MemorySaver 检查点**：LangGraph 内置的状态持久化。每次节点执行后 State 自动存档，支持断点恢复和分支回溯。这解决了阶段一中 Agent 崩溃后从头再来的问题。

- **Multi-Agent 的角色分工 ≠ 多 LLM 实例**：真正的多智能体是"一个模型 + 多个 system prompt + 专业化工具集"，不是起 N 个 LLM 互相聊天。三个节点（本地土著/酒店专家/财务精算）共享同一个 DeepSeek 模型，通过 prompt 切换扮演不同角色。

- **条件路由 vs 循环**：LangGraph 的 `add_conditional_edges` 比手写 while 循环好在：① 路由逻辑从执行逻辑中分离 ② 图结构可视化 ③ 天然支持流式输出（`stream()` 每个节点的状态变更都能作为 SSE 事件推送）

- **AutoGen GroupChat 的适用边界**：AutoGen 的多 Agent 对话适合**窄场景的博弈/谈判**（如财务-酒店讨价还价），但不适合做全局编排。正确姿势是：LangGraph 管全局流程，AutoGen 管局部深度对话。

**金句摘录**：

- "LangGraph 不替你做决策，它只是让你的决策流程变得可见、可测试、可恢复"
- "好的 Multi-Agent 设计不是 Agent 的堆砌，而是角色的分工"
- "条件路由是 ReAct 的工程化表达"

**与项目的关联**：

- StateGraph 实现在 `graph.py`：`build_graph()` 构建 parse→guide→hotel→finance→条件路由
- 四个节点在 `nodes.py`：每个都是 `(state) → partial_update` 的纯函数
- Multi-Agent 角色分工：三个节点共享 DeepSeek，通过 system prompt 区分（不是三个 LLM 实例）
- AutoGen 混编在 `multi_agent.py`：仅在超支谈判时启动 GroupChat，有 max_messages=8 硬上限
- SSE 流式在 `api.py`：`graph.astream()` → `EventSourceResponse` 实时推送

**疑问**：

- 如果节点内部需要调用多个工具（如 hotel 节点既要查酒店又要比价），是应该在节点内嵌 ReAct 循环，还是把工具调用也抽象为子图节点？
- LangGraph 的检查点机制在并发场景下（多个用户同时规划）会不会有状态污染？是否需要 thread_id 隔离？
- AutoGen 的 GroupChat 结果如何可靠地映射回 LangGraph State？当前用关键词匹配 HotelRecord 太脆弱了——能否让 GroupChat 输出结构化 JSON？

---

### [2026-05-27] 第四章：Agent 三大核心范式

**核心概念**：

- **ReAct (Reasoning + Acting)**：将推理和行动交替进行。Thought 分析当前状态 → Action 调用工具 → Observation 接收反馈 → 循环。关键洞察：外部工具调用提供的真实信息能显著抑制 LLM 幻觉，因为 Observation 是 ground truth 而非模型编造。

- **Plan-and-Solve**：将问题分解为"规划"和"执行"两阶段。先生成全局计划（Plan），再逐步执行每个步骤（Solve）。优势是 token 高效（不需要每步都传入完整历史），劣势是计划静态、无法根据执行中获取的新信息动态调整。

- **Reflection**：引入"自我批评"机制。生成器先产出结果，审查器（另一个 LLM 角色或同一 LLM 的角色切换）检查错误，输出修正意见，生成器据此修改。核心是角色分离避免"确认偏误"。

- **结构化输出解析**：LLM 输出本质是不稳定的自然语言，Agent 必须能可靠地从非结构化文本中提取结构化信息（工具名、参数、最终答案）。三种策略：正则匹配标签、JSON 解析（含围栏容错）、格式纠正 prompt。

**金句摘录**：

- "ReAct 不是一种 prompt 技巧，而是一种认知架构 —— 它模拟了人类'边想边做'的认知过程"
- "Plan-and-Solve 的 plan 不是最终产物，而是通往最终产物的路线图"
- "Reflection 的关键不是'检查'本身，而是让检查者和执行者不是同一个人"

**与项目的关联**：

- ReAct 实现在 `react_agent.py`：while 循环状态机 + 正则解析 Thought/Action/Action Input/Final Answer
- P&S 实现在 `plan_solve_agent.py`：`_generate_plan()` → `_execute_plan()` → `_synthesize()` 三阶段
- Reflection 实现在 `reflection_agent.py`：`_generate()` → `_reflect()` → `_apply_corrections()` 循环
- 解析工具在 `common/utils.py`：`extract_json()` + `extract_tag()` + `trim_context()`

**疑问**：

- ReAct 和 P&S 能否融合？比如先用 P&S 生成 plan，但在 solve 阶段如果发现 plan 有误，回退到 ReAct 模式——这实际上就是 LangGraph 的 StateGraph + 条件边所解决的问题
- Reflection 的审查标准如果也用可量化的规则（如"预算超支 >10% 则判定需要修正"），是否比纯 LLM 审查更可靠？这引出了阶段六的 GRPO（奖励函数代替审查员）
- 如果模型本身能力弱（如 7B 小模型），ReAct 的格式遵循度会不会急剧下降？是否需要专门的格式微调？

---

> ⬇️ 持续追加...

### [2026-05-27] 第七章：自研 Agent 框架

**核心概念**：

- **@tool 装饰器 = 反射 + Schema 生成**：核心原理只有两步——`inspect.signature(func)` 拿参数列表，`get_type_hints(func)` 拿类型注解，拼成 OpenAI function-calling JSON Schema。LangChain 的 `@tool` 底层一模一样，但多了一层 Pydantic 包装。自己写一遍 40 行后，所有 Agent 框架的 tool registration 都变成了"再封装"。

- **Orchestrator 状态机 = 节点列表 + 位置指针 + 路由函数**：LangGraph 用编译图（Graph）做路由，Orchestrator 用运行时列表 + `pos` 指针。本质都是"当前节点执行完 → 查路由表 → 跳到下一个"。区别是图是声明式的（不容易出错），指针是命令式的（更灵活但需要手动管理）。

- **Middleware 洋葱模型 = 闭包链**：`M1.before → M2.before → Agent → M2.after → M1.after`。实现上用闭包从后往前包装：每一层生成一个 `async wrapped(state): return await mw(state, inner)`，最终形成一条调用链。不需要递归，不需要中间件管理器——闭包天然就是调用链。

- **function-calling 的本质是 ReAct 的工程化**：`LLM(tools) → tool_calls → execute → append tool result → LLM → answer` 这条链路和 ReAct 的 Thought→Action→Observation→Thought 完全对应。区别只是 Thought 不再是显式文本，而是隐式体现在 tool_calls 的选择中。

- **EventBus 的价值在解耦，不在"事件"**：发布者（Orchestrator 节点执行）不知道有哪些订阅者（日志/SSE/监控），订阅者之间也互不知道。新增一个监听器不需要改任何现有代码——这是开闭原则（OCP）的经典应用。

**金句摘录**：

- "框架的价值不在于替你做事，而在于把做的事变得可见、可控、可恢复"
- "闭包是异步中间件最优雅的实现——没有之一"
- "自己写一遍框架，才知道哪些是本质（状态+路由+循环），哪些是封装（检查点+可视化+流式）"

**与项目的关联**：

- `@tool` 在 `stage3_framework.py`：40 行，自动生成 OpenAI Schema
- `BaseAgent` 在 `stage3_framework.py`：ReAct 循环内嵌，max_turns=5
- `EventBus` 在 `stage3_framework.py`：`subscribe/emit` + `asyncio.gather` 并发分发
- `MiddlewarePipeline` 在 `stage3_framework.py`：闭包链，TokenCounter / SafetyFilter 各 15 行
- `Orchestrator` 在 `stage3_framework.py`：`add_node` → `set_route` → `run` 循环 + `_backtrack_count` 限流
- 旅游业务在 `stage3_travel.py`：4 个 BaseAgent + 条件路由 + EventBus 日志监听

**疑问**：

- 如果 Orchestrator 的节点需要并行执行（如同时查天气和查酒店），当前的顺序循环怎么扩展？是否需要引入 asyncio.TaskGroup？
- Middleware 的闭包链在 10+ 层中间件时性能如何？是否需要改为迭代式调用？
- EventBus 的 `asyncio.gather` 在回调中有耗时操作时会阻塞 `emit` 返回——是否需要改为 `create_task` 的火力发模式（fire-and-forget）？
