# 🌍 旅游规划帝 · Agent 学习项目框架

> 从简单查天气到自主演进的旅游规划帝：一个项目，六次重写，逐层攻克 Agent 核心技术栈。

---

## 📐 项目总览

构建一个旅游助手 Agent，从命令行逐步进化到具备记忆、RAG、MCP 协议、GRPO 强化学习的智能系统。

核心能力：机票酒店查订、小众景点发掘、突发状况应对、账单多币种自动拆分。

---

## 🗺️ 演进路线图

| 阶段 | 对应章节 | 项目形态 | 核心技术 | 状态 |
|------|---------|---------|---------|------|
| 阶段一 | 第四章 | 命令行 Agent V1.0 | ReAct / Plan-and-Solve / Reflection | ✅ |
| 阶段二 | 第五、六章 | 多端旅游群聊 V2.0 | LangGraph / Coze&Dify / Multi-Agent | ✅ |
| 阶段三 | 第七章 | 自研框架 V3.0 | 软件架构抽象、Tool 装饰器、Orchestrator | ✅ |
| 阶段四 | 第八、九章 | 带记忆与 RAG 的 V4.0 | 向量检索、上下文裁剪、长期记忆 | ✅ |
| 阶段五 | 第十章 | MCP 生态接入 V5.0 | MCP / A2A / ANP 协议 | ✅ |
| 阶段六 | 第十一、十二章 | GRPO 微调 V6.0 | 强化学习奖励函数、LLM 训练、评估体系 | ✅ |

---

## 📁 目录结构

```
Agent/
├── main.py                      # 统一入口 (--stage1~6 / --chat / --serve / --mock)
├── chat.py                      # 交互对话 (日程卡片 + 突发指令 + 记忆)
├── common/                      # 共享底座 (全阶段共用，随阶段增强)
│   ├── llm_client.py            # DeepSeek 客户端 (Mock模式 + 单例)
│   ├── base_agent.py            # Agent 基类
│   ├── tool_registry.py         # 工具注册器
│   ├── utils.py                 # JSON解析 / 上下文裁剪 / 序列化
│   └── tools/
│       └── travel_tools.py      # 7个旅游工具 + 数据源
├── agents/                      # Agent 实现 (逐阶段扩展，15个文件)
│   ├── stage1_react.py          # 阶段一: ReAct (while循环 + 正则解析)
│   ├── stage1_plan_solve.py     # 阶段一: Plan-and-Solve (三阶段分离)
│   ├── stage1_reflection.py     # 阶段一: Reflection (角色分离审查)
│   ├── stage2_state.py          # 阶段二: TravelState (TypedDict)
│   ├── stage2_nodes.py          # 阶段二: 4个 LangGraph 节点
│   ├── stage2_graph.py          # 阶段二: StateGraph 组装 + 条件路由
│   ├── stage2_multi_agent.py    # 阶段二: AutoGen 博弈 (财务-酒店谈判)
│   ├── stage3_framework.py      # 阶段三: 自研框架 (640行, 5大组件)
│   ├── stage3_travel.py         # 阶段三: 基于自研框架的旅游Agent
│   ├── stage4_memory.py         # 阶段四: 双轨记忆 (Redis+FAISS)
│   ├── stage4_rag.py            # 阶段四: 混合检索 (BM25+Dense+Rerank)
│   ├── stage4_compressor.py     # 阶段四: 指代消解 + 摘要压缩
│   ├── stage4_pipeline.py       # 阶段四: 上下文工程集成管道
│   ├── stage5_mcp.py            # 阶段五: MCP Client 桥接器 (JSON-RPC 2.0)
│   ├── stage5_a2a.py            # 阶段五: A2A 谈判协议 + ANP 路由器
│   └── stage6_grpo.py           # 阶段六: GRPO 奖励、训练循环、评估闭环
├── data/                        # 知识库文件 (阶段四增强)
│   ├── chengdu-food.md          # 成都美食攻略
│   ├── beijing-tips.md          # 北京旅游攻略
│   ├── sanya-beach.md           # 三亚海滩攻略
│   └── general-travel.txt       # 通用出行建议
├── api/                         # 接口层 (阶段二引入)
│   └── server.py                # FastAPI + SSE 流式
└── docs/                        # 文档
    ├── CHANGELOG.md             # 更新日志 & 问题记录 & 思考
    ├── INTERVIEW-CHALLENGES.md  # 面试官拷打点 (55题 + 27个真实Bug)
    ├── INTERVIEW-SUMMARY.md     # 面试展示版项目总结
    ├── reading-notes.md         # 读书笔记 (第4~12章)
    └── glossary.md              # 术语表
```

---

## 🛠️ 第一部分：经典范式与框架演进 ✅

### 阶段一：手撕三大核心范式 (Chapter 4)

**目标**：不依赖任何第三方 Agent 框架，纯手工实现智能体灵魂。

**功能落地**：

- **ReAct 范式**：Thought → Action (调用天气API) → Observation → 循环
- **Plan-and-Solve 升级**：先生成全局规划，再逐天拆解执行
- **Reflection 反思纠错**：检测路线冲突，触发自我检查与重新规划

**深层技术点**：手写 while 循环状态机、硬核解析 LLM 结构化输出（JSON/Markdown Tag）

**实现文件**：`agents/stage1_react.py` / `stage1_plan_solve.py` / `stage1_reflection.py`

```bash
python main.py --stage1              # 演示三种范式
python main.py --stage1 --mode react # 仅 ReAct
python main.py --mock --stage1       # Mock 模式（无需 API Key）
```

---

### 阶段二：生态对齐与快速原型 (Chapters 5-6)

**目标**：用 LangGraph StateGraph 替代手写循环，接入 AutoGen 增强多 Agent 协作。

**功能落地**：

| 能力 | 实现 |
|------|------|
| 状态图精控 | StateGraph + 4节点 + 条件路由 (超支→回退) |
| 多智能体协作 | 酒店专家 / 本地土著 / 财务精算 (同一 LLM + 不同 prompt) |
| AutoGen 博弈 | 超支时财务-酒店 GroupChat 直接谈判降价 |
| 生产级接口 | FastAPI + SSE 流式 + `/api/v1/plan` |

**实现文件**：`agents/stage2_state.py` / `nodes.py` / `graph.py` / `multi_agent.py`

```bash
python main.py                       # 阶段二 LangGraph CLI (默认)
python main.py --serve               # 启动 FastAPI → http://localhost:8000/docs
```

---

### 阶段三：自研框架破茧成蝶 (Chapter 7)

**目标**：脱离 LangGraph，用纯 Python 640 行实现同等的编排能力。

**五大组件**：

| 组件 | 行数 | 能力 |
|------|------|------|
| `@tool` 装饰器 | 40 | 反射函数签名 → 自动生成 OpenAI function-calling Schema |
| `BaseAgent` | 80 | ReAct 循环内嵌: LLM→工具→观察→LLM (max 5轮) |
| `EventBus` | 35 | 异步 pub/sub: `subscribe/emit` + `asyncio.gather` 并发分发 |
| `MiddlewarePipeline` | 50 | 洋葱模型闭包链: TokenCounter / SafetyFilter |
| `Orchestrator` | 120 | 状态机: 节点流 + 条件路由 + 回溯限流 (max_backtracks=3) |

**实现文件**：`agents/stage3_framework.py` (框架) + `stage3_travel.py` (业务)

```bash
python main.py --stage3              # 自研框架运行
python main.py --stage3 --query "..." # 自定义查询
```

---

## 🧠 第二部分：高级知识扩展与硬核重构

### 阶段四：上下文工程与记忆存储 (Chapters 8-9)

**目标**：解决长途旅行中海量信息丢失与上下文爆炸。

**功能实现**：
- **记忆系统**：Redis 短期会话 + FAISS 向量长期偏好
- **旅游 RAG**：支持 PDF/图片(OCR)/Markdown/TXT 全格式文档导入，混合检索(BM25+Dense)+重排
- **情境理解**：上下文压缩与精简，精准指代消解

**技术栈**：Redis + FAISS + BM25 + PyMuPDF + pytesseract + DeepSeek API

**实现文件**：`agents/stage4_memory.py` / `rag.py` / `compressor.py` / `pipeline.py`

**知识库文件**：`data/` 目录下放入 `.md/.txt/.pdf/.png` 即可自动加载

```bash
python main.py --stage4 --query "我不吃辣，想去成都，那里有什么好玩的"
python main.py --chat                     # 交互对话（日程卡片 + 突发指令）
python main.py --chat --memory local      # 零依赖本地记忆模式
```

---

### 阶段五：打破壁垒 —— 现代通信协议 (Chapter 10)

**目标**：让旅游助手连接全世界生态，拥抱 MCP 标准与 A2A 跨平台通信。

**功能实现**：

| 组件 | 行数 | 能力 |
|------|------|------|
| `MCPClientBridge` | 135 | JSON-RPC 2.0 握手 → tools/list 动态发现 → tools/call 代理执行 |
| 传输层抽象 | 200 | stdio / HTTP / Mock 三种传输，可插拔架构 |
| `NegotiationFSM` | 70 | A2A 谈判状态机: PROPOSE→COUNTER→ACCEPT/REJECT |
| `AgentNetworkRouter` | 130 | ANP URI 寻址 (`anp://ctrip.com/hotel-agent`) + EventBus 事件驱动 |
| `A2ASecurityMiddleware` | 60 | 反欺诈拦截：金额上限/黑名单/无效URI检测 |

**技术栈**：JSON-RPC 2.0 + MCP 协议 + A2A 谈判协议 + ANP 寻址 + WebSocket

**实现文件**：`agents/stage5_mcp.py` (425行) + `stage5_a2a.py` (534行)

```bash
python main.py --stage5              # MCP 工具发现 + A2A 谈判演示
```

**面试亮点**：
- MCP 桥接器严格遵循 JSON-RPC 2.0 标准（`jsonrpc: "2.0"`, `method`, `params`）
- ANP 路由器复用阶段三自研 `EventBus`，事件驱动跨平台 Agent 通信
- A2A 安全中间件预留反欺诈接口，可对接生产级风控

---

### 阶段六：终极进化 —— 算法与评估闭环 (Chapters 11-12)

**目标**：工程 + 算法双修，让模型更懂旅游。

**功能实现**：
- **GRPO 训练**：奖励函数设计（路线顺畅度 +5、超预算 -10、时间冲突 -50）
- **小模型自我博弈**：Qwen2.5 / Llama3-8B 的 "Aha Moment"
- **评估体系**：50 个高难度测试集、定量分析六阶段进化

**技术栈**：GRPO + PyTorch + DeepSpeed + 自定义 Reward Function

**实现文件**：`agents/stage6_grpo.py`

**核心组件**：
- `TravelRewardEngine`：合法 JSON 格式检查（非法 `-100`）、路线顺畅度 `+5`、预算溢出最高 `-10`、时间冲突硬拦截 `-50`
- `GRPOTrainer`：同 Prompt 组内采样 `G` 个输出，计算 `A_i=(R_i-μ)/σ` 相对优势，使用 ratio clip policy loss 更新策略
- `TravelEvaluator`：黄金 Benchmark 自动评估幻觉率、时间冲突率、预算达标率，并输出阶段一到阶段六的进化矩阵

```bash
python main.py --stage6                # 本地奖励引擎 + 离线评估演示，不下载模型
python main.py --stage6 --stage6-train # 加载模型执行一次 GRPO train_step
```

---

## 🗂️ 核心文档入口

| 文档 | 路径 | 说明 |
|------|------|------|
| 📋 更新日志 & 问题 & 思考 | [docs/CHANGELOG.md](docs/CHANGELOG.md) | 每次实践后必填，23个真实Bug记录 |
| 🔥 面试官拷打点 | [docs/INTERVIEW-CHALLENGES.md](docs/INTERVIEW-CHALLENGES.md) | 55道拷打题 + 27个Bug |
| 🎯 面试展示总结 | [docs/INTERVIEW-SUMMARY.md](docs/INTERVIEW-SUMMARY.md) | 六阶段主线、亮点、演示命令 |
| 📖 读书笔记 | [docs/reading-notes.md](docs/reading-notes.md) | 第4~12章心得 |
| 📚 术语表 | [docs/glossary.md](docs/glossary.md) | Agent 领域术语速查 |

---

## 🚩 快速开始

```bash
# 安装依赖
pip install openai langgraph autogen-agentchat autogen-ext fastapi uvicorn sse-starlette tiktoken redis faiss-cpu rank-bm25 PyMuPDF pdfplumber pytesseract Pillow torch transformers deepspeed

# 配置 DeepSeek API Key
export DEEPSEEK_API_KEY="sk-xxx"

# ⭐ 交互对话模式 (推荐)
python main.py --chat                     # 真实 API
python main.py --chat --mock              # Mock 模式
python main.py --chat --memory local      # 零依赖本地记忆

# 各阶段演示
python main.py --stage1 --mode react      # 阶段一: 手写范式
python main.py --query "2人北京3天"       # 阶段二: LangGraph (默认)
python main.py --stage3                   # 阶段三: 自研框架
python main.py --stage4                   # 阶段四: 记忆与RAG
python main.py --stage5                   # 阶段五: MCP + A2A 协议
python main.py --stage6                   # 阶段六: GRPO 奖励与评估闭环

# API 服务
python main.py --serve
# → 浏览器打开 http://localhost:8000/docs
```

> 💡 **建议**：每完成一个阶段的实践，立刻在 `docs/CHANGELOG.md` 中记录更新日志、遇到的问题和你的思考。面试前通读 `docs/INTERVIEW-CHALLENGES.md`。
