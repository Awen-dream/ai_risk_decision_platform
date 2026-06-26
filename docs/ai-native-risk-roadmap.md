# AI-Native 风控能力规划与推进方案

## 1. 目标

围绕 AI-Native 风控分析与运营闭环，建设一套可编排、可解释、可执行、可追踪的平台能力，打通以下系统：

- SQL 查询能力
- Dashboard 指标下钻能力
- 图谱关系分析能力
- 规则系统解释与调优能力
- 知识库检索与 SOP 能力
- 工单/案件协同能力

目标支持四类核心场景：

1. 风险调查：快速定位异常对象、影响范围、关键证据与处置建议。
2. 根因分析：从指标异常追溯到规则变更、图谱扩散、渠道波动、历史相似事件。
3. 策略解释：解释为什么命中、为什么放行、为什么建议调阈值，以及预计影响。
4. 运营协同：把分析结论沉淀为案件、任务、SLO 和执行记录，形成闭环。

## 2. 当前基础能力

当前仓库已经具备 AI-Native 风控平台的第一层骨架，不建议推倒重来。

### 2.1 已具备的能力

- Agent 编排骨架
  - `agents/copilot.py` 已能按意图编排 `investigation`、`strategy`、`graph`。
- 风险调查能力
  - `agents/investigation.py` 已接入 `metric_snapshot`、`case_lookup`、`order_profile`。
- 策略分析能力
  - `agents/strategy.py` 已接入 `strategy_profile`、`strategy_simulation`，并能联合图谱信号。
- 图谱分析能力
  - `agents/graph.py` 已支持实体关系、团伙风险、关键路径输出。
- 知识检索能力
  - `retrieval/knowledge_base.py` 与 `services/knowledge_sync.py` 已具备轻量知识库加载与检索能力。
- 案件/工作流能力
  - `services/case_service.py` 与 `api.py` 已支持 case 创建、状态流转、队列视图、指派与逾期统计。
- 决策与行动计划能力
  - `services/risk_decision.py` 已能把多 Agent 结果转为 `risk_decision` 和 `action_plan`。
- 工具接入骨架
  - `app.py`、`tools/registry.py`、`clients/http.py`、`clients/file.py` 已具备统一工具注册与多后端接入模式。

### 2.2 当前明显缺口

- SQL 能力缺口
  - 现有 “SQL” 主要停留在 `metric_snapshot` 的数据来源语义，尚无通用 SQL Agent/Tool。
- Dashboard 缺口
  - 缺少指标看板快照、维度 drill-down、异常对比视图的标准接口。
- 规则系统缺口
  - 现在有 `risk_decision_policy` 和策略画像，但缺少规则命中明细、规则版本、变更记录、解释链路。
- 工单系统缺口
  - 当前 `case` 是平台内工作流，尚未与真实工单系统双向同步。
- 根因分析缺口
  - 现有 Copilot 是多 Agent 汇总，尚未形成显式“根因候选 -> 验证 -> 排序”的推理链。
- 证据模型缺口
  - SQL、Dashboard、Graph、Rule、Knowledge、Ticket 的证据尚未统一成一个标准对象。
- 运营闭环缺口
  - 缺少“分析结论 -> 工单任务 -> 执行反馈 -> 知识沉淀 -> 策略优化”的学习回路。

## 3. 目标能力蓝图

建议把平台升级为四层结构。

### 3.1 交互层

- 风控 Copilot
  - 面向调查员、策略分析师、运营同学的自然语言入口。
- 调查工作台
  - 展示摘要、证据、图谱、规则解释、时间线、建议动作。
- 运营工作台
  - 展示案件池、任务队列、SLA、负责人、升级状态。

### 3.2 编排层

- Planner
  - 根据用户问题自动选择 SQL、Dashboard、Graph、Rule、Knowledge、Ticket 工具链。
- Executor
  - 统一执行工具调用，记录 trace、重试、降级与权限审计。
- Synthesizer
  - 合并多源证据，输出调查结论、根因判断、策略解释和行动建议。
- Memory
  - 记录会话、案件、分析上下文、处置结果和知识反馈。

### 3.3 能力层

建议新增或标准化以下工具能力：

- `sql_query`
  - 执行受控 SQL 模板查询，返回指标、样本、分群、明细。
- `dashboard_snapshot`
  - 获取 Dashboard 卡片、趋势、环比、同比、分层维度。
- `graph_relation`
  - 复用现有图谱能力，并增加路径解释与社区演化信息。
- `rule_explain`
  - 查询命中规则、规则版本、阈值、特征贡献、变更记录、Owner。
- `knowledge_search`
  - 复用现有知识检索，并补充 SOP、FAQ、历史复盘、案例模板。
- `ticket_create` / `ticket_update` / `ticket_search`
  - 对接工单系统，完成协同与回写。

### 3.4 数据与治理层

- 统一证据模型
  - 所有工具输出统一为 `evidence`、`finding`、`action`、`citation`、`artifact`。
- 审计与合规
  - 延续当前 `audit` 能力，补齐工具访问、数据来源、提示词、决策链留痕。
- 质量评估
  - 建立回答质量、根因命中率、工单采纳率、处置时效、误杀改善等指标。

## 4. 关键闭环设计

### 4.1 风险调查闭环

1. 用户输入问题，例如“巴西信用卡拒付率为什么上涨？”
2. Planner 自动调用：
   - `dashboard_snapshot` 看异常趋势
   - `sql_query` 看分层明细
   - `rule_explain` 看近期规则变更
   - `knowledge_search` 看 SOP 与历史案例
3. Synthesizer 输出：
   - 异常对象
   - 影响范围
   - 关键证据
   - 初步处置建议
4. 一键转案件或工单，进入执行队列。

### 4.2 根因分析闭环

1. 从指标异常生成根因候选：
   - 规则阈值变更
   - 某渠道流量结构变化
   - 团伙扩散
   - 上游模型漂移
2. 调用 SQL、规则、图谱、历史案例对候选根因逐条验证。
3. 输出根因排序、证据强度、反证信息与建议验证动作。
4. 根因结论沉淀为知识文档与复盘样板。

### 4.3 策略解释闭环

1. 查询订单/用户/策略上下文。
2. 解释：
   - 为什么命中
   - 哪些规则/特征贡献最大
   - 与历史相似对象相比有何差异
   - 调整阈值后的收益与风险变化
3. 若建议调参，则自动生成 shadow evaluation 任务。

### 4.4 运营协同闭环

1. 从 Copilot 输出结构化 `action_plan`。
2. 自动路由到案件队列或真实工单系统。
3. 跟踪：
   - SLA
   - 指派
   - 处理结果
   - 回执备注
4. 回写结果到知识库和策略评估样本，形成持续学习。

## 5. 与现有代码的对齐方案

建议在当前代码基础上增量推进，而不是另起炉灶。

### 5.1 Agent 层演进

- 保留现有 `knowledge`、`investigation`、`strategy`、`graph`、`copilot`。
- 新增 `root_cause` Agent
  - 负责根因候选生成、验证和排序。
- 增强 `copilot`
  - 不只编排“调查/策略/图谱”，还要支持“SQL/看板/规则/知识/工单”的动态规划。

### 5.2 Tool 层演进

在 `tools/registry.py` 的统一注册模型上新增以下工具：

- `sql_query`
- `dashboard_snapshot`
- `rule_explain`
- `ticket_search`
- `ticket_create`
- `ticket_update`

对应在 `adapters/`、`clients/`、`providers/` 中延续现有模式增加实现。

### 5.3 领域模型演进

建议扩展 `core/models.py`，新增或增强以下结构：

- `EvidenceRecord`
  - `source`
  - `source_type`
  - `summary`
  - `payload`
  - `confidence`
  - `observed_at`
- `RootCauseHypothesis`
  - `label`
  - `confidence`
  - `supporting_evidence`
  - `counter_evidence`
- `TicketSyncRecord`
  - `ticket_id`
  - `ticket_system`
  - `status`
  - `assigned_to`
  - `last_synced_at`

### 5.4 API 层演进

在 `api.py` 基础上建议增加：

- `POST /agents/root-cause`
- `POST /tools/sql/query`
- `POST /tools/dashboard/snapshot`
- `POST /tools/rules/explain`
- `POST /cases/{case_id}/tickets/sync`
- `GET /cases/{case_id}/evidence`

### 5.5 案件与工单协同演进

当前 `case_service` 已具备很好骨架，建议扩展：

- case 与 ticket 建立一对一或一对多映射
- action_plan 增加执行状态回流
- 记录外部工单链接、处理日志、升级记录

## 6. 分阶段推进路线

### Phase 1：统一证据与工具接入

目标：先把系统入口打通，形成基础可编排能力。

- 新增 SQL、Dashboard、Rule、Ticket 工具接口
- 统一工具输出协议
- 在 Copilot 中增加工具规划 trace
- 扩展 runtime capability contract

交付结果：

- AI 可以用统一方式访问六类系统
- 所有工具调用可追踪、可降级、可审计

### Phase 2：补齐根因分析与策略解释

目标：从“查数据”升级为“能解释、能判断”。

- 新增 `root_cause` Agent
- 补齐规则命中解释、策略版本对比、变更影响分析
- 让 SQL + Dashboard + Rule + Graph 联合生成根因排序

交付结果：

- AI 能给出结构化根因分析
- AI 能输出更强的策略解释与调优建议

### Phase 3：打通案件与工单闭环

目标：从“给建议”升级为“推动执行”。

- case 与工单系统双向同步
- 队列、指派、SLA、升级、回执纳入统一模型
- 将 Copilot 结论自动转任务

交付结果：

- AI 输出可直接进入运营执行
- 平台具备调查到协同的闭环

### Phase 4：建立持续学习与效果评估

目标：从“能用”升级为“越用越好”。

- 工单结果回写知识库
- 案件复盘自动生成知识文档
- 建立根因命中率、建议采纳率、策略收益等评估指标

交付结果：

- 平台具备自我迭代能力
- 风控经验可以规模化复用

## 7. 首批工程拆解建议

建议优先做一轮最小可落地版本，避免一次性铺得过大。

### 7.1 第一优先级

- 新增 `sql_query` 工具契约与 file/http 双实现
- 新增 `rule_explain` 工具契约与 mock/file 实现
- 新增 `dashboard_snapshot` 工具契约与 mock/file 实现
- 扩展 `copilot` 的 planner trace，显示为什么选择这些工具
- 扩展 `core/models.py`，引入统一 evidence 模型

### 7.2 第二优先级

- 新增 `root_cause` Agent
- 在 `case_service` 中增加 ticket sync 字段
- 在 `api.py` 增加 evidence 与 root cause 相关接口

### 7.3 第三优先级

- 对接真实工单系统
- 做 dashboard drill-down 与规则变更 diff
- 建立知识回写与复盘生成流程

## 8. 建议的成功指标

- 调查效率
  - 单次调查平均耗时下降
  - 人工跨系统查询次数下降
- 分析质量
  - 根因判断命中率
  - 策略解释采纳率
- 协同效率
  - 从发现到建单的时间缩短
  - SLA 超时率下降
- 业务结果
  - 风险捕获率提升
  - 误杀率下降
  - 策略迭代周期缩短

## 9. 建议的下一步

如果按“先规划再推进”的节奏，建议下一轮直接进入 Phase 1 的工程落地，按以下顺序实施：

1. 先补 `sql_query`、`dashboard_snapshot`、`rule_explain` 三类工具。
2. 再升级 `copilot`，让其具备动态工具规划和统一证据输出。
3. 然后补 `root_cause` Agent，把根因分析做成独立能力。
4. 最后再打通真实工单系统，形成完整运营闭环。

这条路径的好处是：

- 与现有代码结构最兼容
- 能最快做出可演示版本
- 风险最小，且每一阶段都能独立验收
