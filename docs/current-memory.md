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

## 2026-05-03 requirements first-seven completion pass

- 本轮按前面梳理出的需求缺口前 7 项继续补齐，仍遵守“不伪造结果、不静默 fallback”的约束。
- 已补齐 CSV 上传与数据集画像：
  - 上传改为分块写入，增加文件名、Content-Type、空文件、二进制空字节和 100MB 大小限制。
  - `TaskRecord` 新增 `dataset_profile`，保存真实列名、行列数、缺失值比例、样例值和预览行。
  - 任务详情页新增“数据集画像”区，展示真实预览和缺失概览。
- 已补齐工作流阶段可视化所需字段：
  - `workflow_stage_records` 新增 `started_at / finished_at / duration_seconds / log_excerpt`。
  - 阶段进入新一轮 running 时会重置旧完成时间，避免沿用上次运行耗时。
  - 工作流页展示阶段开始/结束、耗时、日志摘要和人工节点截止时间。
- 已补齐 Token 逐次流水与原子扣减：
  - `supabase/schema.sql` 新增 `adjust_member_token_usage(...)` RPC，Token 用量写账后原子更新成员额度。
  - 后端新增 `GET /api/team/token-ledgers`，管理员可按团队查看成员、任务、阶段、连接器、模型、输入/输出/总 Token 和核算方式。
  - Token 用量页新增管理员可见的 Token 调用流水表。
- 已补齐资产元数据模型：
  - `platform_assets` 新增 `category / tags / visibility / version / source_task_id / source_asset_id / model_card / published_at`。
  - 后端资产创建、审核、发布、Fork 已读写这些字段，审核状态与可见性分离。
  - 资产列表支持按 `asset_type / review_status / visibility / category` 查询。
- 已补齐数据中心 / 模型广场 / 工作流广场的真实页面能力：
  - 资产页表单支持分类、标签、可见性、版本、来源任务和模型卡片 JSON。
  - 资产表展示分类、标签、可见性、版本、来源任务或 Fork 来源。
  - 管理员可在页面上修改分类、标签和可见性，不再只是数据库字段。
- 已补齐从任务沉淀资产的入口：
  - 资产页可从当前任务一键登记数据集、模型、报告或工作流为 `pending_review` 资产。
  - 模型资产会写入真实 `last_run` 指标、最佳模型、输出目录、leaderboard 和数据集画像。
  - 工作流资产会写入阶段路由、人机协同策略、结构化需求和最近运行信息，供后续 Fork 复用。
- 已补齐 Fork 来源与版本语义：
  - Fork 资产会写入 `source_asset_id`，保留来源任务、分类、标签、模型卡片和来源 metadata。
  - 前端 Fork 时可填写新版本号；新副本默认私有、独立可审核/发布。
- 本轮验证：
  - `python -m compileall backend\app`
  - `python -m unittest discover backend\tests`，当前 24 个测试通过。
  - `npm run build`，构建通过；仅保留 Vite chunk size warning。
- 当前注意事项：
  - Supabase 上线环境必须重新执行最新 `supabase/schema.sql`，否则 `dataset_profile`、阶段耗时/日志字段、资产元数据字段、`adjust_member_token_usage` RPC 和 Token 流水页面都会缺依赖。
  - TokenLedger 的 `calculation_method` 当前仍以 provider usage / MLZero token_usage.json 为主；需求文档中的 tokenizer 离线复算只应在后续确实接入 tokenizer 后启用，不能用固定倍率估算。

## 2026-05-05 multi-agent collaboration and speed pass

- 用户本轮连续关注两个核心问题：
  - 项目是否已经是“多 Agent 协同”形式。
  - 所有页面切换、加载和使用体感太慢，要求“极速”优化。
- 当前已新增真实的 `多 Agent 协同中心` 页面：
  - 前端文件：`frontend/src/components/MultiAgentCollaborationPanel.jsx`
  - 导航入口：`Agent 协同`
  - 映射 6 个协作 Agent：
    - Agent-Alpha：需求解析
    - Agent-Beta：数据分析
    - Agent-Gamma：特征工程
    - Agent-Delta：模型选择
    - Agent-Epsilon：训练验证
    - Agent-Zeta：报告生成
  - 页面使用真实 `GET /api/tasks/{task_id}/human-collaboration` 快照，不使用假数据。
  - 布局已按用户反馈改过：去掉挤占空间的左侧任务栏，任务选择器上移到顶部，协作图获得完整宽度，状态表和事件日志放到底部区域。

### 当前多 Agent 的真实边界

- 当前“多 Agent 协同”已经有前端可视化和阶段/人工协同状态映射。
- 当前 6 个 Agent 是围绕现有 MLZero/工作流阶段的可观察协作视图，不是已经启动 6 个独立后端进程或 6 个独立模型 worker。
- 页面必须继续保持真实状态原则：
  - 只展示任务、阶段、人工协同请求、产物和运行事件中已经存在的真实信息。
  - 不要为了让 Agent 看起来繁忙而生成假日志、假产物、假进度。

### 当前极速优化已经完成的内容

- 前端请求层优化：
  - `frontend/src/lib/api.js` 增加 30 秒 GET 短缓存。
  - 并发 GET 请求去重，同一个请求在进行中时复用 Promise。
  - 非 GET 请求会清空 GET 缓存，避免修改后继续读旧数据。
  - 支持 `{ noCache: true }` 用于手动刷新。
- 首屏加载优化：
  - 登录进入团队后不再一次性拉所有页面的数据。
  - 当前默认只加载任务列表和模型连接器。
  - 用量、Token 流水、配额、路由、资产、审计、团队成员/设置改为进入对应页面后再加载。
- 页面代码加载优化：
  - `frontend/src/App.jsx` 已用 `React.lazy` / `Suspense` 做页面级拆包。
  - 大页面组件如 Agent、工作流、模型报告、在线预测、AI 记录、代码工作区、人机协同、资产、审计、配额、团队等都改为按需加载。
  - 导航悬停 / 聚焦会预加载对应页面 chunk 和部分只读数据。
- 页面切换体感优化：
  - `frontend/src/App.jsx` 新增 `RoutePane` 与 `visitedPages`。
  - 已打开过的页面现在会保活，切换页面时只隐藏/显示，不再卸载重建。
  - 页面局部状态、已渲染内容、展开状态等更容易保留。
  - AI 记录和模型报告页已有当前任务数据时，切回页面不会立刻重新进入 loading，除非任务变更或用户手动刷新。
- 协作快照缓存：
  - 新增 `frontend/src/lib/collaborationCache.js`。
  - `WorkflowStagePanel`、`MultiAgentCollaborationPanel`、`HumanCollaborationPanel` 共享 60 秒协作快照缓存。
  - 切换这些页面时优先显示缓存快照，再后台刷新真实数据。

### 当前后端性能优化

- `backend/app/core/supabase_auth.py`
  - 增加 30 秒 Supabase 用户和团队成员身份缓存。
  - 避免每个业务接口都重复打 Supabase auth / membership 请求。
  - 注意：团队角色或成员状态变化最多可能有 30 秒生效延迟，这是为了速度做出的显式权衡。
- `backend/app/services/task_human_collaboration.py`
  - `get_snapshot()` 不再每次读取协作状态时 upsert 6 条阶段记录。
  - 现在读取已有阶段记录和人工请求后，在内存中构造阶段快照。
  - `sync_task_stages()` 仍保留给写入/运行路径使用。
  - 这避免了 Agent、工作流、人机协同页面反复打开时造成 Supabase 写入风暴。

### 本轮 GitHub 状态

- 本轮代码已经推送到 GitHub 远端：
  - remote：`origin https://github.com/insomniacs01/AI4ML.git`
  - branch：`main`
- 关键提交：
  - `7dc5885 Optimize workspace loading and add multi-agent view`
  - `b7119ce Keep workspace pages alive during navigation`
- 当前本地工作区还有一个未跟踪文件：
  - `data/GAID_MASTER_V2_COMPILATION_FINAL.csv`
  - 该文件不是本轮代码改动的一部分，尚未加入 Git。

### 本轮验证

- 已执行并通过：
  - `cd frontend && npm run build`
  - `python -m compileall backend\app`
  - `python -m unittest discover backend\tests`
- 最近一次后端测试结果：
  - 24 个测试通过。
- 本地前端服务仍可通过：
  - `http://127.0.0.1:5173`

### 下次继续时最应该记住的事

- 用户对“页面慢”和“每次切换又重新加载”的体验非常敏感。
- 不要再把页面改回条件渲染卸载模式；当前 `RoutePane` 保活策略是为了解决用户明确抱怨的切页体感。
- 不要重新引入大规模首屏 eager load；重数据应继续按页面加载或预热。
- 如果用户仍觉得慢，下一步优先做：
  1. 给 `api.js` 增加开发态接口耗时日志，定位具体慢接口。
  2. 对治理类列表接口增加后端短缓存或批量聚合，减少 Supabase 多次 round-trip。
  3. 对代码工作区、AI 记录、报告等页面加更细粒度的本地状态缓存。
  4. 视需要保存每个 `RoutePane` 的滚动位置，做到更接近桌面软件的切页体验。

## 2026-05-06 P0 final clarification and Agent Runtime closure

- 用户追问 P0 是否已经“完美闭环”，重点指出：
  - “智能体进度可视化已有真实 Agent 阶段快照，但本质是阶段 Agent 编排视图，不是 6 个独立后端 Agent 进程。”
- 本轮已把这一项从阶段投影升级为后端持久化 Agent Runtime 闭环：
  - 新增/扩展模型：`TaskAgentRecord`、`TaskAgentRuntimeRecord`、`TaskAgentEventRecord`、`TaskAgentCollaborationResponse`。
  - 新增服务：`backend/app/services/task_agent_collaboration.py`。
  - `task_agent_runs` 表持久化 6 个后端 Agent Runtime 记录。
  - `task_agent_events` 表记录 Agent Runtime 事件流。
  - `_record_workflow_stage()` 写阶段记录时同步 upsert 对应 Agent Runtime，并追加真实 Agent 事件。
  - `GET /api/tasks/{task_id}/agent-collaboration` 读取 `task_agent_runs` / `task_agent_events`，返回 `runtime_mode = persistent_agent_runtime`。
  - 旧任务首次打开 Agent 协同视图时会补齐缺失的 6 条 Runtime 记录，但不会反复刷新已有 Runtime 时间戳。
- 前端 `MultiAgentCollaborationPanel` 已改为展示持久化 Runtime 口径：
  - 运行模式：持久化 Agent Runtime / 阶段快照兼容模式。
  - Runtime 数量、`runtime_id` / `worker_id`、耗时、开始时间、日志摘录、事件类型和产物数量。
- Supabase schema 已新增并启用：
  - `task_agent_runs`
  - `task_agent_events`
  - 对应索引、updated_at trigger、RLS enable 和 member policy。
- 当前准确口径：
  - P0 “智能体工作进度可视化”已经闭环为“6 个后端持久化 Agent Runtime 单元 + 事件流”。
  - 它仍按 AI4ML 阶段顺序编排执行，不声称启动了 6 个并行 OS 进程。
  - 不要为了迎合“多 Agent”表述而伪造并行 worker、假日志或假产物。

### P0 需求口径调整

- 用户确认当前任务创建设计更合理：
  - 创建任务只要求 `name` / `description`。
  - `problem_type` 创建时可为空。
  - 上传 CSV 后由 AI 解析，或由人工语义修正表单确认后回写。
- 已同步修改需求文档口径：
  - `MON-智算社区-2-需求-0420.docx`
  - `tools/req_0420_paras.txt`
  - `docs/requirements-coverage-matrix.md`
- 后续不要再把“创建任务时 `problem_type` 必填”当作 P0 缺口；这已经从需求上改为可空、后置解析/确认。

### 当前 P0 判断

- P0 当前可判定为已闭环。
- 剩余曾被提到的点不建议作为 P0 硬闭环：
  - 邮件邀请系统：是产品化增强，当前邀请码/团队成员/RLS 已能支撑 P0 权限闭环。
  - 独立 `RoleBinding` 表：当前 `team_members.role` + 后端依赖鉴权 + Supabase RLS 更直接，除非后续要做细粒度可配置 RBAC。
  - 6 个并行后端进程：当前持久化 Runtime 更诚实；真正分布式 worker 应作为后续架构增强，而不是为了页面表述硬做。
  - 任务文件目录按 `team_id/task_id` 分层：数据库已按团队隔离，`task_id` 全局唯一；这属于后续存储口径统一或兼容迁移，不阻塞 P0。

### 本轮验证

- 已执行并通过：
  - `.\.venv\Scripts\python.exe -m compileall backend\app`
  - `.\.venv\Scripts\python.exe -m unittest discover backend\tests`
  - `npm run build`
- 最近一次后端测试结果：
  - 29 个测试通过。
- 前端开发服务已启动并返回 HTTP 200：
  - `http://127.0.0.1:5173`

### 当前注意事项

- 上线或本地 Supabase 验收前必须执行最新 `supabase/schema.sql`，否则 `task_agent_runs` / `task_agent_events` 不存在会导致 Agent 协同视图落库失败。
- 当前工作区有很多用户/既有未提交改动；后续继续修改时不要回滚无关文件。

## 2026-05-06 Agent-to-Agent communication closure

- 用户要求：当前流程不能只是按顺序执行，而要让不同 Agent 之间互相交流、交换信息、安排任务并共同完成目标。
- 本轮已把 Agent 协同从“Runtime + 事件流”继续升级为“Runtime + 事件流 + 持久化 Agent 间消息流”：
  - 新增模型：`TaskAgentMessageRecord`，并在 `TaskAgentCollaborationResponse.messages` 返回。
  - 新增 Supabase 表：`task_agent_messages`，字段包括 `from_agent_id`、`to_agent_id`、`stage`、`message_type`、`status`、`content`、`payload`、`artifact_refs`、`correlation_id`。
  - `task_agent_messages` 已增加索引、唯一 `correlation_id` 防重复、RLS enable 和团队成员 policy。
  - `TaskStore` 新增 `list_agent_messages()` 和 `append_agent_message()`。
  - `backend/app/services/task_agent_collaboration.py` 新增 `append_stage_agent_messages()`，在真实阶段状态变化时写入 Agent 间消息：
    - `coordination`：上游 Agent 运行中，通知下游预备接收输出。
    - `handoff`：上游 Agent 完成后向下游交接摘要和真实产物引用。
    - `acknowledgement`：下游 Agent 确认接收上游结果。
    - `blocker`：失败时通知下游等待修复或人工决策。
    - `human_review`：等待人工节点时通知后续交接被暂停。
    - `result`：最终报告 Agent 广播完成结果。
  - `_record_workflow_stage()` 现在每次写阶段记录和 Agent Runtime 事件时，也会同步写入真实 Agent 间消息。
  - `GET /api/tasks/{task_id}/agent-collaboration` 现在读取并返回 `task_agent_messages`。
  - 前端 `MultiAgentCollaborationPanel` 新增“Agent 讨论流”，展示发送 Agent、接收 Agent、消息类型、内容、时间和真实产物数量。
- 当前准确口径：
  - Agent 之间现在具备持久化的“协作消息 / 交接消息 / 接收确认 / 阻塞通知”能力。
  - 这些消息由真实阶段推进和运行结果触发，不是前端伪造聊天记录。
  - 当前仍不是独立 LLM worker 之间自由辩论或并行规划；它是围绕 AI4ML 阶段编排的真实 Agent-to-Agent 协调消息总线。
- 本轮验证：
  - `.\.venv\Scripts\python.exe -m compileall backend\app`
  - `.\.venv\Scripts\python.exe -m unittest backend.tests.test_p0_closure_services`
  - `.\.venv\Scripts\python.exe -m unittest discover backend\tests`
  - `npm run build`
  - 当前后端测试结果：31 个测试通过。
- 上线或本地 Supabase 验收前必须执行最新 `supabase/schema.sql`，否则 `task_agent_messages` 表不存在会导致 Agent 讨论流无法落库或读取。

## 2026-05-06 MLZero long-run observability and stale-state repair

- 用户反馈一个任务“跑了一天还在运行中”，页面进度不可用，无法判断是慢、卡住还是后台已经断了。
- 本轮排查的具体任务：
  - task id：`184e3ce7`
  - 数据集：`GAID_MASTER_V2_COMPILATION_FINAL.csv`
  - 真实运行目录：`C:\Users\LENOVO\AppData\Local\AI4ML\mlzero_runs\184e3ce7\20260505T080950Z`
  - 最后文件/日志更新时间：`2026-05-05 16:29:49`
  - 当前未发现与该 task id 或 output_dir 匹配的本地 MLZero/Python 子进程。
- 真实产物状态：
  - 已有 `run_summary.json`
  - 已有 `leaderboard.csv`
  - 已有生成代码产物
  - 缺少 `token_usage.json`
  - 最佳模型可从产物中读到：`WeightedEnsemble_L2`
  - 指标：`rmse = 0.0006200115833211335`
- 准确定性：
  - 这不是仍在正常运行的任务。
  - 它是一个“运行目录长时间无更新 + 后台进程不存在 + 部分产物存在但缺 token_usage”的陈旧/中断状态。
  - 按项目严格规则，缺少 `token_usage.json` 不能标为完整成功。

### 本轮实现

- 新增真实运行诊断服务：
  - `backend/app/services/task_run_progress.py`
  - 读取真实 MLZero 输出目录、日志、summary、leaderboard、token usage、generated code。
  - 同时扫描配置的 `settings.run_output_dir` 和 Windows `%LOCALAPPDATA%\AI4ML\mlzero_runs\<task_id>`，避免数据库没有记录 `last_run_attempt` 时找不到真实目录。
  - 对 `running` 任务只认任务进入 running 后产生或更新过的运行目录，避免重新运行时误拿上一次成功目录当当前进度。
- 新增 API：
  - `GET /api/tasks/{task_id}/run-progress`
  - 团队 scoped 路径也可用：`GET /api/teams/{team_id}/tasks/{task_id}/run-progress`
- 新增响应模型：
  - `TaskRunProgressArtifactSummary`
  - `TaskRunProgressResponse`
- stale 判定：
  - 如果任务仍是 `running`，但运行目录超过 1 小时无日志/产物更新，则标记为 `stale`。
  - 如果确认没有匹配的本地 Python/MLZero 进程，会把任务从 `running` 自动修正为 `failed`。
  - 自动修正会保留真实 output_dir、阶段记录、日志摘要、审计事件 `task.run.stale_repair`。
  - 如果无法确认进程状态且静默时间不足 6 小时，不会贸然自动改写任务状态。
- 前端新增真实进度入口：
  - `frontend/src/lib/api.js` 增加 `taskRunProgress(...)`。
  - 任务详情和工作流页显示“真实运行诊断”卡片。
  - 任务卡片新增“进度”按钮。
  - 选中 running / failed / 有运行尝试的任务时自动读取诊断；running 时每 10 秒轮询。
- 前端运行流程体验修正：
  - 点击“运行 MLZero”后，前端立即把该任务显示为 `running` 并开始读取真实进度，不再等长请求返回后才更新页面。
  - 新建任务的自动流程从“上传接口里串行跑完整 MLZero”改为：先上传/AI 解析，再由前端单独触发 MLZero run，这样训练阶段从开始就可观察。
  - 当任务状态是 `running` 时，任务卡片和详情页禁止重复运行、重复解析和删除。

### 重要口径

- 这次加的是“运行状态可观察性 + 陈旧状态修复”，不是“结果兜底”。
- 不能把部分产物直接当成功结果：
  - 有 `run_summary.json` / `leaderboard.csv` 但缺 `token_usage.json` 时，必须继续显示为失败或状态不完整。
  - 不允许为了让页面好看而伪造 token usage、伪造完成状态、伪造成功报告。
- 后续如果要支持“失败但可恢复的部分结果导入”，必须明确标注为 recoverable/partial，并仍然不能绕过 token usage 严格口径。

### 本轮验证

- 已执行并通过：
  - `.\.venv\Scripts\python.exe -m unittest backend.tests.test_p0_closure_services`
  - `.\.venv\Scripts\python.exe -m unittest discover backend\tests`
  - `.\.venv\Scripts\python.exe -m compileall backend\app`
  - `cd frontend && npm run build`
- 当前后端测试结果：33 个测试通过。
- 本地接口验证：
  - `http://127.0.0.1:8000/api/health` 返回 HTTP 200。
  - OpenAPI 中已包含 `/api/tasks/{task_id}/run-progress` 和 `/api/teams/{team_id}/tasks/{task_id}/run-progress`。
  - `http://127.0.0.1:5173` 前端服务返回 HTTP 200。

### 后续建议

- 优先在登录后的真实前端里打开任务 `184e3ce7` 的“进度/工作流进度”，触发 run-progress 接口，让后台把陈旧 `running` 状态修正为 `failed`。
- 下一步可做“停止/标记中断”手动入口，但要继续遵守真实进程检测和产物保留原则。
- 如果用户继续反馈训练耗时过长，下一步再做运行策略优化，例如默认更短时间预算、减少连续改进轮数、或者把 MCTS iteration / last log line 更细粒度地展示到 UI。

## 2026-05-06 frontend/backend stability and duplicate uvicorn guard

- 用户连续反馈：
  - 页面任务卡片顺序上下跳动，诊断按钮在“诊断中/刷新诊断”之间闪动。
  - 所有页面加载慢，连接器、配额等页面出现 `Failed to fetch` 或长时间卡住。
  - 连接器保存从原本约 5 秒变成十多分钟无结果。
  - 明确要求：不能用“前端几秒后停止等待/超时取消请求”来假装加速；所有业务请求不能被前端主动超时中断。
- 本轮排查出的关键故障：
  - 之前为性能加的前端请求超时/AbortController 是错误方向，会让连接器、配额等真实业务请求被前端直接取消。
  - 本地 8000 端口一度同时存在两套 `uvicorn --reload` 相关进程，导致后端健康检查和前端代理请求卡死。
  - 旧的 Vite/HMR 模块会让浏览器继续显示旧错误，例如 `DEFAULT_GET_TIMEOUT_MS is not defined` 或旧的 `Failed to fetch`。
- 已撤销/修正：
  - `frontend/src/lib/api.js` 不再有 `DEFAULT_GET_TIMEOUT_MS`、`timeoutMs`、`AbortController`、`已停止等待`、`超过 X 秒` 等前端中断逻辑。
  - 前端网络错误只做可读提示，不主动取消真实业务请求。
  - `frontend/vite.config.js` 的 `/api` 代理固定到 `http://127.0.0.1:8000`，避免 Windows 下 `localhost` 解析或代理链路不稳定。
  - 清理过 `frontend/dist` 旧包并重新构建，避免旧 hash bundle 残留。
- 新增后端单实例保护：
  - 新文件：`backend/app/core/backend_instance.py`
  - 新配置：`Settings.backend_instance_lock_path`
  - 锁文件默认放在系统本地运行目录，例如 Windows `%LOCALAPPDATA%\AI4ML\backend-<repo_hash>.lock`，不放在 repo 内，避免触发 `uvicorn --reload`。
  - `backend/app/main.py` 在创建 FastAPI app 前就尝试获取锁；第二套后端启动会直接退出。
  - 第二套启动时的明确提示：
    - `AI4ML backend startup blocked: AI4ML backend is already running for this workspace. Stop the existing uvicorn process on port 8000 before starting another one.`
  - 目的：同一 workspace 同一台机器只允许一套 AI4ML 后端实例运行，避免两套 `uvicorn --reload` 抢 8000 或把页面业务请求卡死。
- 新增测试：
  - `backend/tests/test_backend_instance_lock.py`
  - 覆盖：同一个锁文件第二次获取失败；释放后可再次获取。
- 当前验证结果：
  - `.\.venv\Scripts\python.exe -m unittest discover backend\tests`：36 个测试通过。
  - `npm run build`：通过。
  - 第一套后端启动后 `http://127.0.0.1:8000/api/health` 返回 HTTP 200。
  - `http://127.0.0.1:5173/api/health` 返回 HTTP 200。
  - 第二套后端启动命令退出码为 1，并提示已有后端实例正在运行；不会留下第二个后端进程。
- 重要后续口径：
  - 性能优化不能再通过前端超时/AbortController 中断业务请求实现。
  - 加速方向应是减少不必要请求、后端轻量查询、缓存只读 GET、限制文件递归扫描、稳定轮询状态，而不是取消真实写请求。
  - 如果用户看到 `Failed to fetch`，第一优先检查后端进程、5173 代理、浏览器是否加载旧 Vite 模块；不要重新引入前端超时取消。
