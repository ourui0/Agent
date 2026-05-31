# 测试与评估报告

日期：2026-05-30

## 覆盖范围

本轮测试围绕“旅游规划帝 Agent 学习项目”的六阶段能力建立离线优先的 pytest 测试底座，避免依赖真实 DeepSeek API Key、Redis、外部网络和大模型下载。

## 新增测试文件

| 文件 | 覆盖内容 |
|------|----------|
| `tests/conftest.py` | 测试根路径、强制 Mock LLM、通用 registry 和 fixture 加载 |
| `tests/test_project_contract.py` | README 描述的核心目录结构、`main.py --help` CLI 参数覆盖 |
| `tests/test_common.py` | `LLMClient` Mock、`ToolRegistry`、JSON 提取、上下文裁剪 |
| `tests/test_tools_and_stage1.py` | 旅游工具 fallback、ReAct、Plan-and-Solve、Reflection |
| `tests/test_stage2_stage3.py` | TravelState、LangGraph 节点、预算回退路由、`@tool`、EventBus、Middleware、Orchestrator |
| `tests/test_stage3_travel.py` | 阶段三自研旅游 Agent 简单查询 smoke test |
| `tests/test_stage4_stage5.py` | LocalMemory、RAG 文档加载、ContextPipeline、MCP MockTransport、A2A FSM/Router/Security |
| `tests/test_stage6_grpo.py` | TravelRewardEngine、预算/时间/JSON 奖励、评估矩阵、mock GRPO train_step |
| `tests/test_cli.py` | `main.py` subprocess CLI 集成测试，含 stage1/stage3/stage5/stage6/chat local |
| `tests/test_api.py` | FastAPI TestClient，`/health`、`/api/v1/plan` 同步和 SSE |
| `tests/test_rag_integration.py` | 使用 `data/` 目录文档做成都/北京/三亚检索 |
| `tests/test_evaluation_pipeline.py` | 构造旅游规划样例，输出阶段六评估指标 |

## 新增测试数据

| 文件 | 内容 |
|------|------|
| `tests/fixtures/sample_queries.json` | 20 条旅游查询，覆盖单人、多人、家庭、预算、不吃辣、雨天、改签、紧急情况等 |
| `tests/fixtures/golden_answers.json` | 每条查询的最低可接受字段、城市、预算、偏好等约束 |
| `tests/fixtures/mock_tool_responses.json` | 天气、酒店、机票、景点、汇率、账单拆分 mock 数据 |
| `tests/fixtures/bad_llm_outputs.json` | 非法 JSON、缺 Action、错误工具名、无限循环倾向、幻觉工具调用 |

## 本轮修复

- `main.py` 新增 `--memory {redis,local}`，使 README 中的 `python main.py --chat --memory local` 可运行。
- `common/llm_client.py` 收紧 ReAct Mock 分支，避免 Plan-and-Solve / Reflection 被无条件第 2、3 轮 ReAct 回复污染。
- `common/llm_client.py` 增加 `"修改:"` 识别，使 Reflection 修正链路能在 Mock 模式下稳定触发。
- `agents/stage5_a2a.py` 将 `A2AMessage.timestamp` 从 `asyncio.get_event_loop()` 改为 `time.time()`，避免 Python 3.13 同步上下文中无 event loop 崩溃。
- `main.py --stage4` 在 Redis 不可用时自动降级到 `LocalMemoryManager`，并支持显式 `--memory local`。
- `agents/stage4_memory.py` 补齐 `LocalMemoryManager.inject_memory_to_prompt()`，保持本地记忆与 Redis 记忆接口兼容。
- `agents/stage6_grpo.py` 增加 bucket 级评估聚合与 Markdown 报告输出。
- 新增 `pytest.ini` 注册 `integration` / `slow` marker，隔离真实外部依赖测试。
- 新增 `docs/INTERVIEW-SUMMARY.md`，沉淀面试展示版说明。
- `README.md` 同步阶段六、文档题库数量和 `main.py --stage1~6` 描述。

## 测试结果

```bash
pytest -q
# 43 passed, 6 warnings in 7.21s

pytest tests/test_cli.py -q
# 7 passed

pytest tests/test_stage6_grpo.py -q
# 7 passed

pytest tests/test_api.py -q
# 3 passed
```

## 当前可运行状态

| 能力 | 状态 | 说明 |
|------|------|------|
| 阶段一 Mock CLI | 通过 | ReAct / P&S / Reflection 可离线跑 |
| 阶段二 API / LangGraph | 通过 | TestClient 同步和 SSE 均可跑 |
| 阶段三 CLI | 通过 | 无 API Key 时走降级/Mock 路径 |
| 阶段四单元能力 | 通过 | LocalMemory、RAG、压缩器可离线测 |
| 阶段四 CLI 默认模式 | 通过 | Redis 不可用时自动降级到 LocalMemory |
| 阶段五 Mock MCP/A2A | 通过 | 不依赖真实外部协议服务 |
| 阶段六奖励与评估 | 通过 | 默认不下载模型，训练路径可 mock |

## 已知失败 / xfail

当前基础测试无失败、无 xfail。

## 评估指标体系

| 维度 | 指标 |
|------|------|
| 功能正确性 | 查询字段是否正确解析、工具是否被调用、是否输出完整旅游计划 |
| 结构化输出质量 | JSON 合法率、字段完整率、API/前端消费便利性 |
| Agent 推理过程质量 | ReAct 是否有 Observation、P&S 是否先规划后执行、Reflection 是否发现并修正问题 |
| 旅游业务合理性 | 路线顺畅度、时间冲突率、预算达标率、偏好匹配率 |
| RAG 与记忆能力 | data/ 检索命中率、用户偏好复用率、无依据编造率 |
| 协议与框架能力 | MCP JSON-RPC 合规率、A2A 状态转换完整性、Orchestrator 条件路由正确性 |
| 鲁棒性 | API Key 缺失、Redis 缺失、外部服务不可用、LLM 格式错误、工具空结果 fallback |

## 潜在架构风险

- `stage3_travel.py` 的部分工具默认尝试真实高德 API，再 fallback；虽然测试可过，但离线演示耗时和日志噪声可能偏高。
- 当前测试以离线 Mock 为主，真实 Redis、真实 API Key、真实大模型训练仍应作为 optional integration test 单独隔离。
- `agents/__init__.py` 已改为懒加载，但仍需要在后续新增阶段模块时维护符号映射，避免 re-export 漂移。

## 项目质量评分

当前评分：88 / 100

理由：项目的六阶段主链路已经有离线测试覆盖，Mock/Local 设计基本可用，阶段四 CLI 已具备 Redis 缺失降级能力，阶段六 Benchmark 已扩展到 50 条结构化用例，并支持按 bucket 聚合评估。但真实 integration job、覆盖率门禁和训练路径 mock 深度仍有提升空间。

## 下一步优先修复 Top 5

1. 为真实 Redis、真实 API Key、真实模型加载补充 `integration` 测试样例，并默认从基础 CI 排除。
2. 增强 GRPOTrainer 的轻量 mock 训练断言，覆盖保存 checkpoint、梯度裁剪和异常奖励值。
3. 增加 pytest-cov 覆盖率统计，并把核心模块覆盖率目标设为 70% 起步。
4. 将阶段六 bucket 报告导出为 JSON + Markdown 文件，便于长期对比。
5. 把 `docs/INTERVIEW-SUMMARY.md` 与 README 入口互链，进一步提升项目可读性。

## 推荐命令

```bash
pytest -q
pytest tests/test_cli.py -q
pytest tests/test_stage6_grpo.py -q
pytest tests/test_api.py -q
pytest --cov=. --cov-report=term-missing
```
