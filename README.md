# AI4ML

更新时间：2026-05-26

AI4ML 是一个团队协作式智能建模工作台。当前主线不是固定的 MLZero / AutoGluon 流水线，而是通过 `codex_use` 接入 Codex-native workspace：用户创建任务并提供数据与目标后，Codex 先生成可确认的执行方案，用户确认后再执行建模、生成报告、结果文件和预测入口。

当前事实以 `docs/current-memory.md` 和 `codex_use/current-memory.md` 为准。旧文档中关于 React 主入口、模型广场、数据中心、工作流广场、业务/技术双报告、MLZero 作为主执行器等说法已经过时。

## 当前定位

AI4ML 负责：

- 团队、成员、角色和权限管理。
- 任务创建、数据上传、计划确认、状态同步和结果展示。
- Codex workspace 的创建、恢复、产物读取和结果落库。
- 报告、源码、预测入口、运行进度和 token usage 的真实展示。
- 提示词和执行方案的社区复用。

Codex 负责：

- 理解任务目标和数据结构。
- 生成 `output/plan.md`，等待用户确认。
- 在用户确认后执行建模、实验、修复和报告撰写。
- 产出 `metrics.json`、`report.md`、`predict.py`、源码、日志和模型文件。

系统硬约束：

- 不展示伪数据。
- 不制造假成功。
- 不用演示值冒充真实结果。
- 不做静默 fallback。
- 缺少连接器、权限、运行产物或 token usage 时必须明确失败或显示未接入。

## 服务入口

- AI4ML 前端：`http://127.0.0.1:5173`
- AI4ML 后端：`http://127.0.0.1:8000`
- `codex_use` Web Console / Codex app-server 代理：`http://127.0.0.1:3000`

除 `/api/health` 外，正式业务 API 统一使用团队作用域：

```text
/api/teams/{team_id}/...
```

不要新增非团队作用域业务接口。

## 技术栈

### 前端

- Vue 3
- Vite 5
- Vue Router
- `@supabase/supabase-js`

当前入口：

- `frontend/src/App.vue`
- `frontend/src/main.js`
- `frontend/src/router.js`
- `frontend/src/api/client.js`

旧的 `frontend/src/App.jsx`、`frontend/src/lib/api.js` 和一批 React 组件已经不是当前主入口。

### 后端

- FastAPI
- Pydantic / pydantic-settings
- Supabase Auth / REST API
- 本地 SQLite cache

当前入口：

- `backend/app/main.py`
- `backend/app/application.py`
- `backend/app/api/router.py`

### 执行桥

- `codex_use/` 是 AI4ML 主项目使用的 Codex-native 执行桥。
- `backend/app/services/codex_backend.py` 负责创建和读取 Codex workspace。
- `codex_use` 通过 Codex app-server 维护 Web session、事件流、计划确认、恢复执行和 token usage 持久化。

## 目录结构

```text
AI4ML/
├─ backend/                    # FastAPI 后端
├─ frontend/                   # Vue + Vite 前端
├─ codex_use/                  # Codex-native 执行桥
├─ supabase/                   # Supabase schema
├─ docs/                       # 当前记忆和项目文档
├─ scripts/                    # 验证与辅助脚本
├─ data/                       # 示例数据
├─ storage/                    # 本地任务与运行产物
├─ external/                   # 上游依赖仓库与本地补丁
└─ 周报/                       # 周报材料
```

## Codex Workspace 协议

AI4ML 任务 workspace 通常位于：

```text
codex_use/workspaces/ai4ml-{task_id}
```

输入文件：

```text
input/task_request.json
input/project_rules.md
```

输出文件：

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

## 当前产品能力

### 团队与权限

- Supabase 登录和 session。
- 团队空间、成员和角色。
- FastAPI 按 Supabase bearer token 和 team scope 校验访问。
- 正式业务接口统一走 `/api/teams/{team_id}/...`。

### 任务

- 创建任务。
- 上传或指定数据。
- 生成 Codex plan。
- 用户查看、编辑和确认 plan。
- 确认后启动或恢复 Codex 执行。
- 读取真实进度、报告、指标、源码、预测入口和 token usage。

### 人工确认

- plan 确认是当前主流程的核心节点。
- 后续人工问题、恢复执行和中断处理通过 Codex workspace 与后端状态同步。
- 不把“缺少信息”包装成成功结果。

### 报告与预测

- 报告页只展示最终报告，不再拆业务报告和技术报告。
- 预测 Demo 优先读取真实 `output/predict.py`。
- 缺少模型或预测合约时返回不支持，不伪造预测结果。

### 源码与结果文件

- 源码页优先展示真实运行产物。
- 重点文件包括 `output/code/`、`output/predict.py` 和相关日志。
- 空产物不能假装有源码。

### 社区复用

社区广场当前只保留两类资产：

- `prompt`：提示词资产，保存任务主题和描述。
- `plan`：执行方案资产，保存已确认或编辑过的 Codex plan。

模型广场、数据中心、工作流广场和报告类社区资产不再属于当前产品口径。

如果发布提示词或方案时报 Supabase 约束错误，通常说明线上数据库仍保留旧 `platform_assets.asset_type` 约束，需要执行当前 `supabase/schema.sql` 或对应迁移，让资产类型收敛到 `prompt` / `plan`。

## 主要后端接口

健康检查：

```text
GET /api/health
```

团队作用域业务接口示例：

```text
GET    /api/teams/{team_id}/tasks
POST   /api/teams/{team_id}/tasks
GET    /api/teams/{team_id}/tasks/{task_id}
POST   /api/teams/{team_id}/tasks/{task_id}/dataset
POST   /api/teams/{team_id}/tasks/{task_id}/run
POST   /api/teams/{team_id}/tasks/{task_id}/resume
GET    /api/teams/{team_id}/tasks/{task_id}/runtime-snapshot
GET    /api/teams/{team_id}/tasks/{task_id}/run-progress
GET    /api/teams/{team_id}/tasks/{task_id}/report
POST   /api/teams/{team_id}/tasks/{task_id}/prediction-demo
GET    /api/teams/{team_id}/tasks/{task_id}/code-workspace
GET    /api/teams/{team_id}/assets
POST   /api/teams/{team_id}/assets
POST   /api/teams/{team_id}/assets/{asset_id}/publish
POST   /api/teams/{team_id}/assets/{asset_id}/fork
```

实际接口以 `backend/app/api/router.py` 和 `backend/app/api/routes/` 为准。

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

需要配置 Supabase、连接器密钥、Codex / OpenAI-compatible provider 和本地运行相关环境。不要把真实密钥提交到仓库。

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

`codex_use` 的具体启动方式以 `codex_use/current-memory.md` 和子项目脚本为准。它是当前 AI4ML 后端读取 Codex 产物的关键执行桥。

## 验证方式

后端基础检查：

```powershell
cd D:\333\AI4ML
.\.venv\Scripts\python.exe -m compileall backend\app
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

前端检查：

```powershell
cd D:\333\AI4ML\frontend
npm test
npm run build
```

近期记忆中的验证状态见 `docs/current-memory.md`。如果代码或环境变化，应重新运行对应检查，不能把历史验证当作当前结果。

## 当前限制

- 当前社区资产是提示词和执行方案复用，不是完整模型市场或数据集托管平台。
- `codex_use` 当前需要重新设计后才能稳定支持多任务并行，不要直接把单活动任务模型硬扩成多 runner。
- 历史任务缺少 `output/token_usage.json` 时无法恢复真实 token usage。
- 缺少 workspace、报告、指标、源码或预测入口时，系统应明确显示不可用。
- 华为云部署信息没有在最近记忆中重新验证，部署前必须重新检查服务器、网络、密钥和线上 schema。

## 关键文档

- `docs/current-memory.md`
- `codex_use/current-memory.md`
- `supabase/schema.sql`

## 维护原则

项目文档只保留当前仍然成立的事实。与当前代码、`docs/current-memory.md` 或 `codex_use/current-memory.md` 冲突的历史口径应直接更新或删除，不再保留多个过时版本。
