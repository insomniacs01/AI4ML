#AI4ML_APPROVE_PLAN

我批准当前 `output/plan.md`，请按用户确认的计划和机器可读策略执行 AI4ML 建模流程。

执行要求：

- 使用当前 workspace 的 `input/project_rules.md` 作为硬规则。
- 在执行任何训练、模型比较、报告生成或预测入口创建前，必须读取：
  - `output/plan.md`
  - `output/run_strategy.json`
- `output/plan.md` 是用户确认过的人类可读执行计划；`output/run_strategy.json` 是用户确认过的机器可读执行边界。两者共同约束本次执行。
- 如果 `output/run_strategy.json` 缺失或不是合法 JSON，只能从当前已确认的 `output/plan.md` 中提取最保守的执行边界并先写入 `output/run_strategy.json`，然后再执行。不得借此扩大模型数量、启用 subagents、增加调参或扩展报告深度。
- 如果 `output/plan.md` 与 `output/run_strategy.json` 冲突，采用更保守的边界；如果目标定义、候选模型范围或是否启用 subagents 存在实质冲突，停止执行，更新 `output/progress.json` 为 `waiting_plan_approval`，说明需要用户重新确认，不要自行继续。
- 计划中的目标定义可能是单目标、多目标、多指标、衍生目标、非列名目标、无监督目标、分析型目标或混合任务，不要擅自收缩成单一 target column。
- 必须严格遵守 `output/run_strategy.json.execution_limits`：
  - 候选模型或方法数量不得超过 `candidate_model_count`。
  - 优先只使用 `planned_models_or_methods` 中列出的模型或方法。
  - `allow_subagents: false` 时不得启动 subagents。
  - `allow_subagents: true` 时，也只能使用 `planned_subagents` 列出的 subagents；没有列出则不要启动 subagents。
  - `hyperparameter_search` 为 `none` 时不得做调参；为 `small` 或 `bounded` 时只允许少量明确参数尝试；不得升级为无边界搜索。
  - 报告长度和细节必须匹配 `report_depth`。
  - 自动改进次数不得超过 `max_auto_improvement_rounds`。
  - 指标提升小于 `min_meaningful_metric_improvement` 时，视为无明显提升。
- 如果执行中发现需要超出已确认边界，例如新增更多模型、启用未批准的 subagents、扩大调参、改变目标定义或生成更深报告，必须停止当前扩展动作，写清楚原因，并把任务退回人工确认。不得直接继续。
- 对于 `light_tabular` 策略，应保持轻量执行：通常单父 Codex 流程、1-2 个候选模型、无 subagents、无大规模调参、简短报告、最多 1 轮自动改进。
- 对于 `standard_tabular` 策略，应保持普通执行：有限候选模型、有限诊断和有限改进，不得自动升级为深度建模。
- 对于 `deep_tabular` 或 `custom_research` 策略，也必须遵守策略中写明的模型数量、subagents、调参和改进轮数边界。
- 如果使用 subagents，subagent 只能写入 `work/subagents/{agent_name}/` 和 `output/logs/subagents/{agent_name}.md`。
- 最终用户可见产物只能由父 Codex 写入：
  - `output/metrics.json`
  - `output/overview.json`
  - `output/report.md`
  - `output/predict.py`
  - `state/artifact_index.json`
- 必须包含与策略匹配的质量反馈闭环：baseline 或合理对照、验证/测试评估、效果诊断、有限改进、最终复核。轻量任务的闭环应简短直接，不要扩展成多 agent 或长实验。
- 如果首轮结果未达到 `output/run_strategy.json.acceptance`，只能在 `max_auto_improvement_rounds` 内做有限改进。
- 如果自动改进轮数已用完、连续改进没有达到 `min_meaningful_metric_improvement`、或继续改进需要超出已确认策略边界，必须停止继续实验，并写入 `output/improvement_plan.md`，同时把 `output/progress.json` 设置为：

```json
{
  "schema_version": "ai4ml-progress-v1",
  "status": "waiting_improvement_review",
  "current_step": "waiting_improvement_review",
  "summary": "当前结果未满足验收或继续改进需要人工确认，等待用户选择继续改进或停止并生成报告。",
  "events_path": "state/progress_events.jsonl"
}
```

- 这里的 `percent` 只能保留当前已有的真实进度百分比；如果没有真实进度百分比，必须省略该字段，不得填写 72、80 或其他猜测值。
- 写入 `output/improvement_plan.md` 后必须停止，等待用户人工选择。不得在等待期间继续训练、增加模型、扩大调参或生成最终完成状态。
- `output/improvement_plan.md` 必须简短、可决策，使用这些章节：
  - `# 改进决策方案`
  - `## 当前结果`
  - `## 未满足验收的原因`
  - `## 已尝试的改进`
  - `## 顾问诊断`
  - `## 继续改进方案`
  - `## 停止并生成报告时的交付`
  - `## 需要用户选择`
- 如果同一问题连续两轮改进无明显提升，或策略允许的自动改进轮数已经用完但仍希望继续，必须先请求一个独立顾问诊断，再写入 `output/improvement_plan.md`。
- 顾问必须作为独立只读诊断角色运行，不能直接修改最终产物。优先使用原生 subagent `advisor_reviewer`，其输入为 `output/advisor_request.json`，输出为 `output/advisor_diagnosis.json`。如果当前策略禁止常规 subagents，仍只允许这个只读顾问在“多次改进无效后”触发，且必须在报告中记录触发原因。
- `output/advisor_request.json` 必须包含：`schema_version`、`trigger_reason`、`run_strategy`、`acceptance`、`current_metrics`、`baseline_metrics`、`improvement_attempts`、`suspected_causes`、`evidence_files`、`question_for_advisor`。
- `output/advisor_diagnosis.json` 必须包含：`schema_version`、`summary`、`root_causes`、`recommended_actions`、`actions_to_avoid`、`confidence`、`evidence_reviewed`。顾问建议不能自动扩大执行边界；如果采纳建议会超过已确认策略，仍必须进入人工确认。
- 不得伪造指标、报告、模型或预测能力。
- 用中文持续说明进展，最终报告也使用中文。
- 进度更新必须先追加 `state/progress_events.jsonl`，再更新 `output/progress.json` 快照。快照必须包含 `schema_version: "ai4ml-progress-v1"`、`events_path: "state/progress_events.jsonl"`、`status`、`current_step`、`summary` 和 `updated_at`。
- `percent` / `progress_percent` 只能来自 Codex/AIOUR 执行体明确写入的真实百分比、初始化阶段的 `percent: 0` 或任务完成状态；不得按任务状态、进度里程碑、步骤数量、证据文件或页面位置推导。等待人工确认、中断或暂停时保留已有真实百分比；没有真实百分比时省略该字段或写为 `null`，不得填写固定兜底值。
- 必须生成 `output/overview.json`，它是前端“概览”页的结构化数据来源，不能只生成最终报告。
- `output/overview.json` 必须是合法 JSON，字段只能来自真实数据、真实指标、真实诊断、真实 subagent 输出和真实产物；不得填写占位值、示例值、猜测百分比或装饰性文案。
- `output/overview.json` 必须包含以下顶层字段：
  - `schema_version`
  - `generated_at`
  - `status`
  - `task_summary`
  - `prediction_error`
  - `confidence`
  - `key_factors`
  - `result_checks`
  - `optimization_records`
  - `charts`
  - `source_files`
- `task_summary` 必须包含 `title`、`target`、`task_type`、`conclusion`、`recommendation`。
- `prediction_error` 必须包含 `primary_metric`、`value`、`display`、`split`、`lower_is_better`、`baseline_metric`、`baseline_name`、`interpretation`，并使用真实验证集、测试集、交叉验证或等价评估产物中的主指标。
- `confidence` 必须包含 `score`、`level`、`display`、`rationale`、`warnings`。`score` 是 0 到 1 的可信度评估，必须综合真实证据：验证/测试表现、baseline 对比、不同切分或分组稳定性、数据质量、样本覆盖、泄漏风险、目标定义清晰度和最终复核结果。证据不足时使用 `level: "unknown"` 和 `score: null`。
- `key_factors` 必须优先使用真实模型特征重要性、系数、permutation importance、SHAP 或等价解释结果。每项必须包含 `name`、`importance`、`display`、`source`、`is_model_feature_importance`、`direction`、`evidence`。如果模型没有真实特征重要性，只能返回明确标注为误差分析或诊断来源的因素，不能把“目标字段、数据完整度、样本规模、历史波动”等泛化占位项当成关键因素。
- `result_checks` 必须覆盖 baseline 对照、验证/测试切分、泄漏风险或不适用说明、产物一致性、预测入口可用性或不适用说明、数据质量。每项必须包含 `name`、`status`、`detail`、`evidence`。
- `optimization_records` 必须记录真实有限优化尝试，每项包含 `name`、`change`、`before_metric`、`after_metric`、`metric_name`、`result`、`detail`。如果没有优化尝试，返回空数组，并在 `result_checks` 中解释原因。
- `charts.actual_vs_predicted` 和 `charts.metric_series` 只能放真实抽样点或真实候选模型/迭代指标；没有就返回空数组。
- `source_files` 必须列出 `metrics`、`report`、`prediction_csv`、`feature_importance` 的相对路径或 `null`。
- 如果某个字段无法真实计算，字段仍要保留，标量值写 `null`，数组写 `[]`，并在 `interpretation`、`rationale`、`warnings`、`detail` 或 `evidence` 中解释原因。
- 最终 `output/report.md` 的深度必须匹配 `output/run_strategy.json.execution_limits.report_depth`：
  - `brief`：简短说明任务、数据、方法、主要指标、结论、限制和核心产物，不写长篇背景。
  - `standard`：正常说明任务目标、默认假设、数据概况、处理方式、验证方式、候选模型、最终选择、指标解释、限制和复现步骤。
  - `detailed`：在 standard 基础上增加更完整的误差分析、诊断、改进记录和产物使用边界。
- 报告的产物说明必须解释核心产物的用途和边界，但只说明本次真实生成的产物，不要列不存在的文件。
- 完成前必须自检 `output/report.md` 是否匹配已确认的 `report_depth`、真实产物和真实指标；如果不满足，先修正报告，再标记任务完成。

请执行到最终完成，并生成最终报告。
