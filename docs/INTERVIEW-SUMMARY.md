# 旅游规划帝 Agent 项目面试总结

## 项目定位

这是一个多阶段演进的旅游助手 Agent 学习项目，目标不是简单封装一个聊天机器人，而是完整走一遍 Agent 工程从 Prompt 范式、图编排、自研框架、记忆与 RAG、协议接入，到强化学习评估闭环的升级路径。

项目当前可以作为面试展示版收尾：核心链路可离线运行，具备 Mock/Local 降级，测试覆盖六个阶段，并有阶段六 GRPO 奖励函数与 Benchmark 评估体系。

## 六阶段主线

| 阶段 | 核心能力 | 面试表达重点 |
|------|----------|--------------|
| 阶段一 | ReAct / Plan-and-Solve / Reflection | Agent 的三种基础推理范式与格式解析容错 |
| 阶段二 | LangGraph / Multi-Agent / FastAPI + SSE | 状态图编排、条件路由、流式事件输出 |
| 阶段三 | 自研 Agent 框架 | `@tool` schema 生成、BaseAgent 工具循环、EventBus、中间件、Orchestrator |
| 阶段四 | Memory + RAG | Redis 短期记忆、FAISS 长期偏好、BM25 + Dense 混合检索、上下文压缩 |
| 阶段五 | MCP / A2A / ANP | JSON-RPC 工具协议、Agent 谈判状态机、URI 路由、安全拦截 |
| 阶段六 | GRPO + Evaluation | 奖励函数、组内相对优势、clip policy loss、Benchmark 指标矩阵 |

## 我解决的关键问题

1. **LLM 输出不稳定**
   - 用 JSON 解析、Markdown code block 提取、ReAct 标签解析和 Mock 回归测试约束格式。

2. **Agent 流程容易失控**
   - 阶段二用 LangGraph 条件路由，阶段三用自研 Orchestrator 和 max rounds 控制循环。

3. **外部依赖影响演示**
   - API Key 缺失走 Mock；Redis 不可用自动降级到 LocalMemory；阶段六默认不下载大模型。

4. **RAG 检索中文效果不稳定**
   - 用字符级 TF-IDF bigram、BM25 + Dense 混合检索、FAISS 持久化和本地 data 文档集。

5. **只训练不评估无法证明进步**
   - 阶段六实现 `TravelRewardEngine`，统计格式合规率、幻觉率、时间冲突率、预算达标率，并扩展 50 条 Benchmark。

## 阶段六亮点

阶段六没有停留在“我想用 GRPO 微调模型”的口号，而是实现了可运行的算法底座：

- `TravelRewardEngine`
  - 非法 JSON：`-100`
  - 时间冲突：`-50`
  - 预算溢出：最高 `-10`
  - 路线顺畅：`+5`
  - 幻觉景点：按未知地点惩罚

- `GRPOTrainer`
  - 同一 prompt 采样 `G` 个候选
  - 组内 reward 标准化：`A_i = (R_i - μ) / σ`
  - 使用 ratio clip policy loss
  - 预留 DeepSpeed 初始化接口

- `TravelEvaluator`
  - 50 条结构化 Benchmark
  - 支持按 budget / days / scenario / difficulty 分桶统计
  - 输出阶段演进矩阵和 bucket 报告

## 测试与质量

当前基础测试结果：

```bash
pytest -q
# 43 passed, 6 warnings
```

重点测试覆盖：

- CLI：`--stage1`、`--stage3`、`--stage4`、`--stage5`、`--stage6`
- API：FastAPI TestClient，不启动真实 uvicorn
- RAG：使用 `data/` 本地文档检索成都、北京、三亚
- 阶段六：奖励函数、GRPO mock train_step、Benchmark 分桶评估
- 协议：MCP JSON-RPC、A2A 谈判 FSM、ANP URI 安全检查

## 可演示命令

```bash
python main.py --mock --stage1 --mode react
python main.py --stage3 --query "2人北京3天，预算3000"
python main.py --stage4 --memory local --query "我不吃辣，想去成都"
python main.py --stage5
python main.py --stage6
pytest -q
pytest tests/test_stage6_grpo.py -q
```

## 项目当前边界

- 阶段六默认只演示奖励与评估，不会真实下载 8B 模型训练。
- 真实 Redis、真实 API Key、真实大模型加载应作为 `integration` 测试单独执行。
- Benchmark 已有 50 条结构化用例，但还可以继续扩展到多城市、多季节、多用户画像。
- 覆盖率统计尚未强制接入 CI，可后续用 `pytest --cov=. --cov-report=term-missing` 补齐。

## 面试总结话术

这个项目的核心价值是：我不是只做了一个能聊天的旅游助手，而是把 Agent 系统从 Prompt 范式、工程编排、记忆检索、协议接入一路推进到强化学习评估闭环。  

其中我最想强调的是阶段六：我用规则奖励函数把旅游业务质量量化，再用 GRPO 的组内相对优势替代 Critic，最后通过 Benchmark 指标矩阵验证模型输出是否真的变好。即使不实际训练大模型，这套奖励与评估底座也能说明我理解“如何定义 Agent 的进步”。
