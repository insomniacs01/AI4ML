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
workspaces/{task_id}/output/run_strategy.json
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
- `output/run_strategy.json` is required together with `output/plan.md` before model execution. It is the machine-readable execution boundary confirmed by the user.
- After receiving a data path, Codex must first inspect whether it is a file or directory, understand its content and structure, then generate or update `output/plan.md`.
- The selected data path may be any file or directory. Do not assume CSV. For a directory, inventory the contained files, identify likely datasets, metadata, documentation, and existing outputs. For a file, choose the reader based on extension, file signature, content sampling, and available libraries.
- The task target may be a single column, multiple columns, multiple indicators, derived targets, non-column objectives, ranking targets, clustering groups, missing-value completion, forecasting ranges, report-only analysis goals, or a mixed workflow. Do not assume there is exactly one `target column`.
- The plan must be a concise user-confirmation contract, not a long technical report, tutorial, broad methodology document, or list of questions. It should let the user quickly decide whether the proposed execution boundary is correct.
- If the user did not fully specify target definition, task type, metric, prediction range, or business objective, Codex must infer reasonable defaults from the data and task description, clearly label them as "默认假设", and build the plan around those defaults.
- For ambiguous multi-indicator or multi-file tasks, Codex must select a defensible default modeling target, analysis target, or target set from the data, explain why it was chosen in one short bullet, and include at most three concise alternatives in "需要确认或可调整". Do not stop only because multiple choices exist.
- `output/plan.md` must use exactly these top-level sections, in this order:
  1. `# 执行计划`
  2. `## 任务判断`
  3. `## 执行策略`
  4. `## 执行步骤`
  5. `## 验收与改进规则`
  6. `## 预期产物`
  7. `## 需要用户确认`
- `output/plan.md` must stay short and reviewable:
  - Prefer 600-1200 Chinese characters for simple and standard tasks.
  - Use short bullets and numbered steps only.
  - Do not include long background explanations, machine-learning textbook content, generic best practices, implementation code, dependency installation logs, or final-report-style analysis.
  - Do not enumerate many possible algorithms. Name only the models, analyses, or checks that Codex actually plans to run.
  - Do not duplicate the project rules, output schema, or final report requirements inside the plan.
- The `任务判断` section must state:
  - task type, such as classification, regression, forecasting, clustering, analysis-only, mixed, or other;
  - target definition, including selected target column, derived objective, entity, time range, or "not applicable";
  - data complexity as low, medium, or high;
  - one concise reason for the complexity judgment;
  - any necessary default assumptions.
- The `执行策略` section must state:
  - the execution strategy selected for this task;
  - planned candidate model or method count;
  - whether subagents are needed;
  - whether hyperparameter search is needed;
  - expected report depth.
- Codex must choose exactly one strategy id and write it consistently in both `output/plan.md` and `output/run_strategy.json`:
  - `light_tabular`: small or simple tabular classification/regression task with clear target, small feature set, and no need for broad exploration. Example: Iris-like CSV tasks. Usually use 1-2 candidate models, no subagents, no broad hyperparameter search, brief report, and at most 1 automatic improvement round.
  - `standard_tabular`: ordinary tabular modeling task that needs normal preprocessing, a few model candidates, bounded diagnostics, and a standard report. Usually use 3-5 candidate models, optional limited subagents only when useful, small bounded hyperparameter search, and at most 2 automatic improvement rounds.
  - `deep_tabular`: difficult tabular modeling task with larger data, ambiguous target, strong imbalance, time/group constraints, complex feature work, or high-stakes analysis. Use only when the data and task justify deeper work. It may use subagents, richer diagnostics, bounded tuning, detailed report, and at most 3 automatic improvement rounds.
  - `custom_research`: non-standard task such as multi-file custom analysis, forecasting, clustering, report-only analysis, non-column target, mixed workflow, or domain-specific research where tabular model presets do not fit.
- `output/run_strategy.json` must be valid JSON using this schema:

```json
{
  "schema_version": "1.0",
  "strategy_id": "light_tabular | standard_tabular | deep_tabular | custom_research",
  "complexity": "low | medium | high",
  "task_type": "classification | regression | forecasting | clustering | analysis | mixed | other",
  "target": {
    "mode": "single_target | multi_target | multi_output | unsupervised | analysis_only | mixed | other",
    "fields": ["target field or derived target name"],
    "description": "concise Chinese target definition"
  },
  "decision_reason": "one concise Chinese reason for this strategy",
  "execution_limits": {
    "candidate_model_count": 2,
    "planned_models_or_methods": ["model or method names"],
    "allow_subagents": false,
    "planned_subagents": [],
    "hyperparameter_search": "none | small | bounded | deep",
    "report_depth": "brief | standard | detailed",
    "max_auto_improvement_rounds": 1,
    "min_meaningful_metric_improvement": 0.01,
    "advisor_after_failed_rounds": 2
  },
  "acceptance": {
    "primary_metric": "metric or success criterion",
    "threshold": 0.0,
    "higher_is_better": true,
    "fallback_rule": "concise Chinese rule when no numeric threshold is appropriate"
  },
  "stop_rules": [
    "concise Chinese stop rule"
  ],
  "expected_artifacts": [
    "output/metrics.json",
    "output/overview.json",
    "output/report.md"
  ]
}
```

- For fields that are not applicable, keep the JSON key and use `null`, `[]`, or a concise explanatory string. Do not add extra top-level keys unless the task truly requires them.
- For `light_tabular`, the default `execution_limits` should normally be: `candidate_model_count <= 2`, `allow_subagents: false`, `hyperparameter_search: "none"` or `"small"`, `report_depth: "brief"`, and `max_auto_improvement_rounds <= 1`.
- For `standard_tabular`, the default `execution_limits` should normally be: `candidate_model_count <= 5`, subagents only if justified, `hyperparameter_search: "small"` or `"bounded"`, `report_depth: "standard"`, and `max_auto_improvement_rounds <= 2`.
- For `deep_tabular`, the plan must briefly justify why a deeper strategy is needed; do not choose it just because it might improve results.
- `advisor_after_failed_rounds` controls when Codex may request an independent read-only advisor after repeated ineffective improvements. For `light_tabular`, use `2` or `null` and do not request an advisor unless the task has already failed to improve within the one allowed automatic round and the user confirms further work.
- The `执行步骤` section must contain 5 numbered steps for simple and standard tasks:
  1. `任务与数据确认`
  2. `数据检查与准备`
  3. `模型训练或核心分析`
  4. `评估与选择`
  5. `产物生成`
- Each `执行步骤` item must include 2-4 concrete sub-bullets. Each sub-bullet must describe a specific action or output, not a vague principle.
- For genuinely complex tasks, `执行步骤` may contain at most 7 numbered steps by inserting only these two steps where needed:
  - `探索分析`
  - `特征工程或任务专用处理`
- The `验收与改进规则` section must define:
  - primary metric or success criterion;
  - acceptance threshold or a clear rule for deciding whether the result is usable;
  - the maximum number of automatic improvement rounds;
  - the minimum meaningful metric improvement when applicable;
  - the stop rule when the result remains unsatisfactory.
- The stop rule must say that when the automatic improvement limit is reached, Codex writes `output/improvement_plan.md`, sets `output/progress.json` to `waiting_improvement_review`, and waits for the user to choose `继续改进` or `停止并生成报告`.
- The `预期产物` section must list only the concrete files expected for this task, usually `output/run_strategy.json`, `output/metrics.json`, `output/overview.json`, `output/report.md`, `output/predict.py` when a real prediction entrypoint is appropriate, and `output/code/final_modeling.py` or an equivalent core script.
- The `需要用户确认` section must explicitly say that Codex will wait for approval before training, model comparison, final report generation, prediction entrypoint creation, or other execution work.
- After generating the complete default plan and `output/run_strategy.json`, Codex must set `output/progress.json` to `waiting_plan_approval` and stop.
- Codex must not train models, run model comparison, create `output/metrics.json`, create `output/report.md`, or create `output/predict.py` until the user explicitly approves the plan.
- During the execution stage after plan approval, Codex must follow the subagent decision stated in the confirmed plan. Small, low-complexity tasks should normally use a single parent Codex flow rather than spawning subagents.
- Use native subagents only when the confirmed plan says they are needed for parallel experimental work, independent diagnostics, or final validation. For larger tasks, possible subagents include `baseline_worker`, `feature_model_worker`, `alternative_model_worker`, `diagnostics_worker`, `optimization_worker`, and read-only `validation_reviewer`; do not spawn them by default for simple tasks.
- Subagents must not write final user-visible artifacts directly. Subagents may write only under `work/subagents/{agent_name}/` and `output/logs/subagents/{agent_name}.md`. The parent Codex must read subagent outputs, choose and merge the result, and write final `output/metrics.json`, `output/overview.json`, `output/report.md`, `output/predict.py`, and `state/artifact_index.json`.
- The parent Codex must record which subagents were used, what each tried, and which result was selected in `output/report.md` or `output/logs/subagents/summary.md`.
- After the user approves execution, Codex must include a result-quality feedback loop: establish a baseline, evaluate the first modeling result on an appropriate validation split, diagnose weak performance or suspicious results, then make bounded fixes or optimization attempts before finalizing.
- If performance is not satisfactory, Codex must inspect likely causes such as data leakage, target definition, missing values, feature quality, class imbalance, time split mistakes, insufficient samples, inappropriate metric choice, or model underfitting/overfitting. Codex must then revise features, validation, preprocessing, model choice, or task framing when justified.
- Codex must not endlessly optimize. It must stop after `max_auto_improvement_rounds` or after repeated changes fail to reach `min_meaningful_metric_improvement`.
- When stopping because further improvement needs human confirmation, Codex must write `output/improvement_plan.md`, set `output/progress.json` to `waiting_improvement_review`, and wait. Do not keep training while waiting.
- If repeated changes fail and `advisor_after_failed_rounds` is reached, Codex may request one independent read-only advisor diagnosis before writing the improvement decision plan. The advisor input must be `output/advisor_request.json`, and the advisor output must be `output/advisor_diagnosis.json`. The advisor cannot directly modify final artifacts or expand the confirmed strategy.
- If the user revises the plan, update `output/plan.md`, update `output/run_strategy.json` if the execution boundary changed, and keep waiting for approval unless the user explicitly asks to execute.
- If the user asks to regenerate the plan, regenerate both `output/plan.md` and `output/run_strategy.json`, then keep waiting for approval.
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
- Final `output/report.md` must match `output/run_strategy.json.execution_limits.report_depth`.
- For `report_depth: "brief"`, write a concise report covering task objective, data used, method, main metrics, conclusion, limitations, and generated artifacts. Do not add long background explanations or unnecessary sections.
- For `report_depth: "standard"`, write a normal report covering task objective and assumptions, dataset overview, data preparation, validation split, baseline or comparison method, candidate models or methods, final selection, metric interpretation, limitations, artifacts, and reproduction steps.
- For `report_depth: "detailed"`, write a deeper report that adds richer diagnostics, error analysis, optimization records, stability or leakage checks where relevant, and more detailed artifact usage boundaries.
- The report's artifact guide must explain only the real artifacts generated in this run. Do not list nonexistent prediction CSVs, model files, subagent logs, or feature-importance files.
- Before finalizing, Codex must review `output/report.md` against the confirmed `report_depth`, real artifacts, real metrics, and truthfulness requirements. If it is too shallow or unnecessarily long for the selected strategy, revise it before marking the task completed.
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
