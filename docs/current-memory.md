# AI4ML Current Memory

## 项目定位

AI4ML 是一个团队协作式智能建模工作台。当前产品主线是：用户在团队空间内创建建模任务、上传 CSV、通过 AI 解析任务语义、调用 MLZero/AutoGluon 训练模型，并在运行控制台、模型报告、代码文件、人工复核和资产库中查看真实产物与协作记录。

## 当前产品口径调整（2026-05-14）

当前版本前端应明确收敛为面向新人和课堂展示的“统一建模向导”，而不是复杂的可配置工作流平台。首要目标是让零基础用户理解并完成一条稳定闭环：

上传 CSV / 描述目标 -> AI 理解需求 -> 自动尝试建模 -> 生成可读结果 -> 必要时人工复核。

近期不再把以下能力作为主导航或展示重点：

- 独立“资产库/成果库”主页面。
- 工作流模板复用、Fork 工作流、从模板再做一次。
- 模型广场、工作流广场、跨任务模板运营。
- 面向新人直接暴露的阶段路由、连接器细节、Token 账本、运行控制台、代码文件、审计日志等技术后台能力。

这些能力如果仍需保留，应降级为专家模式、团队管理二级入口，或结果报告/历史任务中的弱入口。当前展示中不要承诺“自动带入任务描述、目标列、流程设置、复核规则”的模板复用能力，除非后续真正实现该逻辑。

建议当前主导航收敛为：

- 开始建模
- 我的任务
- 结果报告
- 复核待办
- 团队管理

专家能力统一折叠到“专家模式”或团队管理二级页中，避免新人一进入系统就看到大量专业术语。

2026-05-14 的展示口径进一步明确：

- 专家页面不能直接删除入口，但默认只展示核心结论、当前状态和必要操作；日志、代码、大表、账本、配置表单、策略细节等进入可展开区域。
- “复核待办”是当前用户自己的复核处理台，不是团队审查看板。默认只展示后端返回的 `my_requests` / `my_open_request_count`。
- 团队成员分派、转交、候选组、人工决策注入、调试预览等不作为当前页面主 UI；必要历史兼容逻辑保留在后端和数据结构中。
- Fork、模板复用、工作流市场等能力当前不应该作为展示重点。当前主流程仍是每次基于任务数据重新跑固定建模链路。

## 华为云 ModelArts MaaS 配置口径（2026-05-14）

用户提供的华为云模型服务是 OpenAI-compatible Chat Completions 接口，不是 SSH 代码部署服务器。

- API 地址：`https://api.modelarts-maas.com/v2/chat/completions`
- 建议后端 base URL：`https://api.modelarts-maas.com/v2`
- model 参数：`deepseek-v3.2`
- wire API：`chat_completions`
- API Key：用户已在对话中提供过真实 key，但该值属于密钥，不能写入仓库文档或提交到 git；只允许放在本机/服务器忽略提交的 `backend/.env.local` 中。记忆文档只记录脱敏标识：`yfb-JZ...cg`。

对应 `backend/.env.local` 配置应使用：

```env
AI4ML_MLZERO_PROVIDER_MODE=cloud
AI4ML_MLZERO_PROVIDER_BASE_URL_OVERRIDE=https://api.modelarts-maas.com/v2
AI4ML_MLZERO_MODEL_ALIAS=deepseek-v3.2
AI4ML_MLZERO_PROVIDER_WIRE_API=chat_completions
AI4ML_MLZERO_OPENAI_API_KEY=<真实华为云 ModelArts MaaS API Key>
```

## 华为云 ECS 部署目标（2026-05-14）

用户确认当前代码需要同步到华为云 ECS：

- 组名：`MON-1-2`
- 服务器名称/ID：`ecs-ed03-0011`
- 公网 IP：`116.63.15.143`
- 私有 IP：`192.168.0.78`
- 当前可用 SSH 用户：`root`
- 本机 SSH 别名：`ai4ml-huawei`
- 免密私钥：`C:\Users\LENOVO\.ssh\id_rsa`
- 线上应用目录：`/opt/ai4ml/app`
- 后端虚拟环境：`/opt/ai4ml/venv`
- 后端 systemd 服务：`ai4ml-backend.service`
- 前端由 nginx 直接服务：`/opt/ai4ml/app/frontend/dist`
- 后端反向代理：nginx `/api/` -> `http://127.0.0.1:8000/api/`

服务器密码属于敏感信息，不写入记忆文档或仓库。同步代码时应保留服务器上的 `backend/.env.local`、`frontend/.env.local` 和 `/var/lib/ai4ml` 运行数据。

## 当前硬约束

- 不展示伪数据，不制造假成功，不用演示值冒充真实业务结果。
- 不做静默 fallback。连接器、模型、运行产物、Supabase 权限或 MLZero 产物缺失时必须明确失败或显示“不支持/未接入”。
- 正式业务 API 统一走 `/api/teams/{team_id}/...`，除 `/api/health` 外不再使用非团队作用域业务路径。
- 当前正式 AI 路由只保留主路由：`stage`、`connector_id`、`model_name`、`config`。历史 `fallback_connector_id` / `fallback_model_name` 已从 schema、模型、store 和前端提交路径清理。
- 运行成功判定严格依赖真实 MLZero 产物，尤其是 `run_summary`、`leaderboard`、`token_usage` 等完整记录。

## 当前架构

- 前端：React/Vite，主入口 `frontend/src/App.jsx`，按页面 lazy load。
- 后端：FastAPI，任务相关路由已拆为生命周期、运行、产物、人工协作等子路由。
- 身份和团队：Supabase session + team scope 是正式来源。
- 存储：任务、治理、连接器、配额、审计、资产等走 Supabase store。
- 执行：后端通过 MLZero executor 运行真实 AutoGluon/MLZero 链路。
- 运行观测：`task_run_progress` 读取真实日志、事件、leaderboard、telemetry、observer insight。

## 当前已完成能力

- Supabase 登录、团队上下文、团队成员/角色、团队设置。
- 任务创建、CSV 上传、任务列表/详情、任务语义解析。
- 阶段默认 AI 连接器和任务级 stage routing。
- MLZero 运行、增量重跑、可恢复失败标记、运行进度读取。
- 运行控制台：Agent Runtime、运行事件、日志摘要、实时 leaderboard、训练 telemetry、observer 状态。
- AI 记录页：只展示用户手动对话，不再混入系统日志或训练事件。
- 复核待办页：个人待办视角；后端返回 `my_requests` 和 `my_open_request_count`，前端默认只展示当前用户相关请求，手动补记录和历史处理折叠。
- 代码文件页：查看真实运行目录中的代码、结果、日志和上下文工件。
- 模型报告页：展示最终解释、指标说明、风险局限、feature importance 和 Markdown 报告。
- 在线预测页：调用真实任务运行产物；缺少可加载模型或预测合约时明确说明暂不支持。
- 消耗账本、资产库、连接器管理、配额、审计日志等治理能力已接入真实接口或明确真实状态，但当前前端展示应作为专家/管理能力收起，不作为新人主流程入口。

## 最近完成的清理

- 任务路由瘦身：`tasks.py` 已拆成聚合 router，具体逻辑分到 `task_lifecycle.py`、`task_runtime.py`、`task_artifacts.py`、`task_human.py` 和共享 `task_route_common.py`。
- 页面边界收敛：
  - 开始建模页只保留任务创建、下一步动作、生命周期进度、关键 KPI 和轻量跳转。
  - 运行控制台只负责运行态、事件、日志、leaderboard、telemetry 和 observer。
  - AI 记录只负责手动对话。
  - 复核待办只负责人工决策。
  - 模型报告只负责最终解释和报告内容，不再重复完整 leaderboard。
- 产物解析收敛：`backend/app/services/task_artifacts.py` 集中处理运行目录、核心产物、feature importance、stage artifact、日志摘要和报错文件选择。
- 功能臃肿清理：
  - 删除旧 `frontend/src/prototypeData.js`。
  - 新增 `frontend/src/lib/taskPresentation.js`，统一前端状态/阶段/时间/运行日志清洗等展示口径。
  - 多个页面已改为复用该展示层，减少重复实现。
- 历史 fallback 路由字段已从正式数据模型和保存路径移除。
- 前端展示降噪：
  - 主导航收敛为开始建模、我的任务、结果报告、复核待办、团队管理。
  - 专家工具仍保留入口，但通过顶栏“专家工具”选择进入，不再占据新人主导航。
  - `RoutePane` 仅挂载当前激活页面，减少多个重页面同时渲染导致浏览器卡死或“页面没有响应”。
  - 运行控制台、代码工作区、Token 账本、资产、连接器、配额等页面改为概览优先，重日志、大表和高级操作默认折叠。
  - 任务列表渲染数量做了限制，报告页不再高频轮询，整体减少前端卡顿。
- 人工复核个人化：
  - `TaskHumanCollaborationResponse` 新增 `my_requests` / `my_open_request_count`。
  - `TaskHumanCollaborationService.get_snapshot(...)` 按当前 actor 过滤本人相关请求；管理员不会自动在 `my_requests` 中看到全队请求。
  - 创建、决策、恢复任务接口会把当前用户身份传入 snapshot，保证返回结果符合个人视角。
  - 前端移除“人工决策注入/调试预览”和团队审查看板式 UI；保留后端 assignee/reassign/candidate_pool 兼容历史数据、自动策略和权限校验。

## 关键文件

- `frontend/src/App.jsx`：主应用壳、页面路由、任务主流程。
- `frontend/src/lib/api.js`：团队作用域 API client。
- `frontend/src/lib/taskPresentation.js`：前端任务状态/阶段/运行文本展示公共口径。
- `frontend/src/components/MultiAgentCollaborationPanel.jsx`：运行控制台。
- `frontend/src/components/ModelReportPanel.jsx`：模型报告。
- `frontend/src/components/CodeWorkspacePanel.jsx`：代码/产物工作区。
- `frontend/src/components/HumanCollaborationPanel.jsx`：人工复核。
- `backend/app/api/routes/tasks.py`：任务聚合 router。
- `backend/app/api/routes/task_human.py`：人工复核 API，负责把当前团队用户身份传入协作 snapshot。
- `backend/app/api/routes/task_route_common.py`：任务路由共享依赖和少量共享逻辑，后续仍可继续瘦身。
- `backend/app/models/task.py`：任务、人机协作响应模型，包含 `my_requests` / `my_open_request_count`。
- `backend/app/services/task_human_collaboration.py`：人工复核生命周期、个人待办过滤和恢复任务逻辑。
- `backend/app/services/task_artifacts.py`：运行产物索引和文件定位。
- `backend/app/services/task_run_progress.py`：运行进度、日志和 observer 状态。
- `backend/app/services/executors/mlzero_executor.py`：MLZero 执行器。
- `supabase/schema.sql`：正式数据库结构。

## 最新验证状态

最近一次已通过（2026-05-14，本轮定向验证）：

- `cd frontend && npm run build`
- `.\.venv\Scripts\python.exe -m compileall -q backend/app backend/tests/test_human_collaboration.py`
- `.\.venv\Scripts\python.exe -m unittest backend.tests.test_human_collaboration`

说明：系统 Python 缺少 `pydantic_settings`，项目测试需要使用 `.venv`；当前 `.venv` 未安装 `pytest`，人工复核回归使用 `unittest` 跑通。此前后端 `unittest discover backend\tests` 曾通过 56 个测试，本轮未重新跑全量 discover。

## 后续优先级

1. 继续保持主流程/专家模式边界：不要把专家能力重新塞回新人主导航。
2. 开始建模页继续按新人向导打磨：突出“说清目标、上传数据、AI 自动尝试、看懂结果”，弱化阶段路由和人工策略等高级配置。
3. 我的任务、结果报告和复核待办页继续用业务可理解语言解释状态、结果、风险和下一步，不直接堆底层技术术语。
4. 继续拆 `App.jsx`：优先抽 `TaskDetailPanel` 和任务/治理数据 hooks，配合新的页面层级。
5. 继续瘦身 `task_route_common.py`：把运行诊断、stale repair、阶段记录等实现逻辑继续下沉到 service。
6. 逐步治理 `frontend/src/styles.css`，减少历史样式重复，并加入克制的流程动效和科技感视觉系统。
7. 保持当前验收口径：所有页面必须基于真实数据或明确说明未接入/暂不支持。
