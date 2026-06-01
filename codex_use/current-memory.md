# Codex Web Console Current Memory

更新时间：2026-05-28

这份文档记录 `D:\333\AI4ML\codex_use` 子项目当前仍然成立的记忆。`codex_use/` 是 AI4ML 主项目使用的 Codex-native 执行桥，不是上一级主项目的 `frontend/` 或 `backend/`。

## 当前角色

`codex_use` 当前不再只是独立实验控制台，而是 AI4ML 主项目的 Codex-native 执行后端。AI4ML 后端通过它启动 Codex app-server、创建任务 workspace、发送任务提示词、确认计划、恢复中断任务，并读取 Codex 产物展示报告、预测、进度和 token usage。

AI4ML 主项目当前已经清理旧 MLZero/AutoGluon/AIDE 执行链路，`codex_use` 是当前唯一有效的建模执行桥。不要再按旧 MLZero runtime、AutoGluon assistant 或外部 AutoML agent 的方式扩展这里的任务流程。

当前服务：

- `codex_use`：`http://127.0.0.1:3000`
- AI4ML 后端：`http://127.0.0.1:8000`
- AI4ML 前端：`http://127.0.0.1:5173`

## Workspace 协议

AI4ML 任务 workspace 目录通常是：

- `D:\333\AI4ML\codex_use\workspaces\ai4ml-{task_id}`

核心输入：

- `input/task_request.json`
- `input/project_rules.md`

核心输出：

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

- 不要在 task workspace、`work/`、`output/` 或 subagent 目录内创建新的 Python 虚拟环境，例如 `.venv`、`venv` 或 `env`。
- 优先使用项目级 `D:\333\AI4ML\.venv` 或系统已有 Python 解释器。
- 如确实需要额外依赖，记录到 workspace requirements 文件或报告复现步骤中，不在每个 subagent 目录重复安装完整依赖环境。
- 可重建的依赖目录、pip cache、临时安装目录和虚拟环境不能作为最终产物写入 `output/` 或 `state/artifact_index.json`。

重要约束：

- 计划阶段必须先写 `output/plan.md`，等待用户确认。
- 用户可以编辑 plan 后确认执行，也可以要求重新生成。
- 确认前不应训练模型、生成最终报告或写预测产物。
- 执行阶段由 Codex 原生能力和 subagents 完成，不在 Web Console 里重写一套自研多进程调度器。
- 最终 `metrics.json`、`report.md`、`predict.py`、`artifact_index.json` 等用户可见产物应由父 Codex 统一确认和写入。

## 当前实现重点

关键文件：

- `server.js`：Express 静态服务、`/terminal` WebSocket、AI4ML REST 接口。
- `src/server/web-session-manager.js`：持久 Web session、事件日志、任务启动、计划确认、重新生成、恢复执行、历史回放压缩和 token usage 持久化。
- `src/server/runners/app-server-runner.js`：Codex app-server JSON-RPC runner，负责 `thread/start`、`thread/resume`、`turn/start`、`turn/interrupt` 和事件转发。
- `src/server/ai4ml-artifacts.js`：workspace 产物读取、最新 workspace 识别、中断标记、`output/token_usage.json` 写入。
- `src/server/ai4ml-workspace-init.js`：构建新任务、确认计划、重新生成计划和恢复中断任务的提示词。
- `templates/ai4ml-new-task-prompt.md`
- `templates/ai4ml-approve-plan-execute-prompt.md`
- `templates/ai4ml-regenerate-complete-plan-prompt.md`
- `templates/ai4ml-resume-interrupted-task-prompt.md`
- `public/index.html`、`public/js/main.js`、`public/js/state.js`、`public/js/render/timeline.js`：独立 Web Console UI。

## 外部参考目录

- `codex_use/external/companion` 是保留的上游参考/协议对照代码，不是当前 AI4ML 主项目的前端、后端或实际运行入口。
- 当前有效入口仍是 `codex_use/server.js` 与 `src/server/` 下的 AI4ML REST 和 Codex app-server runner。
- 不要把 `codex_use/external/companion` 的产品形态、路由或会话模型直接当成当前实现事实；只有在明确做协议研究或迁移时才参考它。

## 刷新和历史恢复

当前架构已经从“WebSocket 连接生命周期 = Codex runner 生命周期”改为“持久 Web session 生命周期 = Codex runner 生命周期”。

当前行为：

- 浏览器刷新或 WebSocket 断开不会主动停止 Codex app-server。
- 新连接会 attach 到同一个 session。
- 后端会 replay 已持久化事件，再继续广播实时事件。
- 如果服务或 Codex 进程异常结束，未闭合 turn 会被标记为 interrupted。
- `thread/resume` 用于恢复已有 Codex thread。
- “继续执行”语义是恢复当前任务自己的 Codex thread + 当前中断 workspace，不是创建新 workspace。
- “创建新任务”语义是新 workspace + 新 Codex thread。
- 每个 AI4ML 任务现在有独立 Codex 原生对话：新任务强制新建 thread，AI4ML 后端保存 `TaskRecord.codex_thread_id`，后续确认计划、重新生成、暂停和继续都会传回这个 threadId。
- `src/server/session-store.js` 在 `~/.codex-web-console/session-state.json` 中保存 `taskThreads` 映射，结构是 `taskId -> { threadId, webSessionId, updatedAt }`。
- `src/server/runners/app-server-runner.js` 支持 `resumeThread(threadId)`；`src/server/web-session-manager.js` 会先按任务级 threadId 切换 runner，再发送恢复/确认/重生成 prompt。
- 实时运行面板应优先展示持久 session/event replay 中的真实对话和 Working 状态；没有真实记录时显示等待、未连接或无历史，不要补造对话。

暂停和取消的当前区别：

- 暂停：AI4ML 后端调用 `/api/ai4ml/tasks/interrupt`，Codex 执行 `turn/interrupt`，workspace `progress.json` 标记为 `interrupted`，主任务保持可恢复状态。
- 继续：AI4ML 后端调用 `/api/ai4ml/tasks/resume`，`codex_use` 按任务自己的 threadId 做 `thread/resume`，再使用 `templates/ai4ml-resume-interrupted-task-prompt.md` 从现有 workspace 继续。
- 取消：是主产品业务终止语义，不作为常规恢复入口。

已解决的旧问题：

- 刷新页面后对话完全消失。
- 刷新中运行状态误显示为 Ready。
- 用户消息和 Working 块顺序错位。
- 任务中断后 Working 计时无限增长。

这些不要再当作当前未解决问题记录。

## Subagents 口径

当前方向是使用 Codex 官方原生 Subagents 能力，而不是自己在 `codex_use` 中手写多个 Codex 进程调度器。

当前实现：

- 后端识别 Codex app-server 的 `collabAgentToolCall` 事件。
- 子 agent thread 的普通消息不会直接混入父会话主消息。
- 前端 Working/Worked 折叠块能展示 spawn/wait subagent 行为和详情。
- 迟到的子线程事件不会在父 turn 完成后重新打开误导性的 Working 块。

## Token Usage

真实 token usage 来源是 Codex app-server 的 `thread/tokenUsage/updated` JSON-RPC notification。

当前链路：

1. `src/server/runners/app-server-runner.js` 监听 `thread/tokenUsage/updated`。
2. 事件被归一化为 `token_usage_updated`。
3. `src/server/web-session-manager.js` 收到后调用 token usage 持久化。
4. `src/server/ai4ml-artifacts.js` 写入 AI4ML workspace 的 `output/token_usage.json`。
5. AI4ML 后端读取后同步到 `TaskRecord.last_run.token_usage` / `last_run_attempt.token_usage`。

重要边界：

- 没有真实 usage 事件时不能估算。
- 旧任务如果没有 `output/token_usage.json`，AI4ML 前端显示 `-` 是正确行为。
- 如果新任务仍没有 token usage，应抓 Codex app-server 原始 JSON-RPC 流，确认上游是否发送 `thread/tokenUsage/updated`。

## 与 AI4ML 主项目的当前集成

AI4ML 主项目当前已做：

- `backend/app/services/codex_backend.py` 读取 `output/plan.md`、`progress.json`、`metrics.json`、`report.md`、`predict.py`、`output/code/` 和 `token_usage.json`。
- Codex workspace 解析支持按 `ai4ml-{task_id}` 确定性目录找回已完成任务产物。
- `backend/app/api/routes/task_lifecycle.py` 的 runtime snapshot 对 Codex 任务以 Codex progress 为主。
- `backend/app/api/routes/task_runtime.py` 负责把 `codex_use` 返回的 `threadId` 保存到 `TaskRecord.codex_thread_id`，并在暂停/继续/确认/重生成时传回。
- `frontend/src/views/TaskDetailView.vue` 的发布页可查看/编辑当前任务 plan，并发布为方案广场资产。
- `frontend/src/views/CommunityView.vue` 只保留提示词广场和方案广场，支持关键词搜索和复用。
- 后端任务执行器已统一为 `codex`，历史非 codex executor 会在模型层规范化。
- AI 服务连接配置已改为通用 `ai_provider_*`，不再使用 `mlzero_*` 或 `AI4ML_MLZERO_*`。
- 额度保护由 AI4ML 后端 quota guard 负责；额度耗尽后应暂停或阻断任务继续调用，不应让 `codex_use` 无限继续跑。

2026-05-28 已删除的旧内容：

- AI4ML 主项目里的 MLZero runtime、旧 executors、旧 `task_run_*` 服务和旧增量重跑服务。
- `external/autogluon-assistant`、`external/automl-agent`、`external/aideml`。
- `storage/mlzero_runs`、`storage/mlzero_runtime`。
- `autogluon.tabular` 后端依赖和旧 MLZero provider 配置文件。

## 当前产品约束

- 不要把 `codex_use` 与 AI4ML 主项目目录混淆。
- 不要把 `codex_use` 的独立 Web Console UI 当作主产品前端；主产品前端是 `D:\333\AI4ML\frontend` 的 Vue/Vite 应用。
- 不要假造任务成功、报告、指标、预测或 token usage。
- 状态必须来自 Codex 实际产物、真实事件或明确的失败/中断状态。
- 不要重新引入 MLZero、AutoGluon、AIDE 或旧外部 AutoML agent。
- 默认用户可见说明使用中文，专业名词、字段名、文件名和代码标识可以保留英文。
- 如果后续实现多个任务并行，需要重新设计多 session / multi-runner / multi-workspace 管理，不要硬叠在当前单活动任务模型上。

## 近期验证

2026-05-28 主项目清理旧 MLZero/AutoGluon/AIDE 后已验证：

- `python -m compileall -q backend/app`：通过。
- `python -m pytest backend/tests/test_backend_instance_lock.py backend/tests/test_quota_runtime_guard.py backend/tests/test_codex_workspace_resolution.py backend/tests/test_admin_user_limits.py backend/tests/test_governance_asset_contract.py backend/tests/test_task_cache.py`：22 passed。
- AI4ML 前端 `npm test -- --run src/api/client.test.js`：12 passed。
- AI4ML 前端 `npm run build`：通过。
- `codex_use` 侧 `node --check server.js; node --check src/server/web-session-manager.js`：通过。
- 任务级独立 thread 改动后已额外验证：`node --check src/server/runners/app-server-runner.js`、`node --check src/server/session-store.js` 通过；AI4ML 前端 `npm test -- --run src/api/client.test.js` 10 passed；后端 `python -m pytest backend/tests/test_codex_workspace_resolution.py backend/tests/test_quota_runtime_guard.py backend/tests/test_task_cache.py` 15 passed。

历史 `codex_use` 侧曾验证过：

- `node --check` 覆盖 `server.js`、`src/server/web-session-manager.js`、`src/server/ai4ml-artifacts.js`、`src/server/ai4ml-workspace-init.js`、`src/server/runners/app-server-runner.js` 和主要 `public/js` 文件。
- WebSocket 重连、历史 replay、中断标记、继续执行、subagent 展示曾通过端到端验证。

这些历史验证说明功能曾跑通；如果当前代码或环境变化，仍应重新跑对应检查。

## 已废弃记忆

以下旧说法已经不再作为当前事实：

- “页面刷新后对话消失仍未解决。”
- “需要探查 Codex app-server 是否支持 thread resume。”
- “当前 Web Console 每次连接都会新建 runner/thread。”
- “AI4ML 任务没有自己的独立 Codex thread，只能靠最近全局 thread 恢复。”
- “`codex_use` 只是单独实验控制台，没有被主项目接入。”
- “前端只需要恢复 localStorage 历史。”
- “后续应自己写 skill 启动多个 Codex app-server 来模拟 subagents。”
