# AI4ML Current Memory

## 对话背景

- 本轮工作重点是 `frontend/` 的前端页面设计，不以当前后端完成度为边界。
- 用户明确要求：
  - 前端应优先依据需求文档和参考截图来设计。
  - 如果功能没有接入或没有实现，页面必须明确显示“未接入 / 暂不支持 / 待实现”，不能用伪数据冒充真实业务结果。

## 本轮已完成内容

### 1. 前端整体重构

- 已将前端首页重构为控制台式后台壳子，包含左侧导航和顶部工具栏。
- 当前导航页面包括：
  - 仪表盘
  - 监控中心
  - 工作流进度
  - 模型报告
  - 成员管理
  - AI 连接管理
  - 默认 AI 组合
  - 配额管理
  - 系统状态
  - 审计日志

### 2. 需求驱动的页面结构

- 页面布局已按需求文档中的 6.1 页面需求做了结构设计。
- 目前前端强调“页面结构已就位”，但不会默认展示虚构业务数据。

### 3. 诚实状态展示模式

- 已把大部分原先的演示数据移除。
- 当前策略是：
  - `health`：尝试读取真实接口
  - 其余未接入模块：显示“未接入 / 待实现 / 当前不展示默认值”

### 4. 修复空白页问题

- 用户反馈点击“AI运行情况”后出现空白页。
- 已定位并修复：
  - `FeatureList` 组件曾对字符串执行 `in` 判断，导致运行时错误并出现空白页。
  - 现已修成同时支持字符串数组和对象数组。
- 另外增加了旧页面标识兜底映射：
  - `aiStatus`
  - `aiRunning`
  - `aiRuntime`
  - `aiMonitor`
  - `aiOperation`
  - 上述旧标识会自动映射到 `monitoring`
- 同时增加了未知页面兜底提示，避免再出现空白页。

## 当前真实行为

### 已接入

- `frontend/src/App.jsx` 中会尝试调用：
  - `GET /api/health`
- 若后端可用：
  - `系统状态`
  - `仪表盘`中的系统状态面板
  会显示真实 health 字段。

### 未接入但已设计结构

- 任务创建
- CSV 上传
- 任务列表 / 详情
- 请求统计
- Token 统计
- API Key 使用占比
- 工作流阶段进度
- 成员管理
- AI 连接器管理
- 默认 AI 组合
- 配额流水
- 审计日志
- 模型报告详情

这些页面当前只保留结构和依赖说明，不再显示伪造数值。

## 关键改动文件

- `frontend/src/App.jsx`
  - 主控制台页面
  - 视图切换
  - health 读取
  - 未知页面兜底
  - “AI运行情况”旧标识兼容
- `frontend/src/prototypeData.js`
  - 当前不是演示业务数据文件
  - 现在主要保存页面结构说明、依赖说明和字段要求
- `frontend/src/styles.css`
  - 控制台布局样式
  - 未接入状态卡片、占位图、空状态等样式
- `frontend/index.html`
  - 页面标题已改为中文控制台标题
- `docs/current-memory.md`
  - 本记忆文档

## 当前构建状态

- 已执行：
  - `cd frontend`
  - `npm install`
  - `npm run build`
- 最近一次构建通过。

## 当前 git 相关状态

- 当前前端存在未提交修改，主要集中在：
  - `frontend/src/App.jsx`
  - `frontend/src/styles.css`
  - `frontend/src/prototypeData.js`
  - `frontend/index.html`
  - `frontend/dist/*`
- `docs/` 目录原本在工作区中实际不存在，但 `README.md` 里引用了 `docs/current-memory.md`，本轮已补建 `docs/` 并写入该记忆文档。

## 下次继续时建议优先做的事

### 方案 A：继续保持“诚实原型”

- 继续补页面，但所有未接入模块都保持：
  - 结构完整
  - 状态明确
  - 不展示伪数据

### 方案 B：逐步接真实接口

- 可优先接入这些真实能力：
  1. `tasks` 列表与详情
  2. 任务创建 + CSV 上传
  3. 运行工作流按钮
  4. 系统状态面板

### 方案 C：补充更多需求页

- 可继续补这些页面原型：
  - 团队创建 / 选择页
  - 数据中心
  - 模型广场
  - 工作流广场

## 如果新开对话，建议这样开场

可以让新对话先读取：

- `docs/current-memory.md`

然后直接说明你要走哪条路线，例如：

- “继续保持前端诚实原型，补数据中心和模型广场页面”
- “开始把任务列表和任务创建接到真实后端”
- “继续排查左侧菜单还有没有会导致空白页的页面”

## 2026-04-21 local validation note

- Backend task execution is MLZero-only again, and local machine failures are now surfaced directly instead of being hidden behind a fallback path.
- `/api/health` now reports MLZero availability status plus the concrete failure reason.
- Frontend build passes after the Supabase integration changes.
- The sample `data/samples/iris.csv` file uses `label` as the target column, not `species`.
- Supabase auth testing is currently blocked by an `email rate limit exceeded` response from the project, so the live database flow still needs a fresh auth window to be rechecked end to end.

## 2026-04-22 current runtime status

- The backend is currently MLZero-only. There is no active fallback executor path anymore.
- Local backend health now truthfully reports runtime availability through `executor_status` and `executor_detail`.
- On this machine, task creation and CSV upload work, but task execution fails at MLZero startup.
- The concrete local blockers are:
  - `AI4ML_MLZERO_MAMBA_EXECUTABLE` default target is missing on this Windows machine
  - `local/models/Qwen2.5-Coder-0.5B-Instruct-Q4_K_M.gguf` is missing
- Current observed health status is effectively:
  - `task_executor = mlzero`
  - `executor_status = unavailable`
  - `executor_detail = mamba executable not found from C:\Users\LENOVO\.local\miniforge3\bin\mamba`
- Current observed task run failure is effectively:
  - `POST /api/tasks/{id}/run` returns HTTP 500
  - detail: `MLZero mamba executable not found: C:\Users\LENOVO\.local\miniforge3\bin\mamba`

## 2026-04-22 multi-model capability status

- The project requirement/design expects AI connector management, default AI combinations, routing, and quota management.
- The current codebase does not yet implement a real multi-model connector backend.
- What exists today is a single fixed MLZero execution path:
  - MLZero config uses `provider: openai`
  - model alias is fixed as `gpt-4-local`
  - proxy target is fixed to local `llama_cpp.server` on `http://127.0.0.1:8001/v1`
- Frontend pages for connectors / routing / quotas are still structural placeholders and are not wired to real backend APIs.
- Therefore, the current repository state should be understood as:
  - product/UI structure anticipates multiple models
  - actual runnable backend path is still only one local-model execution chain
  - and that one chain is currently blocked by missing local runtime dependencies

## 2026-04-22 backend unification status

- FastAPI task routes now trust Supabase session identity instead of the old local backend auth flow.
- Frontend task requests now send:
  - `Authorization: Bearer <supabase access token>`
  - `X-Team-Id: <active team id>`
- Backend task storage is now team-scoped:
  - `storage/tasks/<team_id>/<task_id>/task.json`
- New tasks are persisted with:
  - `team_id`
  - `created_by`
- The old FastAPI local `/auth` and `/users` routes are no longer mounted in `backend.app.main`.
- Legacy local-user files still remain in the repository for now, but they are no longer part of the active runtime path.
- This means the active runtime architecture is now:
  - Supabase = identity and team source of truth
  - FastAPI = task and MLZero execution service

## 2026-04-22 auth flow validation

- Live Supabase auth settings were checked through `GET /auth/v1/settings`.
- Current observed auth state is:
  - `disable_signup = false`
  - `mailer_autoconfirm = false`
  - `phone_autoconfirm = false`
- This means the hosted project is still configured to require email confirmation before login.
- The current live signup path is therefore not yet "register and immediately enter the workspace".
- Signup testing also hit:
  - `429 over_email_send_rate_limit`
- Therefore, the immediate blocker is not frontend code alone; it is the hosted Supabase auth configuration.
- Frontend auth flow has now been updated to:
  - read auth settings
  - auto-attempt sign-in immediately after successful signup
  - surface explicit errors for:
    - email confirmation still enabled
    - email send rate limit exceeded
- A local verification helper was added:
  - `node scripts/check_supabase_auth_flow.mjs`

## 2026-04-22 auth flow revalidation after remote config change

- Hosted Supabase auth has now been rechecked and the current observed state is:
  - `disable_signup = false`
  - `mailer_autoconfirm = true`
  - `phone_autoconfirm = false`
  - `email_provider_enabled = true`
- This means the hosted project no longer requires email confirmation before first login.

## 2026-05-02 P0 strict incremental rerun closure

- The previous P0 tail was real: "rerun from stage" used to be only status/guidance while the runtime still called a full `MLZeroExecutor.run(...)`.
- This has now been closed at backend level:
  - `requirement_analysis` / `data_analysis` reruns re-run AI analysis first, then continue downstream.
  - `feature_engineering` reruns create a new incremental run directory, generate new code directly from the reviewed task context, execute it, and persist real `run_summary.json` / `leaderboard` artifacts.
  - `model_selection` / `training_validation` reruns reuse existing `generated_code.py`, rewrite old absolute run paths to the new run directory, execute it, and parse real artifacts.
  - `report_generation` reruns do not train or call MLZero; they copy real prior result artifacts and rebuild `report_snapshot.md`.
- Every strict incremental rerun writes `incremental_rerun_manifest.json` with:
  - `strict_incremental: true`
  - source output directory
  - start stage
  - reused stages
  - rerun stages
  - mode and generated-code lineage
- Missing required artifacts now fail explicitly with `409 Conflict` before the task is marked running, for example missing previous output directory or missing `generated_code.py`.
- `POST /api/tasks/{task_id}/run` also accepts optional `rerun_from_stage` and `force_full_run`; the default still reads `structured_requirements.human_loop.rerun_requested`.
- Frontend task detail now shows when the next run will start from a specific stage and changes the run button label accordingly.
- Verification added:
  - `backend/tests/test_incremental_rerun.py`
  - `python -m unittest discover backend/tests` now includes strict incremental rerun coverage.
- Exact frontend SDK behavior was revalidated with `@supabase/supabase-js` using the same signup path as the app:
  - `signUp()` now returns a session immediately
  - the new session is stored immediately
  - `signInWithPassword()` also succeeds right after signup
- Full runtime smoke test was also revalidated end to end:
  - signup with a fresh test account succeeded
  - team creation through `create_team_with_owner` succeeded
  - team membership query succeeded and returned the new user as `admin`
  - backend `/api/tasks` accepted the Supabase bearer token plus `X-Team-Id`
  - backend task creation succeeded for the new team
- Representative verified test accounts created during this validation:
  - `ai4ml-sdk-check-1776863467601@example.com`
  - `ai4ml-fullflow-check-1776863503916@example.com`
- Current auth conclusion:
  - the register -> immediate sign-in -> create team -> access backend task API path is now working
- Remaining non-auth blocker is unchanged:
  - MLZero runtime is still locally unavailable on this machine, so task execution is not yet runnable even though auth and task creation are now working

## 2026-04-22 frontend monitoring refresh

- The main workspace shell has been visually refreshed toward a cleaner console layout:
  - Chinese navigation labels
  - lighter sidebar / topbar treatment
  - cleaner action buttons in the authenticated workspace
- The `Monitoring` page has been rebuilt from a plain placeholder list into a dashboard-style template view with:
  - toolbar controls
  - summary metric cards
  - model distribution donut
  - daily usage trend chart
  - API key usage share list
- These monitoring visuals are still explicitly template data only.
- Real monitoring aggregation APIs are still not connected, and the page now states that clearly in the UI.
- The previous `Monitoring` white-screen bug was also fixed by making `FeatureList` safely handle items that use `label` instead of `title`.
- Frontend build revalidated successfully after the monitoring redesign.

## 2026-04-22 frontend language unification

- User-facing frontend copy has been further unified toward Chinese-first UI text.
- Updated areas now include:
  - auth screen
  - team onboarding
  - team members view
  - dashboard / system page / monitoring page visible labels
  - placeholder data labels in `prototypeData.js`
  - legacy `TaskForm`, `TaskCard`, and `SystemPanel` component copy
- Frontend now also translates several common backend / Supabase error messages before displaying them in notices or error banners, such as:
  - invalid login credentials
  - user already registered
  - invite code not found
  - dataset has not been uploaded
- Build was revalidated successfully after the copy update.

## 2026-04-24 cloud runtime status and next actions

- Cloud OpenAI-compatible provider access is now working against:
  - base URL: `https://codex.miaomiaocode.com/v1`
  - model alias: `gpt-5.4`
  - wire API: `responses`
- The backend no longer depends only on `mamba` for execution on this Windows machine.
- An explicit MLZero Python launcher mode is now implemented:
  - `AI4ML_MLZERO_EXECUTION_MODE=python`
  - `AI4ML_MLZERO_PYTHON_EXECUTABLE=D:\333\AI4ML\.venv\Scripts\python.exe`
- `/api/health` can now truthfully report:
  - `provider_mode`
  - `execution_mode`
  - `provider_wire_api`
  - `provider_status`
  - `executor_status`
  - without hiding failures behind a fallback path
- The upstream MLZero path was patched so the current Windows machine can really run:
  - lazy import behavior was added around some heavy provider modules
  - `responses` API outputs are normalized before downstream parsing
  - Windows execution no longer breaks on the old bash/select pipe path
  - tutorial retrieval dependencies remain optional and now fail explicitly without blocking the main execution chain
- Real validation already completed:
  - provider smoke test passed for `/models` and `/responses`
  - MLZero smoke task passed on `data/samples/iris.csv`
  - observed smoke result:
    - `validation_score = 0.9`
    - output directory: `storage/mlzero_runs/smoke-iris-python/20260423T155759Z`
- Important current truth:
  - the runnable path on this machine is now `MLZero + python launcher + cloud openai-compatible provider`
  - this is not a hidden fallback; it is an explicit execution mode
  - `mamba` mode may still remain unavailable on this machine if the configured executable is missing

## 2026-04-24 next things to do

- Next I should convert the current cloud-provider runtime injection from temporary shell environment variables into a persistent project-level configuration flow, so the app can keep using the selected cloud provider after restart without manual re-export each time.
- Next I should run a full end-to-end validation through the real FastAPI + Supabase flow again:
  - create task
  - upload CSV
  - run task
  - verify result is returned to the frontend path, not only from a direct executor smoke script
- Requirement analysis is no longer a blocking pre-run gate. Do not reintroduce a separate target-column/problem-type parser before MLZero; natural-language task understanding should happen inside the MLZero/Agent execution flow.
- Next I should decide whether to keep tutorial retrieval optional on this Windows machine or install the remaining heavy dependencies (`faiss-cpu`, `FlagEmbedding`, related stack) and revalidate MLZero with retrieval enabled.
- Next I should clean up and align the documentation and visible UI copy so the current real runtime status is clear everywhere:
  - cloud mode is available
  - python execution mode is available
  - no silent fallback is allowed

## 2026-04-24 persistent cloud runtime config update

- Backend settings now auto-load project-local env files on startup instead of depending only on shell-exported variables.
- The active lookup chain is now:
  - `.env`
  - `.env.local`
  - `backend/.env`
  - `backend/.env.local`
  - `frontend/.env`
  - `frontend/.env.local`
- `backend/.env.local` is now the intended local persistent file for MLZero cloud runtime settings.
- A tracked template was added at `backend/.env.example`.
- Persisted non-secret runtime values were written locally for:
  - `AI4ML_MLZERO_PROVIDER_MODE=cloud`
  - `AI4ML_MLZERO_PROVIDER_BASE_URL_OVERRIDE=https://codex.miaomiaocode.com/v1`
  - `AI4ML_MLZERO_MODEL_ALIAS=gpt-5.4`
  - `AI4ML_MLZERO_PROVIDER_WIRE_API=responses`
  - `AI4ML_MLZERO_EXECUTION_MODE=python`
  - `AI4ML_MLZERO_PYTHON_EXECUTABLE=D:\333\AI4ML\.venv\Scripts\python.exe`
- The real cloud provider API key could not be recovered from the current shell, repo files, PowerShell profile, or PowerShell history.
- Therefore, restart persistence for cloud mode is now implemented at the code/config level, but final runnable validation still requires inserting the real provider key into `backend/.env.local`.

## 2026-04-24 persistent cloud runtime revalidation

- A real cloud provider API key was written into the ignored local file `backend/.env.local`.
- Persisted backend config was revalidated without temporary shell-exported AI4ML runtime variables.
- Verified current loaded runtime state:
  - `provider_mode = cloud`
  - `provider_base_url = https://codex.miaomiaocode.com/v1`
  - `model_alias = gpt-5.4`
  - `provider_wire_api = responses`
  - `execution_mode = python`
  - `python_executable = D:\333\AI4ML\.venv\Scripts\python.exe`
- Provider connectivity revalidation passed:
  - `GET /models` succeeded and listed `gpt-5.4`
  - `POST /responses` succeeded and returned the expected tiny reply
- Backend health revalidation passed through FastAPI `TestClient`:
  - `provider_status = available`
  - `executor_status = available`
  - `execution_runtime = mlzero + python launcher + cloud openai-compatible provider`
- A fresh direct MLZero smoke task was re-run successfully against `data/samples/iris.csv`.
- Observed smoke result:
  - `metric_name = validation_score`
  - `metric_value = 0.9`
  - `output_dir = D:\333\AI4ML\storage\mlzero_runs\t042155z\20260424T042155Z`
- Current truth after this revalidation:
  - cloud runtime persistence is now working
  - restart no longer depends on re-exporting AI4ML cloud runtime variables by hand
  - the direct executor path is currently runnable on this machine
## 2026-04-25 task flow simplification update

- User clarified the intended product behavior: after receiving a dataset, the AI/MLZero Agent should inspect the CSV, infer the target column and task type, write data-loading/training code, run it, and fix code based on concrete errors.
- The previous `backend/app/services/task_analysis.py` pre-run parser was identified as a harmful extra gate because it could fail before MLZero had a chance to run.
- The pre-run parser has been removed from the active task flow:
  - `backend/app/services/task_analysis.py` was deleted.
  - `backend/app/api/routes/tasks.py` no longer calls `analyze_task_requirements()` during CSV upload.
  - Uploading a CSV now only saves the file, sets task status to `uploaded`, and records that MLZero will handle target/type inference at run time.
  - `/api/tasks/{task_id}/run` no longer requires `label_column` or `problem_type` before execution.
- `backend/app/services/executors/mlzero_executor.py` now tells MLZero to:
  - read `train.csv` itself
  - inspect columns and sample values
  - infer the target column and classification/regression type during execution
  - write and run the data loading, preprocessing, training, and validation code
  - use concrete runtime errors to revise code and continue
  - report the selected target column, inferred problem type, metric name, and validation score
- Frontend behavior was updated accordingly:
  - task creation says CSV upload is enough to run MLZero
  - run buttons are enabled after dataset upload, without waiting for target-column/problem-type pre-parsing
  - copy now says target/type will be handled by MLZero at runtime
- Validation completed after this change:
  - `python -m compileall backend/app` passed
  - `cd frontend && npm run build` passed
  - residual scan found no remaining references to `task_analysis`, `analyze_task_requirements`, `_require_task_requirements`, or target-column/problem-type blocking checks
- Current task flow truth:
  - create task
  - upload CSV
  - task becomes `uploaded`
- user clicks run
- MLZero receives `train.csv` plus the natural-language task description
- MLZero/Agent is responsible for data understanding, code generation, execution, and repair
- failures should now come from the real MLZero execution path, not from a separate pre-run parser gate

## 2026-04-26 current source of truth: frontend connector + AI task analysis flow

- This section supersedes the 2026-04-25 "do not reintroduce a separate task parser" note.
- The user explicitly changed the product expectation again:
  - the page should directly use the currently configured AI connector
  - AI should fill task fields such as target column / problem type
  - the UI must not claim success while still showing "待 AI 识别 / 未解析"

### Current intended product flow

- Current expected end-to-end flow is now:
  1. User logs in with Supabase and enters a team
  2. User records an OpenAI-compatible connector in the frontend
  3. User sets that connector as the current runtime
  4. User creates a task and uploads a CSV
  5. Backend immediately calls the current runtime AI to analyze the task
  6. AI returns:
    - `label_column`
    - `problem_type`
    - `metric_name`
    - `reasoning`
    - `confidence`
  7. Frontend shows the AI-filled result
  8. User can manually click "AI 解析" to re-run analysis
  9. User then runs MLZero
  10. MLZero receives the AI-parsed task metadata and the CSV, then executes the real run

### What was wrong before

- The user's complaint was correct:
  - upstream `autogluon-assistant` still had deterministic local fallback behavior in several places
  - for the generic `machine learning` tool path, generated code could still default to:
    - `LABEL_COLUMN = "label"`
    - `PROBLEM_TYPE = "classification"`
- Therefore the old UI state could look "completed" even though target column / task type had not really been inferred by the selected AI connector.
- Tutorial retrieval warnings about `faiss-cpu` / `FlagEmbedding` are optional-dependency warnings and are not the core reason for this product-level mismatch.

### Backend changes now active

- New service added:
  - `backend/app/services/ai_task_analyzer.py`
- Task route behavior changed in:
  - `backend/app/api/routes/tasks.py`
- MLZero executor prompt/input behavior changed in:
  - `backend/app/services/executors/mlzero_executor.py`
- Connector runtime activation and probing now exist in:
  - `backend/app/api/routes/connectors.py`
  - `backend/app/services/connector_runtime.py`

### Current backend behavior

- `POST /api/tasks/{task_id}/dataset`
  - saves the CSV
  - clears old parsed fields and old run result
  - immediately tries AI analysis with the current runtime connector
- `POST /api/tasks/{task_id}/analyze`
  - forces task analysis through the current runtime AI
- `POST /api/tasks/{task_id}/run`
  - if `label_column` or `problem_type` is missing, it first forces AI analysis
  - if AI analysis fails, the route raises an error instead of silently letting defaults decide the run
- Parsed AI results are stored in:
  - `task.label_column`
  - `task.problem_type`
  - `task.structured_requirements`
  - `task.notes`
- MLZero input bundle now includes AI-derived hints such as:
  - `Label column: ...`
  - `Problem type: ...`
  - `Metric: ...`
  - `AI analysis notes: ...`

### Current frontend behavior

- The frontend task/connector shell was rewritten into a clean UTF-8 version after historical encoding corruption in `frontend/src/App.jsx`.
- Current key frontend files:
  - `frontend/src/App.jsx`
  - `frontend/src/components/ConnectorManagementPanel.jsx`
  - `frontend/src/components/TaskForm.jsx`
  - `frontend/src/components/TaskCard.jsx`
  - `frontend/src/components/SystemPanel.jsx`
  - `frontend/src/lib/api.js`
- The current task page now supports:
  - create task
  - upload CSV
  - automatic AI analysis after upload
  - manual "AI 解析"
  - MLZero run
  - display of AI reasoning / confidence / analysis model
  - display of real MLZero metric and output directory

### Current runtime truth on this machine

- Current observed backend health after validation:
  - `provider_mode = cloud`
  - `execution_mode = python`
  - `provider_wire_api = chat_completions`
  - `provider_base_url = https://api.modelarts-maas.com/v2`
  - `model_alias = deepseek-v3.2`
  - `provider_status = available`
  - `executor_status = available`
- Therefore the active runnable path is currently:
  - `MLZero + python launcher + cloud openai-compatible provider`

### Validation completed on 2026-04-26

- Frontend build passed:
  - `cd frontend && npm run build`
- Backend compile check passed:
  - `python -m compileall backend/app`
- FastAPI route smoke check passed for:
  - `/api/health`
  - `/api/connectors`
  - `/api/tasks`
  - `/api/tasks/{task_id}/analyze`
  - `/api/tasks/{task_id}/run`
- Direct AI task-analysis smoke test passed with a temporary CSV:
  - `label_column = yield`
  - `problem_type = regression`
  - `metric_name = rmse`
  - `analysis_model = deepseek-v3.2`
- API chain smoke test also passed through the real task routes:
  - create task
  - upload CSV
  - `/analyze`
  - returned `yield / regression / deepseek-v3.2`

### Important guidance for the next session

- Do not revert the product back to "CSV upload only, and let UI stay unresolved until run" unless the user explicitly asks for that behavior.
- The current user preference is clear:
  - page-level AI interaction is required
  - connector management must be real
  - task semantics should come from the configured AI connector, not from frontend placeholders or hidden defaults

## 2026-04-27 AI conversation log, token tracking, and MLZero self-repair status

- The task detail page now exposes real saved AI prompt/response history instead of only showing parsed fields or hardcoded local file summaries.
- Backend conversation aggregation is now implemented through:
  - `GET /api/tasks/{task_id}/ai-conversations`
  - service: `backend/app/services/task_ai_conversations.py`
- Conversation records currently aggregate:
  - task AI analysis prompt/response
  - MLZero `node_*/states` prompt/response pairs such as:
    - `python_coder`
    - `bash_coder`
    - `executer`
    - `error_analyzer`
    - `chat`
- The UI now distinguishes conversation origin truthfully:
  - `ai_model`
  - `local_runtime`
  - and does not pretend deterministic local generation is a model reply
- The task detail AI conversation panel was later compressed into collapsible prompt/response blocks so long conversations do not flood the page by default.

### Current token-usage truth

- Task detail and usage views now show real recorded token usage for:
  - task AI analysis
  - MLZero runtime
- MLZero token usage is read from the actual run output metadata instead of frontend estimates.
- A completed task can still show MLZero token usage even if some earlier attempts failed.

### Root cause of the 2026-04-27 "predict target yield" failure

- The user-reported failed task `7a5ac5a4` was not failing because of the iris dataset itself.
- The real failure chain was:
  - the LLM returned mixed `bash` + `python` content
  - earlier code-extraction logic could mis-handle that response shape
  - one generated Python script was truncated at the end
  - later retries still produced invalid code
  - MLZero kept spending time on bad repair cycles until timeout
- This was a real execution-chain bug, not just a UI issue.

### Current MLZero repair behavior after fixes

- The current code path should now be understood as "AI self-repair first", not deterministic fallback first.
- The previous local deterministic machine-learning fallback path in the Python coder recovery flow was removed as the default recovery behavior.
- Current hardening added around MLZero Python generation:
  - `autogluon.assistant.prompts.utils.extract_code()` was tightened so Python extraction no longer grabs shell blocks first
  - unterminated or mixed fenced-code responses are handled more safely
  - Python repair prompts now feed the model:
    - the detected issue
    - the extracted broken Python candidate
    - the previous raw assistant reply
  - repair retries explicitly require:
    - exactly one Python code block
    - no shell / bash / PowerShell / pip-install blocks
    - a compact full script so the ending is less likely to be truncated
- The Python completion validator now also checks for:
  - leftover markdown fences
  - shell-script headers
  - shell package-install commands embedded in Python candidates
  - obvious missing score output
- Validation heuristics were later relaxed so a top-level executable script is not falsely rejected only because it lacks a `__main__` wrapper, unless it defines `main()` and forgets to call it.

### Revalidation completed on 2026-04-27

- A same-class iris task (`dcbfbb47`) was re-run multiple times after the repair-chain changes.
- Observed final successful validation after the latest prompt/extractor cleanup:
  - output directory:
    - `C:\Users\LENOVO\AppData\Local\AI4ML\mlzero_runs\dcbfbb47\20260427T054759Z`
  - best node:
    - `node_0 / machine learning`
  - validation score:
    - `0.9`
  - wall-clock runtime:
    - about 64 seconds
  - token usage:
    - `input 7286`
    - `output 1823`
    - `total 9109`
- Important truth from that validation:
  - the run succeeded without `python_coder_prompt_fallback.txt` / `python_coder_response_fallback.txt`
  - only one Python repair retry was needed
  - therefore the successful path was AI self-repair, not deterministic local takeover

### Current remaining risk

- Some task names / descriptions stored in task JSON still show historical encoding corruption in older records.
- This encoding issue is separate from the MLZero timeout bug and remains worth fixing later.

## 2026-04-27 connector storage migration to Supabase

- AI connector records are no longer meant to be treated as local `storage/connectors` source-of-truth data.
- A new Supabase-backed `ai_connectors` schema path is now the intended source of truth for:
  - connector metadata
  - plaintext `api_key` storage for this prototype stage
  - per-team `is_active` runtime selection
- Backend connector routes now read/write connector records through Supabase REST with the current bearer token and `X-Team-Id` context.
- Connector activation is now team-scoped instead of writing a single global backend runtime choice into local connector storage.
- Task AI analysis and MLZero execution now resolve runtime settings from the current team's active connector when one exists.
- Local `storage/connectors` should now be considered historical residue unless a future migration/cleanup step removes it explicitly.

## 2026-04-27 business data migration to Supabase

- Task metadata is no longer intended to use `storage/tasks/<team_id>/<task_id>/task.json` as the source of truth.
- `TaskStore` now reads and writes task records through Supabase REST into `ai_tasks`.
- Uploaded CSV files still remain file artifacts on disk for now, but their `dataset_path` and metadata are stored in Supabase.
- MLZero run metadata is now mirrored into `task_runs` when a run succeeds or when a failed attempt has an output directory.
- Token usage is now mirrored into `token_ledgers` for task AI analysis and MLZero runtime usage.
- The Supabase schema now includes structural tables for future platform data: quotas, routing policies, workflow stages, human interaction requests, platform assets, and audit logs.
- Legacy local `UserStore` is disabled from the active dependency path; Supabase remains the active identity and team source of truth.
- Local files should now be treated as file artifacts only: uploaded CSVs, MLZero outputs, generated code, logs, and runtime traces.

## 2026-04-27 Supabase remote schema and write-path validation

- The user confirmed that `supabase/schema.sql` was applied to the hosted Supabase project.
- The backend can currently read Supabase configuration from `frontend/.env.local`; no secret values were printed during validation.
- Remote table visibility was checked successfully with the configured publishable key for:
  - `teams`
  - `team_members`
  - `ai_connectors`
  - `ai_tasks`
  - `task_runs`
  - `token_ledgers`
  - `quota_accounts`
  - `ai_routing_policies`
  - `workflow_stage_records`
  - `human_interaction_requests`
  - `platform_assets`
  - `audit_logs`
- Backend validation passed:
  - `python -m compileall backend\app`
  - FastAPI import / `TestClient` startup
  - `GET /api/health` returned 200
  - protected routes such as `/api/tasks`, `/api/connectors`, and `/api/usage` correctly returned 401 without a Supabase bearer token
- Frontend validation passed:
  - `cd frontend && npm run build`
- A live Supabase auth/team smoke test passed end to end:
  - temporary signup returned a usable session
  - `create_team_with_owner` created a team
  - backend `/api/tasks` accepted the Supabase bearer token plus `X-Team-Id`
  - backend task creation wrote a visible row into `ai_tasks`
  - backend connector creation wrote a visible row into `ai_connectors`
  - connector activation set `is_active = true`
  - plaintext connector `api_key` storage was verified by exact match, but the value was not printed
  - `/api/usage` returned successfully for the test team
- A service-layer write-path smoke test also passed for:
  - `task_runs`
  - `token_ledgers`
- Cleanup status:
  - smoke-test task rows and connector rows were deleted after validation
  - temporary Supabase Auth users and their test teams may remain because the app is not using a service-role admin cleanup path
- Current conclusion:
  - the Supabase business-data migration is functionally live for connectors, task metadata, task run records, and token ledger records
  - local `storage` should no longer be considered the source of truth for those business records
- Remaining validation gap:
  - this validation intentionally did not run a full MLZero training/analyze job, to avoid consuming model calls
  - the verified part is the Supabase storage/write/read path that MLZero depends on

## 2026-04-28 AutoGluon root-cause fix and real validation

- 用户本轮明确要求：
  - 代码里不能再写“兜底 / fallback”式成功路径
  - 有问题必须查根因并正面修掉
  - 需要真实跑通一次来验证，不接受只做静态分析
- 当前真实运行时配置已再次确认：
  - `provider_mode = cloud`
  - `base_url = https://api.modelarts-maas.com/v2`
  - `wire_api = chat_completions`
  - `model_alias = deepseek-v3.2`
  - `execution_mode = python`
  - `python_executable = D:\333\AI4ML\.venv\Scripts\python.exe`
  - 默认搜索配置仍是：
    - `mlzero_max_iterations = 6`
    - `mlzero_continuous_improvement = True`
    - `mlzero_min_candidate_models = 3`

### 本轮定位出的真实根因

- 之前“任务太简单、没有真正比较模型”的问题，不是单一原因，而是多处链路一起导致：
  1. 生成代码把 AutoGluon 跑成了 `presets='extreme'`
  2. 这个 preset 会切到依赖 GPU 和大量可选扩展的组合
  3. 当前环境实际缺少：
     - `torch`
     - `lightgbm`
     - `xgboost`
     - `catboost`
     - `tabpfn`
     - `tabicl`
     - `tabm`
  4. 因此 AutoGluon 会出现“训练 0 个可用模型”的真实失败
  5. 之前的提示词又把这类失败引导成脚本内切换到 `scikit-learn`
  6. 这就形成了用户不接受的“换库兜底”路径
- 在继续真实排查时，又额外发现了 3 个会导致假成功或半成功的根因：
  - 生成代码错误调用了不存在的 `predictor.get_model_best()`
  - 生成代码错误假设 `leaderboard()` 自带 `rank` 列
  - 生成代码把通用 `classification` 直接传给 AutoGluon，但 AutoGluon 真实接受的是 `binary` 或 `multiclass`

### 已实施修复

- `backend/app/services/executors/mlzero_executor.py` 现在会把当前环境中真实可用的 AutoGluon能力明确写入任务描述：
  - 当前已验证可直接使用的候选模型族是：
    - `RF`
    - `XT`
    - `KNN`
- 同一文件中已明确约束：
  - tabular 任务要继续用 `autogluon.tabular`
  - 不允许再写第二套 `sklearn` 实现路径
  - 不允许再使用 `extreme / best / high / good` 这一类依赖可选扩展的 preset/portfolio
  - 必须根据标签类别数把 classification 映射为 `binary` 或 `multiclass`
  - 必须使用 `predictor.model_best` 或 leaderboard 首行，不得再调用 `get_model_best()`
  - 如果需要 `rank`，必须按排序结果自行生成，不能假设 AutoGluon 自带该列
- `external/autogluon-assistant/src/autogluon/assistant/prompts/python_coder_prompt.py` 已同步更新为同样的强约束。
- 后端 summary 解析也已修正：
  - leaderboard 的 `tool` 字段优先采用 `run_summary.json` 里的真实执行工具
  - 如果 `candidate_model_count > 1`，但没有真正产出可解析的候选模型 leaderboard，执行器现在会直接判失败，而不是再把 node 级结果当成功

### 本轮真实验证结果

- 本轮做过多次真实运行，其中前几次真实运行先后暴露并帮助修掉了上述根因。
- 最终通过的一次真实 smoke run 为：
  - `task_id = verify-iris-autogluon-rootcause-v4`
  - `output_dir = C:\Users\LENOVO\AppData\Local\AI4ML\mlzero_runs\verify-iris-autogluon-rootcause-v4\20260428T074558Z`
- 这次真实成功运行的关键事实：
  - 生成代码只使用了 `autogluon.tabular`
  - 没有再出现脚本内切换到 `scikit-learn` 的第二实现路径
  - 成功产出了：
    - `node_0/output/run_summary.json`
    - `node_0/output/leaderboard.csv`
- 本次真实结果为：
  - `best_model = WeightedEnsemble_L2`
  - `metric_name = accuracy`
  - `metric_value = 1.0`
  - `leaderboard_count = 4`
- 真实 leaderboard 记录到的候选模型为：
  - `ExtraTrees = 1.0`
  - `WeightedEnsemble_L2 = 1.0`
  - `KNeighbors = 1.0`
  - `RandomForest = 0.9333333333333333`

### 当前结论

- 当前代码状态下，tabular 任务已经不是“随便跑一个简单模型”了。
- 对当前这台机器上的真实可用环境而言，系统现在会：
  - 继续走 `autogluon.tabular`
  - 只比较当前环境真正支持的候选模型族
  - 真实落盘 leaderboard 产物
  - 由后端把候选模型结果返回给前端/调用方
- 当前默认的 6 轮持续改进配置仍然保留，但本轮最终验收跑通的是：
  - `mlzero_max_iterations = 1` 的 smoke 验证
- 也就是说：
  - “AutoGluon-only、多模型比较、真实 leaderboard 落盘”这一条已经真实跑通
  - 但“默认 6 轮持续改进配置下的完整长时运行”还没有在本轮最后一次修复后重新做长跑验收

### 下次继续时最应该记住的事

- 不要再把 tabular 任务失败处理成“切 sklearn 继续跑”的兜底方案。
- 如果再出现运行问题，优先检查：
  - 生成代码是否又用了不该用的 preset
  - `problem_type` 是否正确映射成 `binary/multiclass/regression`
  - leaderboard 落盘逻辑是否完整
  - 当前环境中 AutoGluon 可选依赖是否发生变化

## 2026-04-28 follow-up: no-fallback cleanup completed and real 5-minute chain passed

- 本轮后续工作继续围绕用户的同一条要求推进：
  - 不允许保留“看起来成功”的兜底逻辑
  - 必须把真正的根因修掉
  - 必须重新做真实运行验收

### 本轮额外移除的兜底/假成功路径

- `external/autogluon-assistant/src/autogluon/assistant/agents/coder_agent.py`
  - 已删除机器学习代码生成里的本地 deterministic baseline 分支，不再从 `AUTOGLOUON_ASSISTANT_ENABLE_DETERMINISTIC_ML_BASELINE` 切到本地 `sklearn` 路径。
  - Python 修复提示里残留的“改写成简短 sklearn baseline”倾向也已去掉。
- `external/autogluon-assistant/src/autogluon/assistant/agents/executer_agent.py`
  - 已删除“子进程失败但靠工件恢复 validation_score 后仍视为成功”的恢复路径。
  - 当前只有真实执行成功且输出中存在可解析验证分数时才会走成功判断。
- `backend/app/services/ai_task_analyzer.py`
  - `metric_name`
  - `reasoning`
  - `confidence`
  这些字段都不再允许默认兜底，缺失或非法时直接报错。
- `backend/app/services/connector_runtime.py`
  - `backend/app/api/routes/tasks.py`
  - 现在必须存在真实的 active connector；没有激活连接器时不再偷偷退回默认运行时。
- `external/autogluon-assistant/src/autogluon/assistant/agents/tool_selector_agent.py`
  - `external/autogluon-assistant/src/autogluon/assistant/prompts/tool_selector_prompt.py`
  - 已去掉默认工具、closest-match 替换和本地启发式绕过，恢复为真实 LLM 选择路径。
- `external/autogluon-assistant/src/autogluon/assistant/agents/retriever_agent.py`
  - `external/autogluon-assistant/src/autogluon/assistant/agents/reranker_agent.py`
  - 已去掉检索/重排的启发式 fallback；输出格式错误时现在直接报错。
- `backend/app/services/executors/mlzero_executor.py`
  - 已删除 timeout / 非零退出 / 文本解析恢复 summary 的兜底链路。
  - 现在必须依赖规范工件：
    - `run_summary.json`
    - `leaderboard.json` 或 `leaderboard.csv`

### 这次真实排查中又发现并修掉的根因

- 根因 1：执行预算设计错误，不是模型不稳定
  - 之前 5 分钟任务仍被固定传入：
    - `-n 6`
    - `--continuous_improvement`
  - 结果是任务在已经成功后还继续跑第 2、3、4 轮，最后被 300 秒总超时打断。
- 根因 2：leaderboard 工件契约前后冲突
  - Prompt 一边要求最终工件必须有 `validation_score`
  - 一边又让模型“按 AutoGluon 原始列直接保存”
  - 结果真实成功运行后落盘的是原始 `score_val` / `pred_time_val`，后端严格解析时自然判失败。
- 根因 3：Windows `best_run` 使用 directory junction 时，旧代码把它当普通目录 `rmtree`
  - 这会在多轮成功路径里报：
    - `Failed to remove existing best_run folder/link: Cannot call rmtree on a symbolic link`

### 当前新增修复

- `backend/app/services/executors/mlzero_executor.py`
  - 新增 `_resolve_search_plan(time_limit)`。
  - 现在会根据用户给定 `time_limit` 推导本次 MLZero 搜索规模，而不是固定硬跑 6 轮。
  - 对小预算任务会关闭 `continuous_improvement`，避免“已经成功还继续搜索”。
  - 当前 5 分钟预算下的真实计划为：
    - `max_iterations = 3`
    - `continuous_improvement = false`
- `backend/app/services/executors/mlzero_executor.py`
  - `external/autogluon-assistant/src/autogluon/assistant/prompts/python_coder_prompt.py`
  - `external/autogluon-assistant/src/autogluon/assistant/tools_registry/autogluon.tabular/tool.json`
  - 已统一要求最终 leaderboard 工件必须先规范化：
    - `model`
    - `validation_score`
    - `fit_time`
    - `pred_time`
  - 不允许再把 `score_val` / `pred_time_val` 作为最终工件字段名原样落盘。
- `external/autogluon-assistant/src/autogluon/assistant/managers/node_manager.py`
  - 已补 Windows reparse point / directory junction 识别逻辑。
  - 现在删除 `best_run` 时会正确区分：
    - symlink
    - Windows junction
    - 普通目录
  - 同时移除了“当前节点正被 best_run 指向”时只检查 symlink、不检查 junction 的漏洞。

### 2026-04-28 最终真实验收结果

- 使用真实服务链路做了完整重跑，不是只做静态检查。
- 验证脚本链路为：
  - `analyze_task_with_ai(...)`
  - `apply_analysis_to_task(...)`
  - `MLZeroExecutor(settings).run(task, dataset_path, 5)`
- 本次最终成功报告：
  - `D:\333\AI4ML\tmp_executor_verify\codex-e2e-20260428093556-report.json`
- 本次最终成功输出目录：
  - `C:\Users\LENOVO\AppData\Local\AI4ML\mlzero_runs\codex-e2e-20260428093556\20260428T093602Z`
- 真实运行关键事实：
  - `time_limit_minutes = 5`
  - `max_iterations = 3`
  - `continuous_improvement = false`
  - 在首次成功后立即停止继续搜索
  - 总体 wall-clock 大约 76 秒
- AI 任务分析真实结果：
  - `label_column = label`
  - `problem_type = classification`
  - `metric_name = accuracy`
  - `analysis_model = deepseek-v3.2`
- 最终真实 MLZero 结果：
  - `best_model = WeightedEnsemble_L2`
  - `metric_name = accuracy`
  - `metric_value = 1.0`
  - `leaderboard_count = 4`
- 当前成功落盘并被后端严格解析通过的候选模型结果为：
  - `ExtraTrees = 1.0`
  - `WeightedEnsemble_L2 = 1.0`
  - `KNeighbors = 1.0`
  - `RandomForest = 0.9333333333333333`

### 现在的真实结论

- 当前代码状态下，5 分钟预算的真实端到端链路已经跑通：
  - AI 解析
  - AI 结果写回任务
  - MLZero 真实执行
  - 规范 `run_summary.json`
  - 规范 leaderboard 工件
  - 后端严格摘要解析
- 这次成功不依赖：
  - 本地 `sklearn` 替代实现
  - 非零退出后的 artifact 恢复成功
  - 默认连接器/默认工具/closest-match 替换
  - 宽松 leaderboard 字段兼容

### 当前剩余注意事项

- 教程检索依赖仍是可选状态；当前运行中如果缺少：
  - `faiss-cpu`
  - `FlagEmbedding`
  - 相关依赖
  会明确记录“retrieval disabled”，但不会再伪装成主链路成功原因。
- 当前真实可运行链路依然是：
  - `MLZero + python launcher + cloud openai-compatible provider`
- 如果后面又出现“成功但摘要失败”这类现象，优先检查：
  - 生成代码是否又把 raw `score_val` 当最终 leaderboard 字段落盘
  - `run_summary.json` 是否缺少规范键
  - 当前团队是否真的有 active connector

## 2026-04-28 frontend AI conversation page refactor toward Codex-style layout

- 用户本轮明确要求：
  - `AI Conversation Log` 不要继续塞在任务详情页里占大块空间
  - 需要做成左侧主导航下的独立页面模块
  - 页面内部不要再是“每轮一张大卡片”的列表式展示
  - 希望更接近 Codex / Claude 这种“单窗口、连续消息流、主区域以对话为中心”的界面

### 本轮最终前端形态

- `AI 对话` 现在已经是一级导航页面，不再嵌在任务详情中。
- 当前页面不是旧版的折叠日志卡片，而是：
  - 单个主对话窗口
  - 连续的 `Prompt -> Response -> Prompt -> Response` 消息流
  - 每组阶段之间只保留轻量 marker，而不是整块分组卡片
- 页面布局也已经从“页内大左栏 + 右侧对话”的结构，进一步收口成更接近 Codex 的形式：
  - 页面主宽度优先留给中间消息流
  - 任务切换被收进顶部紧凑工具条
  - 不再保留会额外占一整列宽度的页内任务侧栏
  - 外层页头中重复的“当前任务”展示也已去掉，避免双重占位

### 当前真实交互

- 左侧全局导航新增：
  - `AI 对话`
- 在 `任务` 页中：
  - 任务详情里的旧 `AI Conversation Log` 大卡片已被移除
  - 现在只保留一个轻量入口区，引导用户进入独立 `AI 对话` 页查看完整问答流
- 在 `AI 对话` 页中：
  - 可通过顶部任务选择器切换当前任务
  - 顶部会显示当前任务状态、刷新按钮、返回任务详情按钮
  - 中部保留轻量上下文信息：
    - 数据集
    - 任务类型
    - 最近结果
    - 记录数量
  - 主区域是连续消息流，不再以“Round 卡片列表”作为主要视觉

### 当前数据真相

- 本轮只改了前端展示和页面布局，没有改后端会话数据接口。
- 当前对话页继续消费已有接口：
  - `GET /api/tasks/{task_id}/ai-conversations`
- 也就是说：
  - 数据来源仍然是任务 AI 分析记录 + 最新 MLZero 相关 prompt/response 记录
  - 变化的是前端如何组织与呈现这些记录，而不是后端返回结构

### 本轮关键改动文件

- `frontend/src/App.jsx`
  - 新增 `AI 对话` 一级导航入口
  - 从任务详情中移除旧的 AI 日志大卡片
  - 调整对话页页头，减少重复占位信息
- `frontend/src/components/AIConversationPanel.jsx`
  - 整体重写为更接近 Codex 的单窗口对话界面
  - 使用顶部任务选择器替代页内大左栏
  - 将会话记录展开为连续消息流
- `frontend/src/styles.css`
  - 新增/重写 AI 对话页的页面布局与聊天样式
  - 压缩工具条与上下文区
  - 提升中间消息流的有效宽度
- `frontend/dist/*`
  - 构建产物已更新

### 本轮验证

- 已执行：
  - `cd frontend`
  - `npm run build`
- 当前前端构建通过。

### 下次继续时最应该记住的事

- 不要把 `AI 对话` 页又改回“任务详情页里的大块日志卡片”。
- 不要再做“页内宽左栏 + 右侧内容”的二次侧栏结构；当前用户明确更偏好 Codex 风格的主对话优先布局。
- 如果还要继续优化这个页面，优先顺序应是：
  1. 把顶部上下文信息条再压缩成更细的 inline pills
  2. 继续把消息列宽度和留白调到更像真实聊天产品的阅读节奏
  3. 视需要再把消息体升级为更强的 markdown / code block 阅读样式

## 2026-04-28 frontend AI code workspace implementation and UX cleanup

- 用户本轮明确要求：
  - 需要实现“人机协同”的代码查看与修改能力
  - 前端必须能直接看到 AI 写出来的真实代码，而不是假数据或静态示意
  - 代码查看体验要尽量接近 VSCode，而不是把一堆运行工件原样堆给用户

### 当前已经实现的真实能力

- 左侧全局导航新增：
  - `代码工作区`
- 当前页面已可直接读取最新一次 MLZero 运行目录中的真实文本工件。
- 已接入的真实后端接口为：
  - `GET /api/tasks/{task_id}/code-workspace`
  - `GET /api/tasks/{task_id}/code-workspace/file?path=...`
  - `PUT /api/tasks/{task_id}/code-workspace/file`
- 读取范围当前是真实运行工件，不是伪造数据，且来源优先级为：
  1. `task.last_run_attempt.output_dir`
  2. 否则退到 `task.last_run.output_dir`

### 当前真实约束

- 当前只展示可安全读取的文本类工件：
  - `.py`
  - `.txt`
  - `.json`
  - `.csv`
  - `.yaml/.yml`
  - `.md`
  - `.log`
  - `.sh/.ps1/.bat/.sql`
  - 以及无扩展名的 `stdout` / `stderr`
- 当前不会展示：
  - 二进制模型文件
  - PDF
  - `best_run` 影子副本
- 当前“保存修改”只会把内容写回本次运行目录中的对应工件。
- 当前还没有实现：
  - 保存后自动重跑
  - 保存后自动同步回更高层任务配置
  - 多文件标签页
  - 真正的 Monaco / VSCode 编辑器内核

### 本轮已解决的用户问题

- 用户先后指出了 4 个真实体验问题：
  1. 点“查看 AI 代码”时页面空白
  2. 切换不同代码文件时响应慢
  3. 左侧文件列表太乱，看不懂每个文件是干什么的
  4. 长日志/长文件打开后，左侧筛选区会被带到下面去
- 当前修复结果：
  - 空白页问题已补齐加载态、空态、错误态，不再静默白屏
  - 文件切换已增加内存缓存和预取，优先缓存核心文件
  - 文件列表不再默认展示“几乎所有文本工件”，而是默认展示“核心文件”
  - 左侧文件区和右侧代码区现在是固定工作台里的独立滚动区域，不再因为长日志把整块布局一起撑高

### 当前代码工作区的前端组织方式

- 默认视图为：
  - `核心文件`
- 还支持切换：
  - `代码生成过程`
  - `运行结果`
  - `调试日志`
  - `全部工件`
- 当前每个文件都会携带语义信息，而不是只给路径：
  - `display_name`
  - `purpose`
  - `editing_guidance`
  - `group`
  - `stage`
  - `node`
  - `is_core`
- 右侧当前文件区除了代码内容，还会直接解释：
  - 这个文件是什么
  - 它属于哪个阶段
  - 是否建议编辑
  - 当前是只读还是可编辑

### 当前对“哪些文件最值得先看”的真实定义

- 当前会优先识别并突出这些文件：
  - `node_x/generated_code.py`
    - 最终执行代码
  - `node_x/states/python_code.py`
    - Python 草稿代码
  - `node_x/execution_script.sh`
    - 执行脚本
  - `summary.txt`
    - 运行摘要
  - `validation_predictions.csv` / `results.csv`
    - 结果输出
  - `token_usage.json`
    - token 记录
  - `python_coder_prompt.txt`
    - 写代码 Prompt
  - `python_coder_response.txt`
    - 写代码 AI 回复
- 这意味着当前页面不再只是“列文件名”，而是已经在尝试告诉用户：
  - 哪个是最终代码
  - 哪个只是过程文件
  - 哪个只是日志

### 本轮关键改动文件

- `backend/app/models/task.py`
  - 为代码工件补充语义字段
- `backend/app/services/task_code_workspace.py`
  - 新增真实工件扫描、分类、说明和读写能力
- `backend/app/api/routes/tasks.py`
  - 挂载代码工作区相关 API
- `frontend/src/components/CodeWorkspacePanel.jsx`
  - 新增代码工作区页面
  - 支持任务切换、筛选视图、文件用途说明、查看与编辑
- `frontend/src/lib/api.js`
  - 新增代码工作区接口调用
- `frontend/src/App.jsx`
  - 新增 `代码工作区` 一级导航入口
- `frontend/src/styles.css`
  - 新增编辑器式布局
  - 后续又修正为“左侧文件区 / 右侧代码区”独立滚动

### 本轮验证

- 已执行：
  - `python -m compileall backend\\app`
  - `cd frontend && npm run build`
- 还做过一次真实服务层检查：
  - 使用真实任务记录读取代码工作区
  - 已确认核心文件会被优先识别，例如：
    - `generated_code.py`
    - `python_code.py`
    - `execution_script.sh`
    - `summary.txt`
    - `validation_predictions.csv`
    - `token_usage.json`

### 当前仍需记住的限制与风险

- 当前虽然已经有“像编辑器一样查看和修改 AI 代码”的基础能力，但它仍然是工件编辑器，不是完整 IDE。
- 当前保存修改并不会自动触发：
  - 再运行
  - 再评测
  - 再同步 leaderboard
- 如果后面用户继续抱怨“代码区像堆文件，不像 IDE”，优先继续做的不是再加更多文件，而是：
  1. 多标签页
  2. 左侧树形层级折叠
  3. 只看可编辑文件
  4. 保存后触发 rerun 的明确入口

## 2026-04-30 frontend workspace visual redesign and task-detail cleanup

- 用户本轮明确反馈：
  - 当前前端整体“太丑”，各部分不够清晰。
  - 任务页左侧深色导航和右侧白色内容之间过渡突兀。
  - 任务详情右栏太长，尤其是候选模型对比和 MLZero 运行 Token 明细占用过多空间。
  - 连接器 / 模型录入页面还不够优美，需要更像正式配置页面。

### 当前前端视觉方向

- 前端已经从早期的大面积深色侧栏 + 白色内容卡片，调整为更统一的浅色 SaaS 工作台风格。
- 左侧导航现在按模块分组：
  - 建模工作台
  - 协同与资产
  - 团队治理
  - 运行状态
- 侧栏改为浅色导航面板，当前选中项使用：
  - 白底浮起
  - 柔和蓝色文字
  - 左侧细蓝色强调线
- 顶栏现在显示：
  - 当前页面名称与说明
  - 当前团队运行时连接器状态
  - 团队切换、刷新和退出入口
- 当前视觉系统更偏成熟后台产品：
  - 克制色彩
  - 8px 圆角
  - 更细边框
  - 更轻阴影
  - 更明确的信息层级

### 任务页结构调整

- `任务` 页面已经重构为更清晰的三块：
  1. 创建任务并上传 CSV
  2. 任务列表
  3. 当前任务详情
- `TaskForm` 不再使用多层 `section-card` 嵌套。
- 阶段 AI 覆盖区域现在使用 `stage-route-card` 网格展示。
- 人工参与策略区域现在使用 `policy-card` 展示。
- `TaskCard` 已改成摘要式任务卡：
  - 状态
  - AI 解析状态
  - 数据集
  - 目标列
  - 任务类型
  - 最佳候选
  - 候选数
  - 最近结果
  - Token 摘要
- 任务详情右栏使用 `task-detail-panel`，在宽屏下 sticky，窄屏下恢复普通流式布局。

### 任务详情折叠区

- 候选模型对比不再默认展开完整 leaderboard。
- 现在改成 `details` 折叠区：
  - 默认只显示最佳候选、候选数量和指标摘要
  - 点击“查看详细”后展开完整候选模型对比表
  - 展开后按钮显示“收起详情”
- Token 用量明细也改成折叠区：
  - 默认只显示合计摘要
  - 点击后展开 AI 解析 Token 和 MLZero 运行 Token 明细
- `LeaderboardPanel` 新增 `embedded` 模式，用于在折叠区内部展示时避免重复外层大卡片。
- `TokenUsageCard` 新增 `embedded` 模式，用于在折叠区内部展示时避免再次占用整张大卡片。

### 连接器页面改版

- `连接器` 页面已经从两个普通说明块改成配置中心布局。
- 当前结构为：
  - 左侧：新建连接器表单
  - 右侧：已保存连接器 / 运行时池
- 新建连接器区域新增更清晰的录入示例：
  - `https://api.example.com/v2/chat/completions`
- 已保存连接器改成独立 `connector-card`：
  - 连接器名称
  - 模型 ID
  - Base URL
  - Wire API
  - API Key 脱敏
  - 最后测试时间
  - 测试状态
  - 当前运行时状态
- 当前运行时连接器有蓝色细线与轻阴影强调。
- 原有后端接口与业务逻辑未改：
  - 保存连接器
  - 测试连接
  - 设为当前运行时
  - 刷新列表

### 本轮关键改动文件

- `frontend/src/App.jsx`
  - 导航分组
  - 顶栏运行时状态
  - 任务页结构
  - 任务详情候选模型 / Token 折叠区
- `frontend/src/components/TaskForm.jsx`
  - 阶段 AI 覆盖和人工参与策略结构去嵌套化
- `frontend/src/components/TaskCard.jsx`
  - 任务卡片摘要式重排
- `frontend/src/components/LeaderboardPanel.jsx`
  - 新增 `embedded` 展示模式
- `frontend/src/components/TokenUsagePanel.jsx`
  - `TokenUsageCard` 新增 `embedded` 展示模式
- `frontend/src/components/ConnectorManagementPanel.jsx`
  - 连接器页面改为配置中心布局
- `frontend/src/styles.css`
  - 新增并覆盖当前工作台视觉系统
  - 新增任务详情折叠区样式
  - 新增连接器配置中心样式

### 本轮验证

- 已多次执行：
  - `cd frontend`
  - `npm run build`
- 构建通过。
- 每次构建后都已恢复 `frontend/dist`，避免把忽略目录里的构建产物混入源码改动。

### 下次继续时最应该记住的事

- 用户对视觉质量仍较敏感；后续前端改动应优先保持：
  - 浅色统一工作台风格
  - 避免突兀的大面积黑色或高饱和色块
  - 避免卡片嵌套卡片
  - 右侧任务详情不要无限拉长
  - 长表格和明细默认折叠，只展示摘要
- 如果继续优化任务页，优先考虑：
  1. 进一步压缩任务详情中的 AI 解析说明和 AI 对话入口
  2. 让任务创建表单支持折叠“高级配置”
  3. 把阶段 AI 覆盖默认收起，只在需要覆盖默认路由时展开
  4. 对连接器页面做真实空态和错误态视觉 polish

## 2026-04-30 strict no-fallback runtime cleanup

- 用户继续明确要求：不要为了避免报错保留兜底成功路径；真实 bug 必须可观察、可定位。
- 本轮后端阶段 AI 路由已改为严格显式选择：
  - 不再把当前 active connector 当作缺失 `connector_id` 时的隐式补位。
  - 不再把团队路由里的 fallback connector/model 当作运行时候选。
  - 只填模型名但没有 `connector_id` 时直接返回 409/422。
  - 路由引用不存在的连接器或无法解析模型名时直接失败。
- 默认 AI 前端页面已去掉 fallback 连接器/模型表单；保存时会清空旧 fallback 字段。
- 任务创建表单已禁止“只填模型覆盖、不选连接器”的配置。
- CSV 上传后的 AI 解析失败现在会让请求失败，不再把失败写进 notes 后继续展示上传成功。
- 交互式 AI 对话、任务 AI 解析和 MLZero 摘要解析现在都要求真实 provider token usage / `token_usage.json`，缺失即失败。
- AutoGluon Assistant 中会伪装成功或吞掉内部错误的分支已继续收紧：
  - executer 启动/监控异常会抛出 RuntimeError。
  - retriever/reranker 不再跳过格式错误的检索结果、重复/越界索引、不可读教程文件。
  - embedding 结果出现 NaN/Inf 不再替换成 0，而是直接失败。
- 注意：数据库 schema 中历史 fallback 字段暂时保留以兼容旧表结构，但当前 API/UI/运行时不再使用它作为执行兜底。

## 2026-05-01 requirements gap implementation pass

- 本轮按需求缺口顺序继续补齐真实能力，继续遵守“不伪造结果、不静默 fallback”的约束。
- 已补齐工作流阶段事件落库：AI 解析、MLZero 运行开始、失败、成功都会写入 `workflow_stage_records`。
- 已新增模型报告与在线预测 Demo：
  - `GET /api/tasks/{task_id}/report`
  - `POST /api/tasks/{task_id}/prediction-demo`
  - 报告和 Demo 只读取真实数据集画像、真实运行摘要、真实 AutoGluon predictor；缺少产物时明确返回不支持。
- 已增强人机协同：支持确认、修改、驳回、转交、跳过、过期等状态/动作，并在 reject/revise 后标记任务需要重跑。
- 已增强资产中心：支持团队广场筛选、发布、Fork 派生，发布/Fork 信息写入 asset metadata。
- 已增强代码工作区：保存版本记录、下载工件、重跑 Python 工件，重跑 stdout/stderr 写入真实运行目录。
- 已增强连接器密钥安全和审计：
  - 新增 `AI4ML_CONNECTOR_SECRET_KEY`。
  - 新保存/更新的连接器 API Key 会以 `enc:v1:` 前缀加密存储。
  - 历史明文仍可读取；已加密密钥若缺少原 secret key 会明确失败。
  - 连接器 create/test/activate 和任务 create/update/analyze/run/delete、人机协同、代码工作区、在线预测等操作会写审计日志。
- 文档已补充新接口、连接器密钥环境变量、真实产物限制说明。

## 2026-05-02 P0 closed-loop completion pass

- 本轮继续把 P0 中“后端已有能力但前端不可操作”的缺口补成闭环。
- 团队治理闭环：
  - 新增团队所有者专属设置入口，可维护团队名称、说明和状态。
  - 新增所有权转移入口，只能转给 active 成员；转移后当前所有者降为管理员。
  - 成员表不再把 `team_owner` 当作普通角色可直接分配，团队所有者变更必须走所有权转移。
- 连接器生命周期闭环：
  - 前端已支持连接器编辑、保留旧 API Key、替换新 API Key、停用、删除、批量健康检查。
  - 批量健康检查会真实调用每个连接器并写回测试状态，不使用假成功。
  - 删除和停用会同步刷新运行时状态与审计日志。
- 工作流进度闭环：
  - 阶段面板现在展示 `workflow_stage_records.artifact_refs` 中的真实关键产物路径。
  - MLZero 运行成功/失败后，前端可以按阶段看到代码、leaderboard、run summary、日志等入口。
- 人机协同重跑语义：
  - reject/revise 决策会记录 `rerun_from_stage`。
  - 阶段快照会把该阶段及下游阶段标记为待重跑，用户能看到明确的恢复边界。
- 本轮验证：
  - `python -m compileall backend\app`
  - `python -m unittest discover backend\tests`
  - `npm run build`
- 当前注意事项：
  - “从某阶段重跑”已不再只是状态与指引闭环；当前后端已经接入 `backend/app/services/task_incremental_rerun.py` 的严格增量实现。
  - `requirement_analysis` / `data_analysis` 会先重新执行 AI 解析再继续下游阶段；`feature_engineering` 会重新生成并执行代码；`model_selection` / `training_validation` 会复用既有 `generated_code.py` 并改写运行路径后执行；`report_generation` 不训练，只复用真实产物并重建报告快照。
  - 增量重跑缺少必要历史产物时必须明确失败，例如缺少上一次 output directory 或缺少 `generated_code.py`，不能静默退回整次 MLZero 运行。
  - Supabase 上线环境必须应用最新 `supabase/schema.sql`，否则团队设置字段、连接器增删改、阶段产物记录、严格增量重跑相关状态可能缺表/缺字段/缺策略。
