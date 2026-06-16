# AI4ML

更新时间：2026-06-14

AI4ML 是一个团队协作式智能建模工作台。项目当前已经收敛到 Codex-native 主线：用户在团队空间中创建建模任务，上传或指定数据后，由 `codex_use` 调用 Codex 生成可审核的执行方案；用户确认方案后，Codex 在任务工作区内继续完成建模、实验、报告、预测入口和代码产物。

本 README 面向项目验收和后续维护。当前事实以 `docs/current-memory.md`、`codex_use/current-memory.md` 和源码实现为准。

## 项目定位

AI4ML 解决的是“智能建模过程如何被团队协作、人工确认、状态追踪和结果复用”的问题，而不是简单包装一个模型训练脚本。

平台职责：

- 团队、成员、角色、权限和配额管理。
- 任务创建、数据上传、运行状态同步和结果展示。
- 人工确认、暂停、恢复、方案重生成和执行决策记录。
- Codex workspace 的创建、归属校验、产物读取和结果落库。
- 报告、指标、预测入口、源码和 token usage 的真实展示。
- 提示词和执行方案的社区复用。

Codex 职责：

- 理解用户任务目标和数据结构。
- 在计划阶段生成 `output/plan.md`，等待用户确认。
- 在用户确认后继续同一任务线程和 workspace，执行建模、实验、修复和报告撰写。
- 产出 `output/metrics.json`、`output/report.md`、`output/predict.py`、源码、模型、日志和 token usage。

## 验收主线

当前项目验收建议按以下闭环展示：

```text
创建任务
  -> 上传或指定数据
  -> Codex 生成执行方案 output/plan.md
  -> 用户查看、编辑、确认或要求重生成
  -> Codex 从同一 workspace 继续执行建模
  -> AI4ML 同步报告、指标、预测入口、源码和 token usage
  -> 用户发布提示词或执行方案到社区广场
```

这条主线对应的是当前代码中的真实实现，不再使用旧的 MLZero、AutoGluon、AIDE 或外部 AutoML agent 作为主执行链路。

## 系统架构

```text
AI4ML/
├─ frontend/        Vue 3 + Vite 前端工作台
├─ backend/         FastAPI 业务后端
├─ codex_use/       Codex-native 执行桥
├─ supabase/        Supabase schema
├─ docs/            当前记忆、需求覆盖和项目材料
├─ scripts/         验证与辅助脚本
├─ data/            示例数据
├─ storage/         本地任务缓存与历史产物
└─ external/        外部参考代码，不是当前主运行链路
```

### 前端

技术栈：

- Vue 3
- Vite 5
- Vue Router
- `@supabase/supabase-js`
- Vitest

关键入口：

- `frontend/src/App.vue`
- `frontend/src/main.js`
- `frontend/src/router.js`
- `frontend/src/api/request.js`
- `frontend/src/api/tasks.js`
- `frontend/src/api/taskHuman.js`
- `frontend/src/views/CreateTaskView.vue`
- `frontend/src/views/WorkspaceView.vue`
- `frontend/src/views/TaskDetailView.vue`
- `frontend/src/views/CommunityView.vue`

前端负责登录后的工作台体验，包括开始任务、工作台、我的任务、任务详情、人工确认、报告预测、代码产物和社区广场。

### 后端

技术栈：

- FastAPI
- Pydantic / pydantic-settings
- Supabase Auth / REST API
- 本地 SQLite cache

关键入口：

- `backend/app/main.py`
- `backend/app/application.py`
- `backend/app/api/router.py`
- `backend/app/services/service_registry.py`

后端负责团队作用域鉴权、任务状态机、数据上传、Codex 状态同步、人工确认、配额保护、社区资产和结果读取。

除 `/api/health` 外，正式业务 API 统一使用团队作用域：

```text
/api/teams/{team_id}/...
```

不要新增非团队作用域业务接口。

### codex_use

`codex_use/` 是 AI4ML 当前唯一有效的 Codex-native 执行桥。

关键入口：

- `codex_use/server.js`
- `codex_use/src/server/web-session-manager.js`
- `codex_use/src/server/ai4ml-artifacts.js`
- `codex_use/src/server/ai4ml-workspace-init.js`
- `codex_use/src/server/runners/app-server-runner.js`
- `codex_use/src/server/session-store.js`

它负责启动 Codex app-server、创建任务 workspace、维护任务级 `threadId`、处理计划确认、暂停、恢复、重生成、事件 replay 和 token usage 持久化。

## Codex Workspace 协议

AI4ML 任务 workspace 通常位于：

```text
codex_use/workspaces/ai4ml-{task_id}
```

核心输入：

```text
input/task_request.json
input/project_rules.md
```

核心输出：

```text
output/plan.md
output/progress.json
output/metrics.json
output/report.md
output/predict.py
output/code/
output/model/
output/logs/
output/token_usage.json
```

关键规则：

- 计划阶段必须先写 `output/plan.md`。
- 用户确认计划前，不能训练模型、生成最终报告、写指标或创建预测入口。
- 执行阶段由 Codex 原生能力和 subagents 完成。
- 最终用户可见产物以 `output/` 为准。
- token usage 只能来自真实 Codex usage 事件，不能估算。
- 进度百分比只能来自 `output/progress.json` 中真实的 `percent` / `progress_percent` 字段。
- 没有真实百分比时，前端应显示“进度未知”和具体原因，不能按步骤数量或任务状态推导。

## 已实现能力

### 团队与权限

- Supabase 登录和 session。
- 团队空间、成员和角色。
- FastAPI 按 Supabase bearer token 与 team scope 校验访问。
- 团队作用域 API、团队资产和团队任务隔离。

### 任务与数据

- 创建建模任务。
- 上传或指定数据。
- 后端校验上传文件并生成基础数据 profile。
- 创建后异步触发 Codex 运行。
- 任务列表、工作台和任务详情页展示任务状态。

### 方案生成与人工确认

- Codex 先生成 `output/plan.md`。
- 前端支持查看、编辑、批准方案。
- 用户可要求重生成方案。
- 批准后从同一任务 workspace 继续执行。
- 人工确认记录参与后续状态同步。

### 暂停、恢复与重生成

- 暂停：调用 Codex `turn/interrupt`，任务进入可恢复状态。
- 继续：携带 `resume_interrupted=true`，恢复任务自己的 `codex_thread_id`。
- 重生成：针对当前方案重新规划，不把旧状态静默覆盖成成功。
- 取消：作为业务终止语义，不等同于暂停。

### 报告、预测和代码产物

- 报告页展示真实 `output/report.md`。
- 指标读取真实 `output/metrics.json`。
- 预测 Demo 优先读取真实 `output/predict.py`。
- 代码页优先展示 `output/code/`、`output/predict.py` 等真实产物。
- 缺少预测脚本、模型、报告或源码时显示不可用，不伪造结果。

### 社区复用

社区广场当前只保留两类资产：

- `prompt`：提示词资产，保存任务主题和描述。
- `plan`：执行方案资产，保存已确认或编辑过的 Codex plan。

已废弃的模型广场、数据中心、工作流广场和报告类社区资产不属于当前产品口径。

## 质量与可靠性原则

当前项目硬约束：

- 不展示伪数据。
- 不制造假成功。
- 不用演示值冒充真实业务结果。
- 不做静默 fallback。
- 缺少连接器、权限、运行产物、Supabase schema 或 Codex 产物时，必须明确失败或显示未接入。
- 大模型用量必须来自真实 Codex usage 事件。
- Codex 任务阶段必须来自真实 Codex progress。
- 当前执行链路只支持 Codex-native，不重新引入 MLZero、AutoGluon、AIDE 或旧外部 AutoML agent。

这些约束是验收口径的一部分。项目宁可明确显示“不可用 / 未接入 / 进度未知”，也不能把缺失能力包装成已完成能力。

## 服务入口

本地默认入口：

```text
AI4ML 前端：http://127.0.0.1:5173
AI4ML 后端：http://127.0.0.1:8000
codex_use：http://127.0.0.1:3000
```

## 环境配置

### 前端

基于 `frontend/.env.example` 创建 `frontend/.env.local`：

```env
VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
VITE_API_ROOT=/api
```

### 后端

基于 `backend/.env.example` 创建 `backend/.env.local`。

需要配置 Supabase、AI provider、Codex 后端地址和本地存储目录。不要把真实密钥提交到仓库。

### Supabase

在 Supabase SQL Editor 中执行：

```text
supabase/schema.sql
```

实际 Supabase 数据库不会自动跟随仓库文件变化。遇到资产类型约束、团队权限、表字段缺失等问题时，优先检查线上 schema 是否已同步。

## 启动方式

### 后端

```powershell
cd D:\333\AI4ML
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend\requirements.txt
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
curl http://127.0.0.1:8000/api/health
```

### 前端

```powershell
cd D:\333\AI4ML\frontend
npm install
npm run dev
```

访问：

```text
http://127.0.0.1:5173
```

### codex_use

```powershell
cd D:\333\AI4ML\codex_use
npm install
npm start
```

访问：

```text
http://127.0.0.1:3000
```

`codex_use` 依赖本机 Codex app-server 能力和相关 AI 服务配置。实际运行前需要确认 Codex、AI provider、Supabase 和本地文件路径均可用。

## 验证方式

后端基础检查：

```powershell
cd D:\333\AI4ML
python -m compileall -q backend\app
python -m pytest backend\tests -q
```

前端检查：

```powershell
cd D:\333\AI4ML\frontend
npm test
npm run build
```

`codex_use` 语法检查：

```powershell
cd D:\333\AI4ML\codex_use
node --check server.js
node --check src/server/web-session-manager.js
node --check src/server/runners/app-server-runner.js
```

近期历史验证记录见 `docs/current-memory.md`。如果代码、依赖或运行环境发生变化，应重新运行对应检查，不能把历史验证当作当前结果。

## 验收汇报材料

仓库根目录已生成验收 PPT：

```text
AI4ML项目验收汇报.pptx
```

PPT 建议汇报重点：

- 项目背景：建模流程分散、协作成本高、结果需要可追踪。
- 项目定位：AI4ML 负责平台闭环，Codex 负责真实建模执行。
- 系统架构：Vue 前端、FastAPI 后端、Supabase 团队权限、`codex_use` 执行桥、Codex workspace。
- 核心流程：创建任务、上传数据、生成方案、人工确认、执行建模、报告预测、社区复用。
- 关键成果：任务闭环、HITL、暂停恢复、真实产物展示、社区复用。
- 问题反思：三端状态同步复杂、人工确认边界复杂、真实进度不能靠兜底值。
- 后续迭代：多任务并发、异常恢复、报告预测增强、社区质量评价。

PPT 中的人员分工页使用了占位姓名，正式提交前请替换为真实小组成员姓名。

## 人员分工建议

如果需要在验收 PPT 中填写人员分工，可以按角色归纳：

| 角色 | 主要工作 |
| --- | --- |
| 前端负责人 | 创建任务、工作台、任务详情、人工确认、社区广场、交互样式 |
| 后端负责人 | FastAPI 路由、任务状态机、团队鉴权、数据上传、运行快照 |
| Codex 执行桥负责人 | `codex_use`、workspace 协议、线程恢复、暂停继续、token usage |
| 测试与文档负责人 | 联调验证、README、验收 PPT、演示流程和问题记录 |

正式汇报时建议把“成员A/B/C/D”替换为真实姓名，并补充每个人实际承担的模块。

## 当前限制与后续迭代

当前限制：

- `codex_use` 仍以单活动任务模型为主，多任务并发需要重新设计。
- 历史任务缺少 `output/token_usage.json` 时无法恢复真实 token usage。
- 缺少 workspace、报告、指标、源码或预测入口时，系统只能显示不可用。
- 实际 Supabase schema 可能没有自动跟随仓库文件，需要部署时单独迁移。

后续建议：

- 设计任务队列和多 runner 管理，支持稳定并发。
- 增强失败恢复、重试策略和错误提示。
- 增强报告质量，包括实验对比、可解释性和复现步骤。
- 强化预测输入合约校验和模型服务化能力。
- 给社区方案增加版本、评分、审核和复用效果统计。
- 完善部署脚本、环境检查和端到端验收脚本。

## 关键文档

- `docs/current-memory.md`
- `codex_use/current-memory.md`
- `docs/requirements-coverage-matrix.md`
- `supabase/schema.sql`

## 维护原则

- 项目文档只保留当前仍然成立的事实。
- 与当前代码、`docs/current-memory.md` 或 `codex_use/current-memory.md` 冲突的旧口径应更新或删除。
- 不要恢复 React 主入口、MLZero/AutoGluon/AIDE 主执行链路、模型/数据/工作流广场、业务/技术双报告等已废弃内容。
- 修改代码前应先明确需求、列出计划并确认范围。
