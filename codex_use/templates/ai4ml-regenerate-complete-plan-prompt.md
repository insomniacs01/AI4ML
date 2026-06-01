#AI4ML_REGENERATE_PLAN

请基于当前 AI4ML workspace 重新生成完整可执行方案。

要求：

- 使用当前 workspace 的 `input/project_rules.md`。
- 重新读取并理解用户已经选择的数据路径。该路径可以是任意文件或文件夹，不要假设一定是 CSV。
- 如果数据路径是文件夹，先梳理文件结构，识别可用数据文件、说明文档、元数据和已有结果；如果是文件，根据扩展名、文件签名、内容采样和可用库选择读取方式。
- 不要再把 single target column、task type、metric、prediction range 或 business objective 缺失作为直接 blocker。
- 预测或分析目标可能是单目标、多目标、多指标、衍生目标、非列名目标、排序、聚类、缺失补全、时间序列、报告分析或混合任务。不要假设只有一个 target column。
- 如果用户没有指定这些信息，请基于数据自行推断一个合理的默认方案，并在 `output/plan.md` 中明确写出：
  - 明确的目标定义：single-target、multi-target、multi-output、unsupervised、analysis-only 或 mixed。
  - 默认预测目标、分析目标或目标集合。
  - 默认选择的 `Metric`、目标字段、实体、时间范围、标签或衍生目标。
  - 默认预测范围。
  - 默认任务类型。
  - 默认评价指标。
  - 为什么这些默认选择合理。
  - 可选调整项。
  - 执行步骤。
  - 结果质量自检和优化闭环，包括 baseline、验证方式、效果不理想时的诊断和有边界优化策略。
  - 风险和限制。
- 生成完整计划后，将 `output/progress.json` 设置为 `waiting_plan_approval`。
- 只生成计划，不训练模型，不生成 `metrics.json`、`report.md` 或 `predict.py`。
- 用中文回复，并告诉用户计划文件路径和下一步如何批准或修改计划。
