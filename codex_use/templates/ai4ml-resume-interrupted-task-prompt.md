#AI4ML_RESUME_INTERRUPTED_TASK

请继续执行当前被中断的 AI4ML 任务。

用户对改进确认的选择：

```text
{improvement_decision}
```

恢复要求：

- 不要创建新的 task workspace。
- 不要修改 Web Console 源码。
- 继续使用下面指定的现有 workspace。
- 先读取并理解现有协议文件和产物，再决定从哪里继续。
- 已经完成且产物可信的步骤不要无意义重跑；缺失、不完整、可疑或被中断的步骤需要继续执行或修复。
- 如果 `output/progress.json` 仍是 `interrupted`，请先追加 `state/progress_events.jsonl` 事件并更新快照为正在恢复或正在执行的状态。
- 更新进度时必须保留 `schema_version: "ai4ml-progress-v1"` 和 `events_path: "state/progress_events.jsonl"`；`percent` / `progress_percent` 只能保留或写入 Codex/AIOUR 执行体已有的真实百分比，没有真实百分比时省略该字段或写为 `null`，不要填写固定猜测值。
- 如果 `output/plan.md` 尚未被用户批准，必须回到等待计划确认，不要训练模型。
- 如果 `output/progress.json` 是 `waiting_improvement_review`，必须先读取 `output/improvement_plan.md`、`output/run_strategy.json`、`output/advisor_request.json` 和 `output/advisor_diagnosis.json`（如果存在），再按上方用户选择处理。
- 当用户选择为 `continue_improvement` 时，只能执行 `output/improvement_plan.md` 中已说明且被人工确认的继续改进方案；仍不得无边界增加模型、调参、subagents 或报告深度。若继续改进后仍无明显提升或需要再次超出边界，重新写入 `output/improvement_plan.md` 并设置 `waiting_improvement_review`，等待人工确认。
- 当用户选择为 `stop_and_report` 时，不再做新的模型训练、调参或数据重加工。基于当前 workspace 中最好的真实结果、真实失败原因和已完成诊断，生成 `output/metrics.json`（如已有真实结果）、`output/overview.json`、`output/report.md`、必要的 `state/artifact_index.json`，并在报告中说明“用户选择停止继续改进”。
- 如果没有改进确认选择，按普通中断恢复处理；不要把普通中断自动解释成继续改进许可。
- 如果计划已批准但执行未完成，请从未完成处继续，直至生成最终产物。

必须检查这些路径：

```text
{workspace_path}/input/task_request.json
{workspace_path}/input/project_rules.md
{workspace_path}/output/plan.md
{workspace_path}/output/run_strategy.json
{workspace_path}/output/progress.json
{workspace_path}/output/improvement_plan.md
{workspace_path}/output/advisor_request.json
{workspace_path}/output/advisor_diagnosis.json
{workspace_path}/output/metrics.json
{workspace_path}/output/overview.json
{workspace_path}/output/report.md
{workspace_path}/output/predict.py
{workspace_path}/output/code/
{workspace_path}/output/model/
{workspace_path}/output/logs/
{workspace_path}/work/
{workspace_path}/state/artifact_index.json
```

执行阶段要求：

- 继续遵守 `input/project_rules.md`。
- 继续遵守已确认的 `output/plan.md` 和 `output/run_strategy.json`。不得因为恢复任务而扩大模型数量、启用未确认 subagents、增加调参深度或把简短报告扩成详细报告。
- 用户可见沟通和最终报告使用中文。
- 需要建模或实验时只能使用 `output/run_strategy.json.execution_limits` 允许的原生 subagents；如果已有 subagent 输出，先读取再决定是否补派。
- 如果结果较弱、缺失或可疑，只能在策略允许的自动改进轮数和用户确认的改进方案内执行诊断和有限优化。
- 完成前必须做最终一致性检查，确保 `metrics.json`、`report.md`、`predict.py`、模型文件和 `artifact_index.json` 相互一致。
- 完成前必须生成或修复 `output/overview.json`。它是前端“概览”页的结构化数据来源，不能用 `output/report.md` 代替。
- `output/overview.json` 必须包含 `schema_version`、`generated_at`、`status`、`task_summary`、`prediction_error`、`confidence`、`key_factors`、`result_checks`、`optimization_records`、`charts`、`source_files`。
- `prediction_error`、`confidence`、`key_factors`、`result_checks` 和 `optimization_records` 必须只使用当前 workspace 中真实存在的指标、诊断、subagent 输出、预测文件、模型解释或复核结果。不得补写占位值、示例值、猜测百分比或泛化文案。
- 如果某项无法真实计算，保留字段，标量写 `null`，数组写 `[]`，并用中文说明缺失原因。
- `key_factors` 必须优先使用真实模型特征重要性；没有真实模型特征重要性时，只能返回明确标注来源为误差分析或诊断的因素，不能把普通占位项当成影响因素。
- `result_checks` 必须覆盖 baseline 对照、验证/测试切分、泄漏风险或不适用说明、产物一致性、预测入口可用性或不适用说明、数据质量。
- `optimization_records` 必须记录真实有限优化尝试；没有尝试则返回空数组，并在 `result_checks` 中说明。
- `state/artifact_index.json` 必须把 `output/overview.json` 记录为核心产物。
- 最终 `output/report.md` 必须匹配 `output/run_strategy.json.execution_limits.report_depth`，不能只列产物路径。

请从现有历史对话和 workspace 状态继续完成任务。
