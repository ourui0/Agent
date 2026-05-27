# 🔥 面试官拷打点 — 阶段一：手撕三大范式

> 面试官的思维：你说你手写了 ReAct，那我问你——你的 while 循环会不会死循环？P&S 的计划错了怎么办？Reflection 怎么定义"正确"？

---

## 一、ReAct 范式拷打

### Q1: 你的 while 循环终止条件是什么？会不会死循环？

**考察点**：工程健壮性

**你的防线**：
- 硬上限 `max_iterations`（默认 10）——超限直接返回"思考了 N 轮仍未得出结果"
- 每轮都检查是否命中 `Final Answer` 前缀
- 提示工程：system prompt 强制"每次只输出一个 Thought + 一个 Action"

**可能追问**：
- "如果 LLM 输出了一个不存在的工具名，怎么处理？" → `ToolRegistry.call()` 返回 `"错误: 未知工具 'xxx'"`，不抛异常，Agent 继续下一轮
- "如果 LLM 一直不输出 Final Answer，你的 10 轮上限够吗？" → 不够，但上限是 trade-off；ReAct 论文中平均 5-6 轮，10 轮是安全边际

### Q2: 你怎么解析 LLM 的输出？如果 LLM 返回格式不对怎么办？

**考察点**：解析器鲁棒性

**你的防线**：
- 正则匹配 `Thought:` / `Action:` / `Action Input:` / `Final Answer:` 四种模式
- `extract_json()` 兼容 ` ```json ``` ` 围栏和无围栏两种格式
- 解析失败时追加格式纠正提示："请严格按照格式输出..."

**可能追问**：
- "正则匹配 `Action:` 是贪婪还是非贪婪？" → `Action:\s*(\S+)` 是非贪婪（`\S+` 匹配到空白字符就停），防止把后续内容也吃进去
- "如果 Thought 跨多行你怎么处理？" → 当前用 `re.DOTALL` 支持跨行，但只取第一行；这其实是简化处理，真实场景应该提取从 `Thought:` 到下一个 `Action:` 之间的所有内容

### Q3: ReAct 和 Chain-of-Thought (CoT) 的本质区别是什么？

**考察点**：理论深度

**你的回答框架**：
- CoT 是"想完再说"——全程不调用外部工具，纯靠 LLM 内部推理（可能在脑子里编造数据）
- ReAct 是"边想边做"——推理过程中可以调用工具获取真实信息，Observation 反馈回 Thought，形成闭环
- 这也是为什么 ReAct 能显著降低幻觉：Observation 是 ground truth，不会被编造

### Q4: 为什么要做上下文裁剪（trim_context）？你裁剪的策略是什么？

**考察点**：上下文工程意识

**你的防线**：
- 随着循环进行，每轮都追加 Observation，消息列表线性增长 → 超出 context window 则截断/报错
- 策略：保留 system prompt + 最近 6 条观察 + 最后 2 条用户消息
- 估算方式：`总字符数 / 4 ≈ token 数`（中文约 1.5-2 char/token，英文约 4 char/token，取 4 是安全下界）

**可能追问**：
- "你为什么用 4 而不是 3.5 或 2？" → 4 是英文的保守估计，中文场景可以用 2；这里选择 4 是让裁剪更激进，宁可少保留也不让窗口溢出导致 API 报错

---

## 二、Plan-and-Solve 范式拷打

### Q5: 你的 Plan 是静态的——如果执行中发现新信息需要调整计划怎么办？

**考察点**：范式缺陷认知

**你的诚实回答**：
- 当前实现的 P&S 确实是静态的，Plan 生成后就不能改了
- 这是 P&S 范式本身的设计特点：优势是 token 高效，劣势是缺乏动态调整
- 如果要改进：在 solve 阶段检测执行结果是否与 plan 预期冲突，冲突时触发 replan（融合 ReAct 的灵活性）
- LangGraph 用 StateGraph + 条件边解决了这个问题——plan 不是一次性产物而是状态图中的节点

### Q6: Plan 里的工具名如果 LLM 瞎编了一个不存在的，你怎么处理？

**考察点**：防御性编程

**你的防线**：
- `_generate_plan()` 中逐条校验：`if action in self.tools.tool_names`，不存在的直接跳过并 warn
- 跳过的不影响其他有效步骤继续执行

**可能追问**：
- "跳过之后计划步骤序号就不连续了，会不会影响最终答案的质量？" → 会，这是 trade-off。另一种做法是让 LLM 重新生成 plan，但会增加 API 调用。当前选择"部分执行 > 完全失败"

### Q7: Plan-and-Solve 和 ReAct 的 Token 消耗对比？

**考察点**：成本意识

**你的回答**：
- **ReAct**：每轮都需要完整上下文（system + 历史 observation + 本次 prompt），N 轮 ≈ N × (上下文长度) 的 token
- **P&S**：plan 阶段 1 次调用（生成计划），solve 阶段每个工具 1 次调用（不需要 LLM），synthesis 阶段 1 次调用（综合结果）。总计 2+Ntool 次调用，但每次的上下文短得多
- 结论：工具调用次数相同的情况下，P&S 的 token 消耗约为 ReAct 的 30%-50%

### Q8: 如果 LLM 生成的 plan 遗漏了关键步骤（比如没查天气就直接推荐行程），你怎么兜底？

**考察点**：质量保障

**你的回答**：
- 当前实现没有"计划审核"步骤——这是 P&S 范式的一个已知弱点
- 一个改进方案：在 plan 和 solve 之间插入一个"plan reviewer"（类似 Reflection 的审查者角色）
- 这个 reviewer 可以用规则检查（必须包含天气/景点/住宿）或 LLM 检查

---

## 三、Reflection 范式拷打

### Q9: 你的 Reflection 怎么定义"错误"？反思标准是硬编码还是 LLM 自己判断？

**考察点**：评判机制设计

**你的防线**：
- 反思标准写在 `REFLECTOR_PROMPT` 中，是结构化的检查清单：路线逻辑 / 预算核对 / 完整性 / 一致性
- 审查者是另一个 LLM 调用（角色切换为"严格审查员"），不是规则引擎
- 这样做的好处是泛化性强，坏处是审查质量依赖 LLM 能力

**可能追问**：
- "如果审查员 LLM 自己也出错了（比如误判了一个正确的输出），怎么办？" → 多层防御：① 设置反思轮数上限（2-3 轮）；② 即使审查员误判，修正后的输出通常不会比原版更差（修正指令本身有纠偏效果）；③ 最终可引入人工审核

### Q10: Reflection 的"生成 → 反思 → 修正"和你直接在 Prompt 里要求"请仔细检查再回答"有什么本质区别？

**考察点**：范式本质理解

**你的回答**：
- "请仔细检查再回答"是一次性 self-correction，LLM 在同一个 context window 内自检——容易陷入"确认偏误"（自己写的自己很难找出问题）
- Reflection 范式是**角色分离**：生成者是"旅游助手"，审查者是"严格审查员"，两个角色两轮独立调用——审查员没有"作者偏见"
- 这类似于代码 review：自己 review 自己的代码 vs 另一个人 review，效果天差地别

### Q11: 多轮反思会不会产生"修正过拟合"——越改越差？

**考察点**：收敛性

**你的回答**：
- 会的，所以设置了 `max_iterations=2`（通常 2 轮足够）
- 每轮修正后重新审查，如果审查通过（verdict=PASS）则立即停止
- 如果 2 轮都没过，取最后一版输出（接受不完美 > 无限循环）
- 这也是 GRPO 等 RL 方法的动机：用奖励函数代替"审查员"，让模型学会在训练阶段就避免常见错误

---

## 四、架构设计拷打

### Q12: 你的 ToolRegistry 为什么不直接用 Python 的 `@tool` 装饰器（像 LangChain 那样）？

**考察点**：设计决策

**你的回答**：
- 阶段一的目标是"不依赖任何框架，理解底层原理"
- `ToolRegistry.register(func, name, description)` 是显式注册，比装饰器更透明——你能清楚看到注册了什么、什么时候注册的
- 阶段三（自研框架）才会实现 `@tool` 装饰器，那时你已经深刻理解了注册表内部的机制

### Q13: 三个 Agent 为什么都继承 BaseAgent 而不是各自独立？

**考察点**：OOP 设计 / 扩展性

**你的防线**：
- `BaseAgent` 提供统一接口（`run(query) → str`）+ 通用能力（history 记录、logging、reset）
- 阶段二换用 LangGraph 时，只需在 `_run_impl` 里调用 LangGraph graph，外部调用方无感知
- 阶段三自研框架的 Orchestrator 可以统一编排任何 BaseAgent 子类

### Q14: 你的 Mock 模式除了方便演示，还有什么深层价值？

**考察点**：工程思维

**你的回答**：
- Mock 模式的本质是**可复现的确定性测试**：LLM 输出是随机的，但 Mock 输出是确定的 → 你的 Agent 行为完全可预测
- 做回归测试时，Mock 可以覆盖各种边界情况（解析失败 / 工具不存在 / 超限循环）而不花 API 费用
- 面试中主动提到"我设计了 Mock 模式用于确定性测试"，比单纯说"我调了 OpenAI API"更能体现工程素养

### Q15: 如果要上线，你这套代码最大的风险是什么？

**考察点**：生产意识

**你的回答**：
- **解析器脆弱性**：正则匹配对 LLM 输出格式要求太高，生产环境中 LLM 的格式一致性远不如预期。建议在真实场景中使用 function calling（OpenAI）或 JSON mode 替代手写解析
- **错误处理不充分**：网络超时、API 限流、Token 超限等异常没有重试机制
- **成本不可控**：没有 token 预算管理，恶意输入可能导致无限循环消耗
- **安全**：没有 prompt injection 防护

---

## 五、Mock 运行时的真实 Bug 记录

| Bug | 现象 | 根因 | 修复 |
|-----|------|------|------|
| 目录导入失败 | `ModuleNotFoundError: No module named 'stages.stage1_handcraft'` | Python 模块名不允许连字符 `-` | 手动 `sys.path.insert` + 平级导入 |
| Prompt 模板 KeyError | `KeyError: 'results'` | `.format()` 把 `{results}` 误当占位符 | 改为 `{{results}}` 转义 |
| Mock 轮次错乱 | P&S plan 解析失败（拿到默认兜底回复） | 三个 Agent 共用 LLMClient，`_mock_turn` 未重置 | 增加 `reset_mock()` + 改为基于消息内容的匹配逻辑 |
| Mock 格式不匹配 | ReAct 解析器拿到 JSON 而非 `Thought:` 格式 | Mock 初版返回 JSON，解析器只支持 ReAct 标签格式 | 统一 Mock 输出格式为 ReAct 标签格式 |

---

> 📌 **面试心法**：面试官不期待你的代码完美无缺，他们期待你**知道自己代码的边界在哪里**。能清晰说出"这个设计在这里够用，在那里不够用"比写一个假装完美的方案更有说服力。

---

## 六、阶段二：LangGraph 多智能体拷打

### Q16: LangGraph 的 StateGraph 和普通的函数调用链有什么区别？为什么要用图？

**考察点**：框架选型理由

**你的防线**：
- 普通函数调用链是**线性**的：A→B→C→D，一旦顺序定了就不能改
- StateGraph 用**条件路由**：financial 判定超支 → 自动跳回 hotel_expert，不超支 → 直接 END
- 这本质上是把阶段一的 while 循环 + if/else **形式化**：路由逻辑从"人写在代码里"变成"图结构显式声明"

**可能追问**：
- "那你为什么不继续用 while 循环？" → 图结构带来三个工程收益：① 检查点/断点恢复（MemorySaver）② 流式输出（`.stream()` 天生支持 SSE）③ 可视化（LangGraph Studio 能生成图）

### Q17: 你的酒店专家和财务精算师是同一个 LLM 吗？为什么不拆成两个实例？

**考察点**：多 Agent 设计权衡

**你的防线**：
- 是同一个 DeepSeek 模型，通过不同的 system prompt 实现角色切换
- 原因：① 两个 LLM 实例互相聊天 token 消耗翻倍 ② DeepSeek 按 token 计费 ③ "一个成熟 Agent 的系统 prompt 切换 > 两个不成熟 Agent 互相扯皮"
- AutoGen 的博弈仅用于**超支谈判**这个窄场景，有 max_messages=8 硬上限

### Q18: 你的 max_revisions=3 是怎么定出来的？为什么不是 2 或 5？

**考察点**：工程 trade-off

**你的防线**：
- 2 太少：低预算场景可能还没降到底就被截断
- 5 太多：浪费 token + 可能死循环（酒店已是最低价，无限重复选同一家）
- 3 是经验值，配合"已达最低价也停止"的兜底逻辑

### Q19: LangGraph 的 `add_messages` reducer 是什么？不用它会怎样？

**考察点**：框架细节

**你的防线**：
- StateGraph 默认对 TypedDict 字段是**覆盖**语义（新值替换旧值）
- `logs: Annotated[List[str], add_messages]` 显式声明**追加**语义（每个节点的日志累积而非覆盖）
- 不用的话：每个节点执行后，`logs` 只剩最后一条记录

### Q20: 你的节点函数返回 `dict` 而不是完整 State，LangGraph 怎么知道该更新哪些字段？

**考察点**：StateGraph 机制

**你的防线**：
- LangGraph 节点接收完整 State，但**只需返回变化的部分**（partial update）
- 框架自动将返回的 dict 合并回 State（对 TypedDict 字段是覆盖/追加，取决于 reducer）
- 这意味着节点之间是**松耦合**的：local_guide 不需要知道 hotel_expert 的字段定义

| Bug | 现象 | 根因 | 修复 |
|-----|------|------|------|
| 目录导入失败 | `ImportError: attempted relative import` | 目录名含 `-`，Python 无法识别为 package | 平级绝对导入 |
| Prompt 拼写 | `KeyError: 'ciy'` | 模板写了 `{ciy}` | 改为 `{city}` |
| JSON 解析失败 | 返回 `json_parse_failed` | DeepSeek 偶尔在 JSON 前加文字 | 宽松正则 + 节点兜底 |
| add_messages | 日志被覆盖 | 忘记声明 reducer | `Annotated[List, add_messages]` |
| API Key 缺失 | `OpenAIError: Missing credentials` | 阶段二未做 Mock 降级 | `export DEEPSEEK_API_KEY` |

### Q21: 为什么不把酒店/景点数据换成真实 API？

**考察点**：工程节奏

**你的回答**：
> "阶段二的目标是流程编排——LangGraph 的图结构、条件路由、多角色协作。Mock 数据让回归测试可复现、零延迟。阶段四 RAG + 阶段五 MCP 才是我接入真实数据源的时机，那时候 ToolRegistry 保证工具可替换，Agent 编排逻辑零改动。"

---

## 七、阶段三：自研框架拷打

### Q22: 你为什么要脱离 LangGraph 自研框架？这不是重复造轮子吗？

**考察点**：工程决策的理性分析

**你的防线**：
- 不是重复造轮子，而是**理解轮子的构造**。LangGraph 的核心就是 StateGraph + ConditionalEdges + Checkpointer，三样加起来本质是：状态字典 + 节点函数 + 路由规则 + 存档。手写一遍后你对 LangGraph 的依赖不再是"黑盒调用"，而是"我知道里面怎么做的，用你是为了方便"。
- 另外，自研框架只有 640 行，LangGraph 依赖链超过 10 个包。对于只需要 4 节点 + 条件路由的场景，引入 LangGraph 是过度工程。
- **面试加分点**："我先用 LangGraph 验证了编排模式的可行性，然后自研了一个 640 行的轻量替代——这证明我不是只会调 API。"

### Q23: 你的 @tool 装饰器和 LangChain 的 @tool 有什么区别？

**考察点**：原理理解

**你的防线**：
- 核心原理一样：`inspect.signature` + `get_type_hints` → 生成 OpenAI function-calling JSON Schema
- 区别在于：我的只有 40 行，没有 LangChain 的 Pydantic 模型嵌套、异步包装、Runnable 链路等额外抽象
- 面试时正确回答："原理上都是反射 + Schema 生成，但我的实现只做一件事——把 Python 函数变成 LLM 可调用的 JSON 描述，没有额外的抽象负担。"

### Q24: EventBus 和 Python 标准库的 `signal` 模块有什么区别？

**考察点**：设计选择

**你的防线**：
- `signal` 是进程级的同步机制，不能跨协程
- EventBus 是应用级的异步 pub/sub——`asyncio.gather` 并发执行所有回调，单个失败不影响其他
- 实际应用：FastAPI SSE 监听 `node:complete` 事件 → 推送给前端；日志系统监听同一个事件 → 写文件。两个监听器完全解耦。

### Q25: MiddlewarePipeline 的洋葱模型是怎么实现的？为什么用闭包而不是递归？

**考察点**：实现细节

**你的防线**：
- 闭包链式包装：`MiddlewarePipeline.__call__` 从后往前遍历 middlewares，每一层生成一个 `async def wrapped(state): return await mw(state, inner)` 闭包
- 执行顺序：`M1.before → M2.before → Agent → M2.after → M1.after`
- 为什么不用递归：闭包只需要构造一次链，后续调用是扁平调用栈，在 async 场景下比递归更安全（避免栈溢出 + 更好的错误追踪）

**可能追问**：
- "如果中间件抛出异常，后面的中间件和 Agent 还会执行吗？" → 不会，异常会沿闭包链向上冒泡，但 `Orchestrator.run()` 有 try/except 兜底，单个节点崩溃不会导致整体编排失败

### Q26: Orchestrator 的条件回溯和 LangGraph 的 ConditionalEdges 有什么异同？

**考察点**：核心能力对比

**你的防线**：
- 同：都是"当前节点 → 路由函数(状态) → 下一个节点"的决策模式
- 异：LangGraph 用编译后的图结构（边是编译时确定的），Orchestrator 用运行时的 `_order` 列表 + `pos` 指针（边是运行时跳转的）
- 回溯计数：LangGraph 需要手动在 state 里维护 `revision_count`；Orchestrator 内置 `_backtrack_count` 字典，与 `max_backtracks` 配合自动限流

### Q27: BaseAgent 的 `__call__` 内部为什么需要 ReAct 循环？不能只调一次 LLM 吗？

**考察点**：function-calling 原理

**你的防线**：
- OpenAI 的 function-calling 不是"一次调用返回结果"，而是"一次调用返回工具选择 + 再次调用获取最终答案"
- 正确流程：`LLM(tools) → tool_calls → 执行工具 → 追加 tool result → LLM → 文本答案`
- 我的 `__call__` 内部有 `for turn in range(max_turns)` 循环，每轮检测 `msg.tool_calls`，执行后自动追加到 messages 继续下一轮——这就是 ReAct 的最小实现
- 面试加分：能说出 "function-calling 本质是 ReAct 的一种工程化实现"——Thought 隐式在 tool_calls 选择中，Action 是工具调用，Observation 是 tool role message

### Q28: 你的框架 640 行，LangGraph 上万行，差在哪里？

**考察点**：工程边界认知

**你的防线**：
- **检查点/持久化**：LangGraph 有 SQLite/Postgres checkpointer，我的 MemorySaver 目前只存内存
- **流式输出**：LangGraph 有 `.stream()` / `.astream_events()` 多种模式，我需要自己包装
- **图可视化**：LangGraph Studio 能生成流程图，我没有
- **错误恢复/重试**：LangGraph 有内置 retry policy，我的只有外层 try/except
- **并发安全**：LangGraph 的 channel-based state 更新支持并行节点，我的 Orchestrator 是顺序执行
- **关键认知**：640 行覆盖了核心编排能力的 80%，剩下的 20% 是生产级工程细节。选型取决于场景——4 节点旅游规划用自研够用，50 节点复杂流程用 LangGraph

---

| Bug | 现象 | 根因 | 修复 |
|-----|------|------|------|
| function-calling 单步 | 工具结果未反馈给 LLM | `__call__` 只调一次 LLM | 改为 ReAct 循环 max_turns=5 |
| Pipeline final_handler | TypeError: None | 构造时 Agent 未注入 | `run()` 前检查并注入 |
| EventBus 回调混用 | async/sync 混用报错 | 未检测回调类型 | `iscoroutinefunction` 分支处理 |
