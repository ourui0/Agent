# 📚 Agent 领域术语表

> 快速查阅，持续补充。

---

| 术语 | 全称 | 一句话解释 | 首次出现 |
|------|------|-----------|---------|
| ReAct | Reasoning + Acting | Thought→Action→Observation 循环 | 阶段一 |
| P&S | Plan-and-Solve | 先全局规划再逐步执行 | 阶段一 |
| Reflection | — | Agent 自我检查输出并纠错 | 阶段一 |
| CoT | Chain of Thought | 让 LLM 一步步思考的提示技巧 | 阶段一 |
| LangGraph | — | LangChain 的状态图编排框架 | 阶段二 |
| Multi-Agent | — | 多个 Agent 角色协作完成任务 | 阶段二 |
| RAG | Retrieval-Augmented Generation | 检索增强生成，外挂知识库 | 阶段四 |
| MCP | Model Context Protocol | Anthropic 提出的 Agent-工具标准协议 | 阶段五 |
| A2A | Agent-to-Agent | Google 提出的 Agent 间通信协议 | 阶段五 |
| ANP | Agent Network Protocol | 另一种 Agent 间通信协议 | 阶段五 |
| GRPO | Group Relative Policy Optimization | DeepSeek-R1 核心训练算法 | 阶段六 |
| RLHF | Reinforcement Learning from Human Feedback | 基于人类反馈的强化学习 | 阶段六 |
| Embedding | — | 将文本转为向量的技术 | 阶段四 |
| Vector DB | — | 存储和检索向量的数据库 | 阶段四 |
| Orchestrator | — | 多 Agent 编排器 | 阶段三 |
| EventBus | — | 事件总线，解耦组件通信 | 阶段三 |
| Tool | — | Agent 可调用的外部函数/API | 全阶段 |
| Hallucination | — | 模型"幻觉"，生成不实信息 | 阶段四 |
| Token | — | LLM 处理文本的最小单元 | 全阶段 |
| Context Window | — | 模型一次能处理的最大 Token 数 | 阶段四 |

---

> ⬇️ 持续追加...
| @tool | — | 装饰器：将 Python 函数一键注册为 LLM 可调用工具，自动生成 Schema | 阶段三 |
| Middleware | — | 洋葱模型拦截器：在 Agent 调用前后插入逻辑 | 阶段三 |
| EventBus | — | 异步发布/订阅总线，解耦组件通信 | 阶段三 |
| Orchestrator | — | 状态机编排器：节点流 + 条件路由 + 回溯限流 | 阶段三 |
| Function Calling | — | OpenAI 的 tool use API，本质是 ReAct 的工程化实现 | 阶段三 |
| Onion Architecture | 洋葱模型 | 中间件分层设计：外层包装内层，请求层层进入、响应层层返回 | 阶段三 |
| OCP | Open-Closed Principle | 开闭原则：对扩展开放，对修改关闭 | 阶段三 |
| ReAct Loop | — | Agent 内嵌的多轮推理循环：LLM → tool → observation → LLM | 阶段三 |
| Pub/Sub | Publish/Subscribe | 发布/订阅模式：发布者和订阅者通过事件总线解耦 | 阶段三 |
