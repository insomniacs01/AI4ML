# AI4ML

AI4ML 是一个面向团队协作的 AI4ML 社区平台原型。当前仓库已经不再是早期的 Week 2 脚手架状态，而是一个包含真实前后端、Supabase 团队体系、AI 连接器、任务执行、人工复核、代码工作区、资产登记和审计能力的可运行版本。

## 当前项目状态

- 前端：React + Vite 工作台，已接入真实登录、团队、任务、连接器、默认 AI 路由、配额、资产、审计、AI 记录、代码工作区。
- 后端：FastAPI 服务，负责团队鉴权后的任务编排、AI 解析、MLZero 执行、人工复核、代码工件读取与 Token 记账。
- 身份与团队：Supabase Auth + Postgres，作为用户、团队、成员、路由、配额、资产和审计的真实数据源。
- 执行引擎：以 `MLZero / AutoGluon Assistant` 为基础，已做本地二次改造，支持 OpenAI-compatible 云模型提供方。
- 当前优先完成的是 P0 能力闭环；资产发布/Fork 已有基础能力，更高层的工作流广场、模型广场运营仍处于后续阶段。

## 已实现的核心能力

- Supabase 登录、注册、建队、邀请码入队
- 团队成员角色与状态管理
  - `team_owner`
  - `admin`
  - `business_user`
  - `developer_user`
  - `member`
  - 成员状态支持 `active / invited / frozen / removed`
- AI 连接器管理
  - 创建连接器
  - 测试连接器
  - 激活团队当前运行连接器
- 团队默认 AI 路由
  - 按阶段配置显式连接器与模型；未配置或配置不完整时直接失败
- 任务链路
  - 创建任务
  - 上传 CSV
  - AI 自动解析目标列、任务类型、指标等结构化信息
  - 触发 MLZero 运行
  - 查看真实模型报告、在线预测 Demo、代码工件下载与 Python 工件重跑
- 人工复核
  - 手动发起复核请求
  - 运行前 `before_run` 自动复核策略
  - 任务 `paused_for_review` / 恢复继续执行
- 代码工作区
  - 查看最新运行目录中的真实代码与日志工件
  - 开发成员可编辑可写文件
  - 保存版本记录、下载工件、重跑可执行 Python 工件
- 配额与 Token
  - 团队成员配额管理
  - 预警阈值拦截高开销阶段
  - Token ledger 记账
- 资产与审计
  - 资产登记与基础审核状态流转
  - 资产发布到团队广场视图与 Fork 派生
  - 审计日志记录团队治理动作

## 技术栈

### 前端

- React 18
- Vite 5
- `@supabase/supabase-js`

### 后端

- FastAPI
- Pydantic / pydantic-settings
- Supabase REST/Auth API

### 执行与模型

- MLZero
- AutoGluon Assistant（仓库内 `external/` 已有补丁）
- OpenAI-compatible provider
  - `chat_completions`
  - `responses`

## 目录结构

```text
AI4ML/
├─ backend/                    # FastAPI 后端
├─ frontend/                   # React + Vite 前端
├─ supabase/                   # Supabase schema 与数据库结构
├─ external/                   # 上游依赖仓库与本地补丁
├─ scripts/                    # 验证与辅助脚本
├─ data/                       # 示例数据
├─ storage/                    # 本地任务与运行产物
├─ docs/                       # 记忆文档与项目过程记录
├─ tools/                      # 其他辅助工具
└─ 周报/                       # 周报文档
```

## 主要后端接口

- `GET /api/health`
- 除健康检查外，正式业务接口统一使用团队作用域：`/api/teams/{team_id}/...`
- `GET/POST /api/teams/{team_id}/tasks`
- `POST /api/teams/{team_id}/tasks/{task_id}/dataset`
- `POST /api/teams/{team_id}/tasks/{task_id}/analyze`
- `POST /api/teams/{team_id}/tasks/{task_id}/run`
- `GET /api/teams/{team_id}/tasks/{task_id}/run-progress`
- `GET /api/teams/{team_id}/tasks/{task_id}/agent-collaboration`
- `GET /api/teams/{team_id}/tasks/{task_id}/human-collaboration`
- `POST /api/teams/{team_id}/tasks/{task_id}/human-requests`
- `POST /api/teams/{team_id}/tasks/{task_id}/human-requests/{request_id}/decision`
- `POST /api/teams/{team_id}/tasks/{task_id}/resume`
- `GET /api/teams/{team_id}/tasks/{task_id}/ai-conversations`
- `POST /api/teams/{team_id}/tasks/{task_id}/chat`
- `GET /api/teams/{team_id}/tasks/{task_id}/report`
- `POST /api/teams/{team_id}/tasks/{task_id}/prediction-demo`
- `GET /api/teams/{team_id}/tasks/{task_id}/code-workspace`
- `GET/PUT /api/teams/{team_id}/tasks/{task_id}/code-workspace/file`
- `GET /api/teams/{team_id}/tasks/{task_id}/code-workspace/download`
- `POST /api/teams/{team_id}/tasks/{task_id}/code-workspace/rerun`
- `GET/POST /api/teams/{team_id}/connectors`
- `GET/PATCH /api/teams/{team_id}/members`
- `GET/POST /api/teams/{team_id}/quotas`
- `GET/PUT /api/teams/{team_id}/routing`
- `GET/POST /api/teams/{team_id}/assets`
- `POST /api/teams/{team_id}/assets/{asset_id}/publish`
- `POST /api/teams/{team_id}/assets/{asset_id}/fork`
- `GET /api/teams/{team_id}/token-ledgers`
- `GET /api/teams/{team_id}/audit-logs`

## 环境准备

### 1. 前端 Supabase 配置

在 [`frontend/.env.example`](frontend/.env.example) 的基础上创建 `frontend/.env.local`：

```env
VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
VITE_API_ROOT=/api
```

### 2. 后端 AI Provider 配置

在 [`backend/.env.example`](backend/.env.example) 的基础上创建 `backend/.env.local`。

最小示例：

```env
AI4ML_MLZERO_PROVIDER_MODE=cloud
AI4ML_MLZERO_PROVIDER_BASE_URL_OVERRIDE=https://your-provider.example.com/v1
AI4ML_MLZERO_MODEL_ALIAS=your-model
AI4ML_MLZERO_PROVIDER_WIRE_API=chat_completions
AI4ML_MLZERO_EXECUTION_MODE=python
AI4ML_MLZERO_PYTHON_EXECUTABLE=D:\333\AI4ML\.venv\Scripts\python.exe
AI4ML_MLZERO_OPENAI_API_KEY=YOUR_REAL_API_KEY
AI4ML_CONNECTOR_SECRET_KEY=replace-with-a-stable-random-secret-at-least-16-bytes
AI4ML_MLZERO_MAX_ITERATIONS=6
AI4ML_MLZERO_CONTINUOUS_IMPROVEMENT=true
AI4ML_MLZERO_MIN_CANDIDATE_MODELS=3
```

说明：

- 后端会自动读取 `.env`、`.env.local`、`backend/.env.local`、`frontend/.env.local` 等文件。
- 不要把真实密钥提交到仓库。
- `AI4ML_CONNECTOR_SECRET_KEY` 用于加密新保存的连接器 API Key，必须保持稳定；更换后旧的加密连接器密钥将无法解密。历史明文连接器仍可读取，但新建或更新连接器必须配置该值。
- 模型报告、在线预测 Demo、代码工作区重跑都只读取真实任务产物；如果缺少运行目录、缺少 AutoGluon predictor 或缺少可重跑的 Python 工件，会明确返回“不支持/缺少产物”，不会生成假结果。

### 3. Supabase 数据库初始化

在 Supabase SQL Editor 中执行：

- [`supabase/schema.sql`](supabase/schema.sql)

这是当前团队、成员、任务、连接器、配额、路由、协同、资产、审计等能力的数据库基础。

## 启动方式

### 后端

PowerShell：

```powershell
cd <repo-root>
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend\requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

健康检查：

```powershell
curl http://127.0.0.1:8000/api/health
```

### 前端

```powershell
cd <repo-root>\frontend
npm install
npm run dev
```

访问：

- 前端：[http://localhost:5173](http://localhost:5173)
- 后端：[http://127.0.0.1:8000](http://127.0.0.1:8000)

## 运行时说明

- 默认任务产物会写到系统本地运行目录，而不是强依赖仓库内目录。
- Windows 默认运行产物目录通常位于：
  - `%LOCALAPPDATA%\AI4ML\mlzero_runs`
- 这样可以避免 `uvicorn --reload` 被运行过程中生成的 Python 文件反复触发。

## 前端主要页面

- 任务
- 运行控制台：运行态、Agent Runtime、事件流、leaderboard、训练遥测和最后日志
- AI 记录：只展示用户手动对话和当前连接器回复
- 代码工作区
- 复核待办：只处理人工请求、决策、转交、驳回和恢复任务
- Token 用量
- 连接器
- 默认 AI
- 配额
- 资产
- 团队
- 审计
- 系统

## 资产页面说明

当前“资产中心”是一个团队内部的资产登记台账，不是完整的文件托管系统。它主要用于登记以下几类产物：

- `dataset`
- `model`
- `workflow`
- `report`

并给它们附加：

- 标题
- 描述
- 存储路径
- 元数据
- 审核状态

当前版本更偏“资产登记与审核目录”。已支持团队内发布与 Fork 派生，但仍不是完整文件托管系统，也不是跨团队公开市场。

## 验证方式

### 后端基础检查

```powershell
cd <repo-root>
.\.venv\Scripts\python.exe -m compileall backend\app
.\.venv\Scripts\python.exe -m unittest discover backend\tests
```

### 前端构建检查

```powershell
cd <repo-root>\frontend
npm run build
```

### 已做过的真实联调验证

当前代码已经做过真实 Supabase 联调，验证通过的关键链路包括：

- 注册 / 登录
- 创建团队
- 邀请码入队
- 成员冻结 / 恢复
- 角色提升到 `developer_user`
- 连接器创建 / 激活
- 团队默认 AI 路由保存 / 读取
- 手工人工复核请求
- `before_run` 自动复核策略
- 代码工作区权限隔离
- 配额与预警阈值拦截
- 审计日志读取

## 当前限制

- 更高层的工作流广场、模型广场运营仍未完全产品化。
- 资产中心已有发布和 Fork，但仍是登记台账，不是完整资产平台。
- CSV 上传会生成真实数据集画像；工作流阶段记录会保存开始/结束时间、耗时、日志摘要和关键产物入口。
- Token 用量已同时支持任务级汇总和管理员可见的逐次 TokenLedger 流水。
- 代码工作区已有下载、版本记录和 Python 工件重跑，但仍是运行工件编辑器，不是完整 IDE。
- MLZero 长时多轮搜索虽然可配置，但实际稳定性仍依赖当前机器环境和所配置的云模型提供方。

## 重要文件

- [`docs/current-memory.md`](docs/current-memory.md)
- [`supabase/schema.sql`](supabase/schema.sql)
- [`backend/.env.example`](backend/.env.example)
- [`frontend/.env.example`](frontend/.env.example)

## 许可与备注

- 本仓库包含基于上游 `MLZero / AutoGluon Assistant` 的本地改造。
- `external/` 目录中的改动用于当前项目集成验证，不代表上游原始实现状态。
