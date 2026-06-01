# AI4ML 当前能力覆盖矩阵

更新时间：2026-05-26

本文档记录当前 AI4ML 主产品仍然成立的能力覆盖情况。历史需求文档中关于 React 主入口、MLZero 主执行链路、模型广场、数据中心、工作流广场、业务/技术双报告等内容已经过时；当前事实以 `docs/current-memory.md`、`codex_use/current-memory.md` 和代码入口为准。

## 状态口径

| 状态 | 判定标准 |
| --- | --- |
| 已闭环 | 有真实前端入口、后端接口或 workspace 协议支撑，能读写真实数据或真实产物，不依赖伪造结果。 |
| 部分闭环 | 主链路已实现，但仍依赖环境、权限、线上 schema 或特定产物，边界能力还不完整。 |
| 已移除 | 曾是需求或设计方向，但已不属于当前产品口径，相关文档或入口不应继续保留。 |
| 未接入 | 当前没有稳定入口、接口或产物协议支撑。 |

## 当前主线总览

| 模块 | 当前状态 | 依据 | 说明 |
| --- | --- | --- | --- |
| Vue 前端工作台 | 已闭环 | `frontend/src/App.vue`、`frontend/src/router.js`、`frontend/src/api/client.js` | 当前主入口是 Vue 3 + Vite。旧 React 入口不再作为开发依据。 |
| FastAPI 团队作用域业务 API | 已闭环 | `backend/app/main.py`、`backend/app/application.py`、`backend/app/api/router.py` | 除 `/api/health` 外，业务 API 统一挂在 `/api/teams/{team_id}/...`。 |
| Supabase 身份与团队 | 已闭环 | `supabase/schema.sql`、后端 team scope 路由 | Supabase session 和团队成员关系是身份与团队真相源。 |
| Codex-native 执行桥 | 已闭环 | `backend/app/services/codex_backend.py`、`codex_use/current-memory.md` | 后端通过 `codex_use` 创建和读取 Codex workspace。 |
| MLZero / AutoGluon 主执行链路 | 已移除 | 当前记忆与主链路 | 不再作为当前产品主线；不要在新文档中恢复该口径。 |

## P0 能力

| 编号 | 能力 | 当前状态 | 当前依据 | 说明 |
| --- | --- | --- | --- | --- |
| P0-001 | 登录、团队和权限上下文 | 已闭环 | `frontend/src/api/client.js`、`backend/app/api/router.py`、`supabase/schema.sql` | 前端依赖 Supabase session，后端业务接口按 team scope 校验。 |
| P0-002 | 任务创建、列表和详情 | 已闭环 | `frontend/src/views/CreateTaskView.vue`、`frontend/src/views/TasksView.vue`、`backend/app/api/routes/task_lifecycle.py` | 任务以团队空间为上下文，支持创建、查询和展示详情。 |
| P0-003 | 数据输入和任务请求落地 | 已闭环 | `backend/app/api/routes/task_lifecycle.py`、Codex workspace `input/task_request.json` | 任务请求写入 Codex workspace，作为后续计划和执行依据。 |
| P0-004 | Codex 计划生成 | 已闭环 | `codex_use/templates/ai4ml-new-task-prompt.md`、workspace `output/plan.md` | Codex 必须先生成 plan，并把进度置为等待用户确认。 |
| P0-005 | 用户确认后执行 | 已闭环 | `codex_use/templates/ai4ml-approve-plan-execute-prompt.md`、`backend/app/services/codex_backend.py` | 用户确认或编辑 plan 后，Codex 才能执行建模和写最终产物。 |
| P0-006 | 运行进度展示 | 已闭环 | `output/progress.json`、`backend/app/services/task_runtime_steps.py`、`frontend/src/components/CodexRealtimePanel.vue` | Codex 任务阶段以真实 progress 为主，不能用旧 workflow stage 覆盖真实状态。 |
| P0-007 | 最终报告展示 | 已闭环 | `output/report.md`、`frontend/src/views/TaskDetailView.vue` | 报告页只展示最终报告，不再拆业务报告和技术报告。 |
| P0-008 | 指标和结果摘要 | 部分闭环 | `output/metrics.json`、`backend/app/services/codex_backend.py` | 有真实指标产物时展示；缺失时必须明确不可用。 |
| P0-009 | 预测 Demo | 部分闭环 | `output/predict.py`、`POST /prediction-demo` | 优先读取真实 `predict.py`；没有预测合约或模型时返回不支持。 |
| P0-010 | 源码和结果文件查看 | 部分闭环 | `output/code/`、`output/predict.py`、`frontend/src/views/TaskDetailView.vue` | 能展示真实运行产物；仍是结果文件查看器，不是完整 IDE。 |
| P0-011 | token usage 展示 | 部分闭环 | `output/token_usage.json`、`codex_use/current-memory.md` | 只展示真实 usage 事件写入的用量；历史任务缺失时显示 `-`。 |
| P0-012 | 失败和缺产物可观察性 | 已闭环 | `docs/current-memory.md`、后端严格失败路径测试 | 不允许 fake success、hidden fallback 或演示值冒充结果。 |

## P1 能力

| 编号 | 能力 | 当前状态 | 当前依据 | 说明 |
| --- | --- | --- | --- | --- |
| P1-001 | 提示词广场 | 已闭环 | `frontend/src/views/CommunityView.vue`、`backend/app/models/governance.py`、`backend/app/services/governance_store.py` | 保存任务主题和描述，支持搜索、查看、复用和 fork。 |
| P1-002 | 执行方案广场 | 已闭环 | `frontend/src/views/TaskDetailView.vue`、`frontend/src/views/CreateTaskView.vue`、`platform_assets.asset_type = plan` | 保存已确认或编辑过的 Codex plan，后续创建任务时可复用。 |
| P1-003 | 社区关键词搜索 | 已闭环 | `frontend/src/views/CommunityView.vue` | 搜索名称、描述、提示词内容、方案文本、任务分类、目标列、指标和标签。 |
| P1-004 | 人工确认与恢复执行 | 部分闭环 | plan 确认、resume prompt、Codex workspace 状态 | 当前重点是 plan 确认和中断恢复；更复杂的多节点通知仍可增强。 |
| P1-005 | 代码工作区编辑和重跑 | 部分闭环 | `backend/app/services/task_code_workspace.py` | 可编辑可写文件、保存版本和重跑 Python 工件；还不是完整 IDE。 |
| P1-006 | 管理端配置和配额 | 部分闭环 | `frontend/src/views/AdminView.vue`、后端 team routes | 团队、连接器、默认 AI、配额和用量已有入口；实际可用性依赖 Supabase schema 和运行环境。 |

## P2 能力

| 编号 | 能力 | 当前状态 | 当前依据 | 说明 |
| --- | --- | --- | --- | --- |
| P2-001 | 多任务并行 Codex runner | 未接入 | `codex_use/current-memory.md` | 当前 `codex_use` 记忆明确要求重新设计多 session / multi-runner 后再做并行。 |
| P2-002 | 完整模型市场 | 已移除 | 当前产品口径 | 当前社区资产已收敛为 `prompt` / `plan`，不恢复模型广场。 |
| P2-003 | 完整数据中心 | 已移除 | 当前产品口径 | 当前不是数据集托管平台。 |
| P2-004 | 工作流广场 | 已移除 | 当前产品口径 | 当前用“执行方案”替代固定工作流资产。 |
| P2-005 | 报告导出下载 | 已移除 | `docs/current-memory.md` | 旧报告下载入口已移除，因为没有实际价值。 |
| P2-006 | 华为云部署闭环 | 未接入 | `docs/current-memory.md` | 旧部署信息未重新验证，部署前必须重新检查线上环境和 schema。 |

## 当前数据库资产约束

当前社区资产类型只应保留：

```text
prompt
plan
```

如果线上 Supabase 仍允许或只允许旧类型：

```text
dataset
model
workflow
report
```

说明线上数据库 schema 没有同步到当前产品口径。需要更新 `platform_assets.asset_type` 约束，并清理不再属于当前口径的旧资产。

## 关键验收规则

- 创建任务后必须能找到对应 team scope。
- Codex 计划必须来自真实 `output/plan.md`。
- 用户确认前不能写最终 `metrics.json`、`report.md` 或 `predict.py`。
- 运行进度必须来自真实 `output/progress.json`。
- 报告必须来自真实 `output/report.md`。
- 指标必须来自真实 `output/metrics.json`。
- 预测 Demo 必须来自真实 `output/predict.py` 或明确返回不支持。
- token usage 必须来自真实 `output/token_usage.json`。
- 缺产物、缺权限、缺连接器或缺 schema 时必须明确失败。

## 后续建议

1. 继续保持 `docs/current-memory.md` 是当前事实源，其他文档如有冲突必须更新或删除。
2. 对线上 Supabase schema 做一次显式核对，尤其是 `platform_assets.asset_type`。
3. 为 `codex_use` 多任务并行单独设计 session、runner 和 workspace 管理，不要直接扩展当前单活动任务模型。
4. 报告、源码、预测和 token usage 页面继续坚持“真实产物优先，缺失就明确不可用”。
