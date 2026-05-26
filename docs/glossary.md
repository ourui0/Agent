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
