# 🌍 旅游规划帝 · Agent 学习项目框架

> 从简单查天气到自主演进的旅游规划帝：一个项目，六次重写，逐层攻克 Agent 核心技术栈。

---

## 📐 项目总览

构建一个旅游助手 Agent，从命令行逐步进化到具备记忆、RAG、MCP 协议、GRPO 强化学习的智能系统。

核心能力：机票酒店查订、小众景点发掘、突发状况应对、账单多币种自动拆分。

---

## 🗺️ 演进路线图

| 阶段 | 对应章节 | 项目形态 | 核心技术 |
|------|---------|---------|---------|
| 阶段一 | 第四章 | 命令行 Agent V1.0 | ReAct / Plan-and-Solve / Reflection |
| 阶段二 | 第五、六章 | 多端旅游群聊 V2.0 | LangGraph / Coze&Dify / Multi-Agent |
| 阶段三 | 第七章 | 自研框架 V3.0 | 软件架构抽象、Tool 装饰器、Orchestrator |
| 阶段四 | 第八、九章 | 带记忆与 RAG 的 V4.0 | 向量检索、上下文裁剪、长期记忆 |
| 阶段五 | 第十章 | MCP 生态接入 V5.0 | MCP / A2A / ANP 协议 |
| 阶段六 | 第十一、十二章 | GRPO 微调 V6.0 | 强化学习奖励函数、LLM 训练、评估体系 |

---

## 📁 目录结构

`
My_Agent/
├── README.md                # ← 你在这里（项目框架总览）
├── docs/                    # 笔记与文档
│   ├── CHANGELOG.md         # 更新日志 & 问题记录 & 思考
│   ├── reading-notes.md     # 读书笔记 / 论文笔记
│   └── glossary.md          # 术语表
├── stages/
│   ├── stage1-handcraft/    # 手撕三大范式 (ReAct/P&S/Reflection)
│   ├── stage2-ecosystem/    # LangGraph / Multi-Agent
│   ├── stage3-self-framework/ # 自研框架
│   ├── stage4-memory-rag/   # 记忆 & RAG
│   ├── stage5-mcp-protocols/ # MCP / A2A / ANP
│   └── stage6-grpo-eval/    # GRPO 训练 & 评估
├── common/                  # 跨阶段共享工具
│   ├── base_agent.py
│   ├── tool_registry.py
│   └── utils.py
└── .gitignore
`

---

## 🛠️ 第一部分：经典范式与框架演进

### 阶段一：手撕三大核心范式 (Chapter 4)

**目标**：不依赖任何第三方 Agent 框架，纯手工实现智能体灵魂。

**项目形态**：简陋的命令行旅游助手。

**功能落地**：

- **ReAct 范式**：Thought → Action (调用天气API) → Observation → 循环
- **Plan-and-Solve 升级**：先生成全局规划，再逐天拆解执行
- **Reflection 反思纠错**：检测路线冲突，触发自我检查与重新规划

**深层技术点**：手写 while 循环状态机、硬核解析 LLM 结构化输出（JSON/Markdown Tag）

**技术栈**：Python + OpenAI API + 手写状态机 + json.loads()

---

### 阶段二：生态对齐与快速原型 (Chapters 5-6)

**目标**：看看工业界和开源社区怎么封装这些范式。

**项目形态**：从命令行升级为具备生产力的多端应用。

**两个子方向**：

| 方向 | 内容 | 成果 |
|------|------|------|
| 低代码搭建 | Coze/Dify 可视化编排 | Benchmark 基线 |
| 开源框架重构 | LangGraph StateGraph + AutoGen/AgentScope Multi-Agent | 状态图精控 + 多智能体协作 |

**技术栈**：LangGraph + AutoGen/AgentScope + Dify/Coze

**多智能体角色**：酒店专家 Agent / 本地土著 Agent / 财务精算 Agent

---

### 阶段三：自研框架破茧成蝶 (Chapter 7)

**目标**：脱离 LangGraph 等第三方框架，用自己写的框架运行旅游助手。

**项目形态**：自研 Agent 框架 V3.0。

**架构抽象**：
- Agent 基类（统一接口）
- Tool 装饰器（一键注册工具）
- Orchestrator 编排器（控制多 Agent 协作）
- EventBus 事件总线（解耦通信）

**深层技术点**：面向对象设计、中间件机制（日志/安全拦截）、动态工具加载

---

## 🧠 第二部分：高级知识扩展与硬核重构

### 阶段四：上下文工程与记忆存储 (Chapters 8-9)

**目标**：解决长途旅行中海量信息丢失与上下文爆炸。

**功能实现**：
- **记忆系统**：Redis 短期会话 + 向量数据库（Milvus/Qdrant）长期偏好
- **旅游 RAG**：导入小红书攻略、PDF 导览手册，构建知识库
- **情境理解**：上下文压缩与精简，精准指代消解

**技术栈**：Redis + Milvus/Qdrant + LlamaIndex/LangChain + Embedding 模型

---

### 阶段五：打破壁垒 —— 现代通信协议 (Chapter 10)

**目标**：让旅游助手连接全世界生态。

**功能实现**：
- **MCP 实战**：接入谷歌日历、Notion、本地文件系统
- **A2A/ANP 协议**：Agent 间跨平台直接对话与交易协商

**技术栈**：MCP SDK + A2A 协议 + ANP 协议

---

### 阶段六：终极进化 —— 算法与评估闭环 (Chapters 11-12)

**目标**：工程 + 算法双修，让模型更懂旅游。

**功能实现**：
- **GRPO 训练**：奖励函数设计（路线顺畅度 +5、超预算 -10、时间冲突 -50）
- **小模型自我博弈**：Qwen2.5 / Llama3-8B 的 "Aha Moment"
- **评估体系**：50 个高难度测试集、定量分析六阶段进化

**技术栈**：GRPO + PyTorch + DeepSpeed + 自定义 Reward Function

---

## 🗂️ 核心文档入口

| 文档 | 路径 | 说明 |
|------|------|------|
| 📋 更新日志 & 问题 & 思考 | [docs/CHANGELOG.md](docs/CHANGELOG.md) | **每次实践后必填** |
| 📖 读书/论文笔记 | [docs/reading-notes.md](docs/reading-notes.md) | 对应章节的心得 |
| 📚 术语表 | [docs/glossary.md](docs/glossary.md) | Agent 领域术语速查 |

---

## 🚩 开始学习

`ash
# 从阶段一开始
cd stages/stage1-handcraft
# 阅读对应章节第四章, 然后开始写代码
`

> 💡 **建议**：每完成一个阶段的实践，立刻在 docs/CHANGELOG.md 中记录更新日志、遇到的问题和你的思考。
