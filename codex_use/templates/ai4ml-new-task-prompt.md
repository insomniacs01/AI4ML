#AI4ML_NEW_TASK

You are starting an AI4ML Codex-native workspace initialization task.

Default language rule:

- Use Chinese for all user-facing communication and artifacts.
- Keep professional names, model names, metric names, field names, file names, code identifiers, library names, commands, and original error messages in their original form when appropriate.
- `output/plan.md`, `output/report.md`, `state/questions.json`, and explanatory values in `output/progress.json` must be written in Chinese by default.

Create a new task workspace under the current project directory. Do not modify the Web Console source code unless the user explicitly asks for source-code changes.

Required workspace location:

```text
workspaces/{task_id}/
```

Choose `{task_id}` yourself using a stable, readable timestamp-based name such as `ai4ml-YYYYMMDD-HHMMSS`.

Create this directory structure:

```text
workspaces/{task_id}/
  input/
  work/
    code/
    notebooks/
    scratch/
  output/
    code/
    model/
    logs/
  state/
```

Write these initial protocol files:

```text
workspaces/{task_id}/input/task_request.json
workspaces/{task_id}/input/project_rules.md
workspaces/{task_id}/output/plan.md
workspaces/{task_id}/output/progress.json
workspaces/{task_id}/state/artifact_index.json
```

The initial `task_request.json` should record that this is a newly initialized AI4ML Codex-native task workspace and that the selected data path and user task description are the authoritative task input when they are provided.

The initial `project_rules.md` must define these rules:

- Codex is the only execution engine.
- User-facing communication and artifacts must use Chinese by default, except for professional names, field names, code identifiers, commands, and original technical text.
- User-visible results must be written under `output/`.
- Do not fabricate model metrics, leaderboards, reports, or prediction support.
- Do not create Python virtual environments such as `.venv`, `venv`, or `env` inside the task workspace, `work/`, `output/`, or subagent directories. Prefer the project-level Python environment or an existing system Python interpreter.
- If extra dependencies are needed, record them in a workspace requirements file or in the report reproduction steps. Do not repeatedly install a full dependency environment under each subagent directory.
- Do not include reproducible dependency directories, pip caches, temporary install directories, or virtual environments as final artifacts in `output/` or `state/artifact_index.json`.
- `output/plan.md` is required before model execution.
- After receiving a data path, Codex must first inspect whether it is a file or directory, understand its content and structure, then generate or update `output/plan.md`.
- The selected data path may be any file or directory. Do not assume CSV. For a directory, inventory the contained files, identify likely datasets, metadata, documentation, and existing outputs. For a file, choose the reader based on extension, file signature, content sampling, and available libraries.
- The task target may be a single column, multiple columns, multiple indicators, derived targets, non-column objectives, ranking targets, clustering groups, missing-value completion, forecasting ranges, report-only analysis goals, or a mixed workflow. Do not assume there is exactly one `target column`.
- The plan must be a complete executable proposal, not a list of questions. If the user did not fully specify target definition, task type, metric, prediction range, or business objective, Codex must infer reasonable defaults from the data and task description, clearly label them as "默认假设", and build the plan around those defaults.
- For ambiguous multi-indicator or multi-file tasks, Codex must select a defensible default modeling target, analysis target, or target set from the data, explain why it was chosen, and include alternative options in a "可选调整" section. Do not stop only because multiple choices exist.
- `output/plan.md` must include an explicit "目标定义" section describing whether the task is single-target, multi-target, multi-output, unsupervised, analysis-only, or mixed, and which fields, entities, time ranges, labels, or derived objectives are involved.
- After generating the complete default plan, Codex must set `output/progress.json` to `waiting_plan_approval` and stop.
- Codex must not train models, run model comparison, create `output/metrics.json`, create `output/report.md`, or create `output/predict.py` until the user explicitly approves the plan.
- During the execution stage after plan approval, Codex must use native subagents for parallel experimental work unless the task is clearly too small or the user explicitly requests single-agent execution.
- Execution-stage subagents should normally include `baseline_worker`, `feature_model_worker`, and `alternative_model_worker`. If results are weak or suspicious, add `diagnostics_worker` and `optimization_worker`. Before final delivery, add a read-only `validation_reviewer`.
- Subagents must not write final user-visible artifacts directly. Subagents may write only under `work/subagents/{agent_name}/` and `output/logs/subagents/{agent_name}.md`. The parent Codex must read subagent outputs, choose and merge the result, and write final `output/metrics.json`, `output/overview.json`, `output/report.md`, `output/predict.py`, and `state/artifact_index.json`.
- The parent Codex must record which subagents were used, what each tried, and which result was selected in `output/report.md` or `output/logs/subagents/summary.md`.
- After the user approves execution, Codex must include a result-quality feedback loop: establish a baseline, evaluate the first modeling result on an appropriate validation split, diagnose weak performance or suspicious results, then make bounded fixes or optimization attempts before finalizing.
- If performance is not satisfactory, Codex must inspect likely causes such as data leakage, target definition, missing values, feature quality, class imbalance, time split mistakes, insufficient samples, inappropriate metric choice, or model underfitting/overfitting. Codex must then revise features, validation, preprocessing, model choice, or task framing when justified.
- Codex must not endlessly optimize. It should stop after a reasonable bounded number of improvement attempts, record what was tried, and clearly explain remaining limitations in `output/report.md`.
- If the user revises the plan, update `output/plan.md` and keep waiting for approval unless the user explicitly asks to execute.
- If the user asks to regenerate the plan, regenerate `output/plan.md` and keep waiting for approval.
- `output/progress.json` must reflect the current task state.
- `output/metrics.json` is required only after a real modeling result exists.
- `output/overview.json` is required after a real modeling result or clear terminal failure exists. This file is the structured source for the Web Console overview page; `output/report.md` is not a substitute for it.
- `output/report.md` is required only after there is a meaningful result or a clear failure explanation.
- Final `output/overview.json` must be valid JSON and must contain only values grounded in actual data, metrics, diagnostics, subagent outputs, generated artifacts, or explicit user instructions. Do not use placeholder values, decorative examples, or guessed percentages.
- Final `output/overview.json` must use this schema:

```json
{
  "schema_version": "1.0",
  "generated_at": "ISO-8601 timestamp",
  "status": "completed | failed | partial",
  "task_summary": {
    "title": "中文任务标题",
    "target": "真实目标字段、指标、实体或任务对象；没有则写明",
    "task_type": "regression | classification | forecasting | clustering | analysis | mixed | other",
    "conclusion": "一句中文结论，说明结果是否可用以及最重要的注意事项",
    "recommendation": "一句中文建议，说明下一步应该看报告、复核数据、谨慎使用或重新定义任务"
  },
  "prediction_error": {
    "primary_metric": "真实主指标名称，例如 signed_log_mae、rmse、accuracy、macro_f1",
    "value": 0.0,
    "display": "面向用户的指标展示文本",
    "split": "validation | test | cross_validation | holdout | full_data | not_applicable",
    "lower_is_better": true,
    "baseline_metric": 0.0,
    "baseline_name": "真实 baseline 名称；没有则为 null",
    "interpretation": "用中文解释这个误差/分数意味着什么"
  },
  "confidence": {
    "score": 0.0,
    "level": "high | medium | low | unknown",
    "display": "高 / 中 / 低 / 未知",
    "rationale": "基于验证集/测试集表现、baseline 对比、数据质量、样本覆盖、泄漏风险、稳定性等真实证据解释可信度",
    "warnings": ["真实风险提示；没有则为空数组"]
  },
  "key_factors": [
    {
      "name": "真实影响因素或特征名",
      "importance": 0.0,
      "display": "面向用户的展示文本",
      "source": "例如 model_feature_importance、permutation_importance、coefficient、shap、error_analysis、diagnostics",
      "is_model_feature_importance": true,
      "direction": "positive | negative | mixed | unknown",
      "evidence": "为什么它影响结果，必须来自真实模型解释、误差分析或诊断"
    }
  ],
  "result_checks": [
    {
      "name": "baseline_comparison | validation_split | leakage_check | artifact_consistency | prediction_entrypoint | data_quality | custom",
      "status": "passed | warning | failed | not_applicable",
      "detail": "中文检查结论",
      "evidence": "对应指标、文件或检查依据"
    }
  ],
  "optimization_records": [
    {
      "name": "优化尝试名称",
      "change": "做了什么改动",
      "before_metric": 0.0,
      "after_metric": 0.0,
      "metric_name": "指标名称",
      "result": "improved | no_change | worse | not_comparable",
      "detail": "中文说明"
    }
  ],
  "charts": {
    "actual_vs_predicted": [
      { "x": "样本或时间标签", "actual": 0.0, "predicted": 0.0 }
    ],
    "metric_series": [
      { "label": "候选模型或迭代名称", "value": 0.0 }
    ]
  },
  "source_files": {
    "metrics": "output/metrics.json",
    "report": "output/report.md",
    "prediction_csv": "真实预测 CSV 路径；没有则为 null",
    "feature_importance": "真实特征重要性文件路径；没有则为 null"
  }
}
```

- If a field cannot be truthfully computed, keep the field present but set scalar values to `null`, arrays to `[]`, and explain the reason in `interpretation`, `rationale`, `warnings`, `detail`, or `evidence`. Never fill unknown fields with generic text such as "大多数情况较为准确" or fake percentages.
- `prediction_error` must use a real validation/test/cross-validation metric from `output/metrics.json` or an equivalent metric artifact. Prefer the metric used to select the final model; for regression with extreme values, prefer the metric explicitly justified in the report.
- `confidence.score` must be a calibrated 0-1 assessment derived from real evidence, not a transformed metric by itself. Consider validation/test performance, improvement over baseline, stability across splits or groups, data quality, sample size, leakage risk, target ambiguity, and artifact validation. If the evidence is insufficient, use `level: "unknown"` and `score: null`.
- `key_factors` must contain true model-derived feature importance whenever the final model supports it. If model-derived feature importance is unavailable, use diagnostic/error-analysis factors only if they are clearly labeled with `is_model_feature_importance: false` and `source: "error_analysis"` or `source: "diagnostics"`.
- `result_checks` must include checks for baseline comparison, validation/test split, leakage risk where relevant, artifact consistency, and prediction entrypoint availability when a prediction entrypoint is expected.
- `optimization_records` must summarize real bounded optimization attempts and metric changes. If no optimization was needed or attempted, return an empty array and explain that in a `result_checks` item.
- The `state/artifact_index.json` file must include `output/overview.json` as a core artifact when it exists.
- Final `output/report.md` must be a detailed business and technical report, not a short summary. It must explain what was done, why choices were made, how to interpret results, how to use artifacts, and what limitations remain.
- The final report must include these sections when a modeling run completes: task objective and default assumptions, dataset overview, data cleaning and filtering, train/validation/test split, baseline methods, candidate models and subagent experiments, final model selection rationale, metric definitions and business interpretation, error analysis by year and scale group, top error cases, quality diagnostics and optimization attempts, final prediction explanation, artifact guide, limitations, and reproduction steps.
- The report's artifact guide must not be a plain file list. For each core artifact, explain its purpose, key fields or contents, how to use it, and its boundaries. Core artifacts include `output/metrics.json`, `output/overview.json`, `output/code/final_predictions_2020_2024.csv` or equivalent prediction CSV, `output/predict.py`, `output/model/model.json`, `output/model/model.pkl` when present, `output/code/final_modeling.py`, `output/logs/subagents/*.md`, and `state/artifact_index.json`.
- Before finalizing, Codex must review `output/report.md` against these report requirements. If any required section is missing or too shallow, revise the report before marking the task completed.
- `output/predict.py` may exist only when a real reusable prediction entrypoint is available.
- Only write a blocker and wait for user input when the selected path cannot be read, contains no usable files or usable structured/unstructured content, contains no usable modeling or analysis target after inspection, or the user's explicit instruction conflicts with the data. Missing single target column, metric, or business objective alone is not a blocker; infer defaults and produce a complete plan for review.

The initial `progress.json` must use this shape:

```json
{
  "status": "waiting_human",
  "current_step": "workspace_initialized",
  "percent": 5,
  "summary": "AI4ML 工作区已创建，正在解析数据路径和任务目标。",
  "steps": [
    {
      "id": "workspace_initialized",
      "title": "工作区已初始化",
      "status": "completed",
      "detail": "已创建 AI4ML Codex-native 工作区和输出协议文件。"
    },
    {
      "id": "awaiting_task_input",
      "title": "等待任务输入",
      "status": "waiting_human",
      "detail": "等待或解析用户选择的数据文件/文件夹、任务描述、目标定义和必要约束。"
    }
  ],
  "updated_at": "{current_iso_time}"
}
```

After creating the workspace, reply with:

- The workspace path.
- The files created.
- The next information needed from the user.

The reply must be written in Chinese.
