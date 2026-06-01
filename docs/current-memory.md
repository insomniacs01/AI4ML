# AI4ML Current Memory

更新时间：2026-05-29

这份文档只记录当前仍然成立的项目事实。已经清理掉旧 React 主入口、MLZero/AutoGluon/AIDE 旧执行链路、模型/数据/工作流广场、业务/技术双报告、无效下载入口等过时记忆。后续代理应以本文件为准，不要再按旧章节恢复已删除的产品口径。

## 当前产品定位

AI4ML 是一个团队协作式智能建模工作台。当前主线是：

1. 用户在团队空间里创建任务，填写主题、描述并上传或指定数据。
2. 后端通过 `codex_use` 调用 Codex-native 工作区。
3. Codex 先生成 `output/plan.md`，用户查看、编辑并确认方案。
4. 确认后 Codex 执行建模、写报告、产物和预测入口。
5. 用户可以把任务主题/描述发布为提示词，也可以把已确认的 Codex plan 发布为执行方案，供后续任务复用。

当前默认方向不是让 AI4ML 自己复刻旧 AutoML agent 或 AutoGluon 执行流程。AI4ML 负责任务、团队、确认、报告、预测展示和社区复用；实际建模主流程交给 `D:\333\AI4ML\codex_use` 中的 Codex-native workspace 协议。

## 当前服务入口

- AI4ML 后端：`http://127.0.0.1:8000`
- AI4ML 前端：`http://127.0.0.1:5173`
- `codex_use` Web Console / Codex app-server 代理：`http://127.0.0.1:3000`
- 正式业务 API 统一走 `/api/teams/{team_id}/...`，除 `/api/health` 外不要新增非团队作用域业务接口。

前端登录依赖 Supabase session。当前 `frontend/src/api/client.js` 的 `getDemoUsers()` 返回空列表，登录页通常只显示账号登录；如果要做浏览器自动化验证，需要准备真实 Supabase 账号或绕过路由守卫做组件级验证。

## 当前技术栈

- 前端：Vue 3 + Vite。
- 前端入口：`frontend/src/App.vue`、`frontend/src/main.js`、`frontend/src/router.js`。
- 前端 API：`frontend/src/api/client.js` 仅作为兼容导出入口；具体逻辑拆到 `auth.js`、`tasks.js`、`community.js`、`notifications.js`、`teamAdmin.js`、`modelConfig.js`、`request.js`、`session.js` 和 `mappers.js`。
- 后端：FastAPI。
- 后端入口：`backend/app/main.py` 调用 `backend/app/application.py:create_app()`。
- 后端路由注册：`backend/app/api/router.py`。
- 身份和团队：Supabase session + team scope。
- 社区资产和任务持久化：Supabase store；任务读取有本地 SQLite cache。
- Codex 执行桥接：`backend/app/services/codex_backend.py`。
- AI 服务配置：统一使用 `ai_provider_*` 配置项，不再使用 `mlzero_*` 环境变量或配置项。

旧 `frontend/src/App.jsx`、`frontend/src/lib/api.js`、`HumanCollaborationPanel.jsx` 等 React 口径已经不是当前主入口，不要再作为开发依据。

## 当前代码清理状态

2026-05-28 已完成一次旧代码清理，当前源码口径是 Codex-only：

- 后端任务执行器统一为 `codex`。`TaskRecord.executor_type` 只接受当前 `codex` 口径，并对历史非 codex 值做兼容规范化。
- `backend/app/services/mlzero_runtime.py`、`backend/app/services/executors/`、旧 `task_run_*` 诊断/日志/指标/实时运行服务、旧增量重跑服务已经删除。
- `backend/config/mlzero-local-openai.yaml`、`scripts/run_autogluon_demo.py`、`scripts/generate_ai4ml_design_report.py`、`storage/run_force_llm_full.py` 已删除。
- `external/autogluon-assistant`、`external/automl-agent`、`external/aideml` 已删除。当前 `external/` 只保留仍存在的 `multica`。
- `storage/mlzero_runs` 和 `storage/mlzero_runtime` 已删除。`storage/tasks` 历史任务记录被保留，避免误删用户数据。
- `backend/requirements.txt` 已移除 `autogluon.tabular` 依赖。
- `supabase/schema.sql` 的任务执行器约束已收敛到 `codex`。
- 源码范围内 `backend/app`、`backend/tests`、`frontend/src`、`scripts`、`external`、`supabase/schema.sql` 已扫描，无 `mlzero`、`MLZero`、`AutoGluon`、`autogluon`、`AI4ML_MLZERO` 残留引用。

当前 `external/` 定位：

- 根目录 `D:\333\AI4ML\external\multica` 是保留的外部参考/上游代码，不是当前 AI4ML 主运行链路的一部分。
- 当前主项目入口仍是 `frontend/`、`backend/` 和 `codex_use/`；不要把 `external/multica` 当成当前业务前端、后端或 Codex 执行桥。
- 如后续确认 `external/multica` 没有参考价值，可以单独评估删除；删除前不要把它与当前运行依赖混为一谈。

## Codex-native Workspace 协议

当前 Codex 任务以 workspace 文件为事实来源。典型目录：

- `D:\333\AI4ML\codex_use\workspaces\ai4ml-{task_id}`
- 已验证示例：`D:\333\AI4ML\codex_use\workspaces\ai4ml-10ab64fd\output\plan.md`

输入文件：

- `input/task_request.json`
- `input/project_rules.md`

输出文件：

- `output/plan.md`
- `output/progress.json`
- `output/metrics.json`
- `output/report.md`
- `output/predict.py`
- `output/code/`
- `output/model/`
- `output/logs/`
- `output/token_usage.json`

环境与依赖规则：

- Codex 任务 workspace、`work/`、`output/` 和 subagent 目录内不应创建 `.venv`、`venv`、`env` 等 Python 虚拟环境。
- 优先使用项目级 `D:\333\AI4ML\.venv` 或系统已有 Python 解释器。
- 如任务确实需要额外依赖，应记录到 workspace 内的 requirements 文件或最终报告复现步骤，不在每个 subagent 目录重复安装完整依赖环境。
- 可重建的依赖目录、pip cache、临时安装目录和虚拟环境不属于任务最终产物，不应写入 `output/` 或 `state/artifact_index.json`。

`backend/app/services/codex_backend.py` 当前会读取这些产物，并同步 `TaskRecord.status`、`codex_status`、`last_run`、`last_run_attempt`、报告、预测、源码和 token usage。

重要修复：Codex workspace 解析现在不只依赖保存过的 `codex_workspace_path` 或 `last_run`，还会按 `ai4ml-{task_id}` 的确定性目录查找，并用 `input/task_request.json` / `authoritative_inputs.task_id` 校验归属。因此已完成任务即使数据库里缺少 workspace 路径，也能加载 `output/plan.md`。

## Codex 运行状态口径

- Codex 任务阶段以 `output/progress.json` 为主。
- `runtime-snapshot` 对 Codex 任务不应再用旧 `workflow_stage_records` 或前端 completed 兜底覆盖真实进度。
- 旧任务如果没有真实 `output/token_usage.json`，大模型用量显示 `-` 是正确行为。
- 不允许用估算 token 数冒充真实大模型用量。
- 新任务的 token usage 依赖 Codex app-server 是否发出 `thread/tokenUsage/updated`。收到后由 `codex_use` 写入 `output/token_usage.json`，AI4ML 后端再同步到任务记录。
- 额度耗尽时应由后端 quota guard 暂停或阻断继续运行，不能在额度为 0 后继续循环调用并重复刷通知。
- 实时运行面板必须读取 Codex session/event replay 或 workspace 产物；如果没有真实对话记录，应显示明确的等待、未连接或无历史状态，不能假装已返回。

## Codex 独立对话与暂停恢复

2026-05-28 已实现每个 AI4ML 任务独立绑定 Codex 原生 `threadId`：

- 新任务启动时，`codex_use` 强制创建新的 Codex thread 和新的 task workspace。
- `codex_use` 返回 `threadId`，AI4ML 后端保存到 `TaskRecord.codex_thread_id`。
- 后端在启动、确认计划、重新生成计划、暂停、继续中断任务时都会传递当前任务自己的 `codex_thread_id`。
- `codex_use` 恢复任务时优先按 `task_id -> threadId` 调 Codex `thread/resume`，再发送恢复 prompt。
- `codex_use/src/server/session-store.js` 会在 `~/.codex-web-console/session-state.json` 的 `taskThreads` 中保存 `taskId -> threadId/webSessionId` 映射。
- `codex_use/src/server/runners/app-server-runner.js` 支持指定 `threadId` 恢复；没有任务级 thread 时才退回 workspace 恢复。

暂停和取消现在是两个不同语义：

- `POST /tasks/{task_id}/pause`：调用 Codex `turn/interrupt`，任务保持 `paused_for_review`，`codex_status=interrupted`，后续可继续。
- `POST /tasks/{task_id}/run` 携带 `resume_interrupted=true`：按该任务自己的 `codex_thread_id` 恢复原 Codex 对话，并从现有 workspace 继续。
- `POST /tasks/{task_id}/cancel`：仍是业务取消，任务进入终止态，不作为常规继续入口。

历史任务如果之前没有保存 `codex_thread_id`，第一次继续时仍会尽量根据 workspace 恢复；新任务开始会严格绑定独立 thread。

## 当前前端页面状态

### 社区广场

社区广场已经收敛为两类资产：

- 提示词广场：保存任务主题和描述信息，后续可一键导入创建新任务。
- 方案广场：保存 Codex 已生成并确认过的执行方案，后续可选择、编辑后直接发给 Codex，跳过重新规划环节。

模型广场、数据中心、工作流、报告类社区资产已经从当前产品口径中移除。不要再恢复这些 tab 或发布入口。

当前 `frontend/src/views/CommunityView.vue` 保留关键词搜索功能：搜索名称、描述、提示词标题/描述、方案文本、任务分类、目标列、指标和标签。页面已改成“提示词 / 方案广场”的集中资源面板版式，点击条目后在下方查看详情并执行复用、复制或 fork 操作。

### 任务详情页

`frontend/src/views/TaskDetailView.vue` 当前重点：

- 顶部指标保留状态、任务类型、大模型用量和总状态。
- 运行中的 Codex 任务会显示“暂停运行”按钮；已暂停任务显示“继续运行”，继续时携带 `resume_interrupted=true` 恢复同一个 workspace 和 `codex_thread_id`。
- 报告页只展示最终报告，不再区分业务报告和技术报告。
- 报告下载入口已移除，因为当前下载按钮没有实际价值。
- 源码页应优先展示真实运行产物，尤其是 `output/code/final_modeling.py`、`output/predict.py` 等；不能空白假装有源码。
- 发布页使用上下结构，不再左右不等宽。
- 发布提示词：保存当前任务主题和描述。
- 发布执行方案：展示“查看/编辑方案”按钮，打开当前任务的 `plan.md` 内容，允许修改后发布。

### 工作台、任务列表和进度页

- `frontend/src/views/WorkspaceView.vue`、`frontend/src/views/TaskProgressView.vue` 和 `frontend/src/views/TasksView.vue` 已接入暂停入口。
- 暂停按钮调用 `pauseTask()` / `POST /tasks/{task_id}/pause`；继续入口调用 `rerunTask()` 并带 `resume_interrupted=true`。
- 前端文案应使用“暂停运行 / 继续运行”，不要把业务取消当成暂停。

### 创建任务页

`frontend/src/views/CreateTaskView.vue` 支持从社区导入：

- 提示词：填充任务主题和描述。
- 执行方案：填充 `selected_plan_text`、`selected_plan_id`、`selected_plan_name`。提交任务时可让 Codex 跳过重新规划，直接执行用户选定并可编辑的方案。

## 社区资产后端和数据库

当前社区资产模型只支持：

- `prompt`
- `plan`

关键文件：

- `backend/app/models/governance.py`
- `backend/app/services/governance_store.py`
- `backend/app/api/routes/team.py`
- `frontend/src/api/client.js`
- `frontend/src/views/CommunityView.vue`
- `frontend/src/views/TaskDetailView.vue`
- `supabase/schema.sql`

`platform_assets.asset_type` 代码和 schema 预期为 `prompt` / `plan`。如果点击“发布提示词”时报：

`platform_assets_asset_type_check`

或：

`new row for relation "platform_assets" violates check constraint`

说明实际 Supabase 数据库还停留在旧约束，仍只允许旧的 `dataset/model/workflow/report`。这不是前端发送错了，需要在 Supabase SQL Editor 更新表约束。

当前最小迁移 SQL：

```sql
alter table public.platform_assets
  drop constraint if exists platform_assets_asset_type_check;

delete from public.platform_assets
where asset_type not in ('prompt', 'plan');

alter table public.platform_assets
  add constraint platform_assets_asset_type_check
  check (asset_type in ('prompt', 'plan'));

select pg_notify('pgrst', 'reload schema');
```

注意：这会删除旧模型/数据/工作流/报告类社区资产。该删除符合当前“只保留提示词广场 / 方案广场”的产品要求。

## 后端结构现状

当前后端已经从大文件拆分为应用工厂、聚合路由和服务层：

- `backend/app/application.py`：FastAPI app factory。
- `backend/app/api/router.py`：统一注册 API router。
- `backend/app/api/errors.py`：统一错误响应辅助。
- `backend/app/services/service_registry.py`：集中提供服务实例。
- `backend/app/api/routes/tasks.py`：任务聚合 router。
- `backend/app/api/routes/task_lifecycle.py`：任务创建、列表、详情、上传、runtime snapshot。
- `backend/app/api/routes/task_runtime.py`：运行、修复、重跑、进度。
- `backend/app/api/routes/task_artifacts.py`：运行产物。
- `backend/app/api/routes/task_human.py`：人工确认。
- `backend/app/services/task_store.py`：任务 store 门面，真实逻辑拆到 repository/mixin。
- `backend/app/services/task_cache.py`：本地 SQLite 任务和阶段缓存。
- `backend/app/api/routes/task_runtime.py`：Codex 任务启动、暂停、恢复中断任务、取消和运行进度。
- `backend/app/services/task_runtime_steps.py`：runtime steps 构建，Codex steps 优先。
- `backend/app/services/task_runtime_activity.py`：Codex 单活动任务互斥和活动任务发现。
- `backend/app/services/task_runtime_progress.py`：Codex 进度文件、阶段记录和计划确认请求。
- `backend/app/services/task_report_features.py`：报告特征重要性产物解析。
- `backend/app/services/task_code_versions.py`：代码工作区版本记录和 hash 计算。
- `backend/app/services/provider_availability.py`：通用 OpenAI-compatible provider 可用性检测。
- `backend/app/services/quota_runtime_guard.py`：任务运行前后的额度保护。
- `backend/app/services/platform_limits.py`：平台额度和限制口径。

`TaskStore` 当前是门面，不应再把新业务逻辑塞回单个大文件。

## 近期 Linus 风格后端重构状态

2026-05-29 已按“行为保持、降低真实复杂度、补直接覆盖”的口径继续处理后端高复杂度热点。当前已落盘的主要拆分包括：

- `backend/app/services/task_human_context.py`：人工决策 guidance 的单条决策渲染和 artifact 文本构造已拆出，保留现有句子格式。
- `backend/app/services/task_report_sections.py`：报告摘要 `_abstract_lines` 已拆成任务、baseline、模型结果和特征解释句子构造。
- `backend/app/services/codex_overview.py`：baseline metric 候选选择和 split fallback 解析已拆出。
- `backend/app/services/task_human_stages.py`：`build_stage_blueprints` 已拆成各工作流阶段的状态/摘要构造函数。
- `backend/app/services/task_human_parameters.py`：`apply_human_decision_parameters` 已拆成阶段参数应用、参数记录、analysis refresh 和 rerun invalidation 四段状态转移。
- `backend/app/services/task_runtime_progress.py`：`record_codex_status_stages` 已拆成用户暂停、计划确认 gate 和 Codex 完成运行三条分支。
- `backend/app/services/task_store_payloads.py`：阶段 timing 解析已拆成 running、terminal、inactive timestamp 规则和 duration 计算。
- `backend/app/services/task_agent_collaboration.py`：agent stage event、human request event 和 event 排序/截断已拆出。

这些变更新增或扩展了直接测试覆盖：

- `backend/tests/test_human_collaboration.py`
- `backend/tests/test_task_report_sections.py`
- `backend/tests/test_codex_overview.py`
- `backend/tests/test_task_human_stages.py`
- `backend/tests/test_task_human_parameters.py`
- `backend/tests/test_task_runtime_progress.py`
- `backend/tests/test_task_store_stage_timing.py`
- `backend/tests/test_task_agent_collaboration.py`

最新热点粗排使用 AST 控制流估算，不依赖 `radon`。当前剩余优先热点大致为：

- `backend/app/services/connector_store.py::_request_json`
- `backend/app/services/supabase_task_http.py::request_json`
- `backend/app/services/dataset_profile.py::build_dataset_profile`
- `backend/app/services/task_workflow_tracking.py::_ensure_agent_runtime_records`
- `backend/app/services/task_agent_quality.py::build_next_improvement`
- `backend/app/services/dataset_profile.py::_infer_scalar_type`
- `backend/app/services/task_human_collaboration.py::submit_decision`

后续继续重构时应优先补直接 characterization，再改实现；HTTP/Supabase request wrappers 属于共享 IO 语义，改前要先固定错误映射、空响应和非 JSON 响应行为。

## 当前硬约束

- 不展示伪数据。
- 不制造假成功。
- 不用演示值冒充真实业务结果。
- 不做静默 fallback。连接器、模型、运行产物、Supabase 权限或 Codex 产物缺失时必须明确失败或显示未接入。
- 大模型用量必须来自真实 Codex usage 事件。
- Codex 任务阶段必须来自真实 Codex progress。
- 当前执行链路只支持 Codex-native；不要重新引入 MLZero、AutoGluon、AIDE 或旧外部 AutoML agent。
- 社区广场只保留提示词和执行方案，不恢复模型/数据/工作流广场。
- 面向普通用户的文案应避免堆底层术语，优先使用“AI 服务”“运行记录”“结果文件”“人工确认”“执行方案”等直观说法。

## 近期验证状态

2026-05-29 Linus 风格后端热点重构后已验证：

- `python -m pytest backend\tests`：149 passed，1 个既有 FastAPI `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning。

2026-05-29 Codex-only 主线整体重构后曾验证：

- `python -m compileall -q backend\app`：通过。
- `python -m pytest backend\tests -q`：48 passed，1 个 FastAPI `HTTP_422_UNPROCESSABLE_ENTITY` deprecation warning。
- `cd frontend && npm test -- --run src/api/client.test.js`：11 passed。
- `cd frontend && npm run build`：通过。

补充：项目 `.venv` 当前没有安装 `pytest`，因此后端测试使用系统 Python 运行。若要固定到 `.venv`，需要给该环境安装测试依赖。

2026-05-28 清理旧 MLZero/AutoGluon/AIDE 执行链路后曾验证：

- `python -m compileall -q backend/app`：通过。
- `python -m pytest backend/tests/test_backend_instance_lock.py backend/tests/test_quota_runtime_guard.py backend/tests/test_codex_workspace_resolution.py backend/tests/test_admin_user_limits.py backend/tests/test_governance_asset_contract.py backend/tests/test_task_cache.py`：22 passed。
- `cd frontend && npm test -- --run src/api/client.test.js`：12 passed。
- `cd frontend && npm run build`：通过。
- `cd codex_use && node --check server.js; node --check src/server/web-session-manager.js; node --check src/server/runners/app-server-runner.js; node --check src/server/session-store.js`：通过。

社区广场版式调整后，前端测试和构建已通过。Playwright 技能包装脚本曾在 Windows/WSL 环境遇到 `E_ACCESSDENIED`，改用 `npx playwright-cli` 可以启动浏览器；但 `/community` 受登录保护，自动视觉检查需要有效 Supabase 登录态。

## 当前注意事项

- 实际 Supabase 数据库 schema 可能没有自动跟随 `supabase/schema.sql`。如果出现约束错误，优先检查数据库约束是否已迁移。
- 历史旧任务缺少 `token_usage.json` 时不能恢复真实 token。
- 工作区或任务产物缺失时，不要补造报告、源码、指标或预测结果。
- 当前工作区有大量用户既有修改和未跟踪文件，后续代理不能用 `git reset --hard` 或 `git checkout --` 回退未确认的内容。
- 旧华为云部署信息没有在本轮重新验证，若要部署必须重新检查服务器状态和线上差异，不能把旧日期的部署记录当作当前事实。
- `storage/tasks` 可能仍保留历史旧任务数据，这不是当前源码链路残留；除非用户明确要求清历史数据，否则不要删除。

## 关键文件

- `frontend/src/App.vue`
- `frontend/src/main.js`
- `frontend/src/router.js`
- `frontend/src/api/client.js`
- `frontend/src/views/WorkspaceView.vue`
- `frontend/src/views/CreateTaskView.vue`
- `frontend/src/views/TaskDetailView.vue`
- `frontend/src/views/CommunityView.vue`
- `frontend/src/components/CodexRealtimePanel.vue`
- `frontend/src/components/HitlApprovalModal.vue`
- `backend/app/main.py`
- `backend/app/application.py`
- `backend/app/api/router.py`
- `backend/app/api/routes/task_lifecycle.py`
- `backend/app/api/routes/task_runtime.py`
- `backend/app/api/routes/task_artifacts.py`
- `backend/app/api/routes/task_human.py`
- `backend/app/api/routes/team.py`
- `backend/app/models/task.py`
- `backend/app/models/governance.py`
- `backend/app/services/codex_backend.py`
- `backend/app/services/governance_store.py`
- `backend/app/services/task_cache.py`
- `backend/app/services/task_code_workspace.py`
- `backend/app/services/provider_availability.py`
- `backend/app/services/quota_runtime_guard.py`
- `backend/app/services/task_runtime_steps.py`
- `backend/app/services/task_store.py`
- `supabase/schema.sql`
- `codex_use/current-memory.md`

## 已废弃口径

以下说法已经过时，后续不要再引用：

- “当前前端是 React/Vite，入口是 `frontend/src/App.jsx`。”
- “继续拆 `App.jsx`。”
- “主执行链路是 MLZero/AutoGluon。”
- “项目还需要保留 MLZero runtime、AutoGluon assistant、AIDE 或旧 AutoML external 目录。”
- “配置仍应读取 `AI4ML_MLZERO_*` 或 `mlzero_*` 字段。”
- “社区广场包含模型广场、数据中心、工作流。”
- “发布页包含提交模型审核、提交工作流审核。”
- “报告页分业务报告和技术报告。”
- “报告下载按钮是有效核心能力。”
- “当前 `.venv` 没有 pytest，只能用 unittest。”
- “Codex workspace 只能依赖数据库保存路径才能加载 plan。”
