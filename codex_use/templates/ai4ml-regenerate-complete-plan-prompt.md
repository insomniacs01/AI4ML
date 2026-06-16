#AI4ML_REGENERATE_PLAN

请基于当前 AI4ML workspace 重新生成简短、清晰、可确认的执行计划，并同步生成机器可读执行策略。

要求：

- 使用当前 workspace 的 `input/project_rules.md`。
- 重新读取并理解用户已经选择的数据路径。该路径可以是任意文件或文件夹，不要假设一定是 CSV。
- 如果数据路径是文件夹，先梳理文件结构，识别可用数据文件、说明文档、元数据和已有结果；如果是文件，根据扩展名、文件签名、内容采样和可用库选择读取方式。
- 不要再把 single target column、task type、metric、prediction range 或 business objective 缺失作为直接 blocker。
- 预测或分析目标可能是单目标、多目标、多指标、衍生目标、非列名目标、排序、聚类、缺失补全、时间序列、报告分析或混合任务。不要假设只有一个 target column。
- 如果用户没有指定目标、主指标、成功阈值、最大改进轮数或第一轮候选模型，请基于数据自行推断一个合理的默认方案，并在 `output/plan.md` 中用“默认假设”清楚标注。
- 建模任务必须在执行前拥有确认后的成功标准。没有用户成功阈值时，Codex 必须推荐阈值或成功规则并等待人工确认；baseline 对比只能作为诊断参考，不能作为成功标准。
- `output/plan.md` 必须是用户确认用的短计划，不是长篇技术报告。使用且只使用这些顶层章节：
  - `# 执行计划`
  - `## 任务判断`
  - `## 执行策略`
  - `## 执行步骤`
  - `## 验收与改进规则`
  - `## 预期产物`
  - `## 需要用户确认`
- 简单和标准任务的 `执行步骤` 固定为 5 步：`任务与数据确认`、`数据检查与准备`、`模型训练或核心分析`、`评估与选择`、`产物生成`。每步写 2-4 个具体子项。
- 复杂任务最多 7 步，只能按需要插入 `探索分析` 和 `特征工程或任务专用处理`。
- 不要写长背景、机器学习常识、泛泛方法论、代码、依赖安装日志或最终报告式分析。
- Codex 必须选择一个执行策略，并在 `output/plan.md` 的“执行策略”中写明：
  - `light_tabular`
  - `standard_tabular`
  - `deep_tabular`
  - `custom_research`
- Iris 这类小型清晰表格分类/回归任务应选择 `light_tabular`，通常不启用 subagents，最多 1-2 个候选模型，不做大规模调参，报告保持简短。
- 同步写入合法 JSON 文件 `output/run_strategy.json`，字段必须包括：
  - `schema_version`
  - `strategy_id`
  - `complexity`
  - `task_type`
  - `target`
  - `decision_reason`
  - `execution_limits`
  - `acceptance`
  - `stop_rules`
  - `expected_artifacts`
- `execution_limits` 必须包含 `candidate_model_count`、`planned_models_or_methods`、`allow_subagents`、`planned_subagents`、`hyperparameter_search`、`report_depth`、`max_auto_improvement_rounds`、`min_meaningful_metric_improvement`、`advisor_after_failed_rounds`。
- `planned_models_or_methods` 表示人工确认后的第一轮模型或方法集合；若用户没有选择，Codex 推荐一个第一轮集合并等待确认。未确认的新模型只能通过 `output/improvement_plan.md` 再次请求。
- `output/run_strategy.json` 必须与 `output/plan.md` 的策略、模型数量、subagents、调参深度、报告深度和改进轮数保持一致。
- `验收与改进规则` 必须说明：成功标准以用户输入或 AI 推荐且被确认的阈值/规则为准；baseline 只用于诊断；自动改进达到上限、连续改进无明显提升或继续改进需要超出策略边界时，Codex 写入 `output/improvement_plan.md`，设置 `output/progress.json` 为 `waiting_improvement_review`，等待用户选择“继续改进”或“停止并生成报告”。
- 达到 5 轮或 `max_auto_improvement_rounds` 上限仍未达标时，必须请求用户重新指定计划。可建议调低成功阈值、增加未跑模型、改变特征或停止，但不得自动调低阈值继续执行。
- 如果策略允许在多次无效改进后请求顾问，必须在 `run_strategy.json.execution_limits.advisor_after_failed_rounds` 中写清触发轮数；顾问只读诊断输入为 `output/advisor_request.json`，输出为 `output/advisor_diagnosis.json`。
- 生成计划和 `run_strategy.json` 后，将 `output/progress.json` 设置为 `waiting_plan_approval`。
- 更新进度时必须追加 `state/progress_events.jsonl`，再更新 `output/progress.json` 快照；不要删除历史进度事件。
- `percent` / `progress_percent` 只能来自已有真实百分比、初始化阶段的 `percent: 0` 或任务完成状态；没有真实百分比时省略该字段或写为 `null`，不要填写固定猜测值。
- 只生成计划，不训练模型，不生成 `metrics.json`、`report.md` 或 `predict.py`。
- 用中文回复，并告诉用户计划文件路径、策略文件路径和下一步如何批准或修改计划。
