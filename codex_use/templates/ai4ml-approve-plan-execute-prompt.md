#AI4ML_APPROVE_PLAN

我批准当前 `output/plan.md`，请按计划执行完整 AI4ML 建模流程。

执行要求：

- 使用当前 workspace 的 `input/project_rules.md` 作为硬规则。
- 以用户确认后的 `output/plan.md` 为唯一执行方案。计划中的目标定义可能是单目标、多目标、多指标、衍生目标、非列名目标、无监督目标、分析型目标或混合任务，不要擅自收缩成单一 target column。
- 执行阶段必须使用原生 subagents 并行实验，除非你能明确说明任务太小不需要并行。
- 默认派发：
  - `baseline_worker`：负责数据切分、baseline 和基础指标。
  - `feature_model_worker`：负责主要特征工程和稳健模型路线。
  - `alternative_model_worker`：负责备选模型或备选特征路线。
- 如果首轮结果较弱或可疑，继续派发：
  - `diagnostics_worker`：诊断数据、目标、验证、泄漏、缺失、异常、特征质量和过拟合/欠拟合问题。
  - `optimization_worker`：基于诊断进行有限优化。
- 最终交付前派发只读 `validation_reviewer`，检查 `metrics.json`、`report.md`、`predict.py`、模型文件和报告结论是否一致、真实、可复现。
- subagent 只能写入 `work/subagents/{agent_name}/` 和 `output/logs/subagents/{agent_name}.md`。
- 最终用户可见产物只能由父 Codex 写入：
  - `output/metrics.json`
  - `output/overview.json`
  - `output/report.md`
  - `output/predict.py`
  - `state/artifact_index.json`
- 必须包含质量反馈闭环：baseline、验证集评估、效果诊断、有限优化、最终复核。
- 不得伪造指标、报告、模型或预测能力。
- 用中文持续说明进展，最终报告也使用中文。
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
- 最终 `output/report.md` 必须是详细业务和技术报告，不得只是简短摘要。
- 最终报告必须解释任务目标、默认假设、数据概况、数据清洗、切分方式、baseline、候选模型、subagents 实验、最终模型选择理由、指标含义、误差分析、诊断与优化、预测结果、产物使用方式、局限性和复现步骤。
- “产物”章节不能只列路径。必须逐项说明每个核心产物的用途、关键字段或内容、使用方式和适用边界，包括 `metrics.json`、`overview.json`、预测 CSV、`predict.py`、模型配置、最终建模脚本、subagent 日志和 `artifact_index.json`。
- 完成前必须自检 `output/report.md` 是否满足上述结构；如果不满足，先重写报告，再标记任务完成。

请执行到最终完成，并生成最终报告。
