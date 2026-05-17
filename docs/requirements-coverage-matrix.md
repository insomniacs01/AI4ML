# AI4ML 需求覆盖矩阵

生成日期：2026-05-06

对照来源：`MON-智算社区-2-需求-0420.docx`、`docs/current-memory.md`、当前 `backend/`、`frontend/`、`supabase/` 代码。

## 状态口径

| 状态 | 判定标准 |
| --- | --- |
| 已闭环 | 有真实后端接口或数据落库，有前端操作入口，能按团队/任务上下文读写真实数据，不依赖假数据。 |
| 部分闭环 | 有真实实现，但需求验收点仍有缺口，或只覆盖核心路径，边界能力尚未完全打通。 |
| 只是可视化 | 主要是页面展示、状态映射或说明，尚不能真实驱动对应业务能力。 |
| 未做 | 当前没有可用接口、数据模型或前端入口支撑该需求。 |

## 总览

| 优先级 | 总项数 | 已闭环 | 部分闭环 | 只是可视化 | 未做 |
| --- | ---: | ---: | ---: | ---: | ---: |
| P0 | 11 | 11 | 0 | 0 | 0 |
| P1 | 6 | 2 | 4 | 0 | 0 |
| P2 | 3 | 2 | 1 | 0 | 0 |
| 合计 | 20 | 15 | 5 | 0 | 0 |

## P0 覆盖矩阵

| 编号 | 需求 | 当前状态 | 当前依据 | 主要缺口 / 说明 |
| --- | --- | --- | --- | --- |
| FR-BAS-0001 | 系统健康检查与环境展示 | 已闭环 | `backend/app/api/routes/health.py` 返回 Provider、执行模式、模型、存储目录；`frontend/src/components/SystemPanel.jsx` 展示真实 health。 | `status` 表示后端存活；Provider/Executor 不可用时通过 `provider_status` / `executor_status` 暴露，不伪装成功。 |
| FR-BAS-0002 | 任务创建、列表与详情查询 | 已闭环 | `backend/app/api/routes/tasks.py` 的 `GET/POST /api/teams/{team_id}/tasks`、`GET /api/teams/{team_id}/tasks/{task_id}`；`TaskStore` 读写 Supabase `ai_tasks`；任务页真实列表/详情。 | 已按当前产品口径更新需求：创建任务只要求 `name` / `description`，`problem_type` 创建时可为空，上传 CSV 后由 AI 解析或人工确认后回写。 |
| FR-BAS-0003 | 本地执行、Provider 生命周期与失败处理 | 已闭环 | `MLZeroExecutor`、`LocalOpenAIProvider`、任务 `run` 接口、运行摘要/失败记录/输出目录回写；失败时保留 `last_run_attempt` 和错误说明。 | 真正可运行依赖本机 `.env.local`、Provider key、Python/Mamba/AutoGluon 环境；部署前必须单独验收运行环境。 |
| FR-ADM-0001 | 用户与权限管理 | 已闭环 | Supabase `profiles/teams/team_members`、RLS、`prevent_last_admin_change()`；后端 `require_team_*_access`；团队成员、设置、所有权转移页面。 | 邀请当前主要是邀请码/分享文案，不是完整邮件邀请系统；`RoleBinding` 未独立建表，而是通过角色枚举和依赖鉴权实现。 |
| FR-ADM-0002 | API Token / 资源额度管理 | 已闭环 | `quota_accounts`、`token_ledgers`、`adjust_member_token_usage()`；额度页、Token 用量页和管理员流水表；任务运行前有额度阻断逻辑；Provider 缺失 `usage` 时通过 `tiktoken` 按显式 tokenizer 复算并以 `tokenizer_estimate` 写账本。 | 不做固定倍率估算；未安装 `tiktoken` 或 tokenizer 未配置/不支持时明确失败。 |
| FR-ADM-0005 | AI 连接器接入、命名与默认 AI 组合管理 | 已闭环 | 连接器 CRUD/测试/激活/停用/删除；密钥加密；团队默认阶段路由 `ai_routing_policies`；任务级阶段覆盖。 | 当前运行策略是严格显式路由：默认路由缺失、连接器无效或只填模型名会直接失败，不再使用隐藏 fallback。 |
| FR-BIZ-0001 | 自然语言输入任务需求 | 已闭环 | 任务 `name/description` 保存；上传后 AI 解析结构化需求；任务详情展示 AI 解析结果和 token usage；`PUT /api/teams/{team_id}/tasks/{task_id}/semantic-analysis` 和任务详情表单支持人工修正目标列、任务类型、指标并写审计/阶段记录。 | 人工修正会清理当前任务上的旧运行结果，避免旧模型结果继续被当成新语义的结果。 |
| FR-BIZ-0002 | 数据集上传 | 已闭环 | CSV 上传接口校验文件名、类型、大小、空文件、二进制空字节、UTF-8；`dataset_profile` 保存列、缺失值、样例预览。 | 本地文件目录当前是 `storage/tasks/<task_id>`，未按旧文档的 `storage/tasks/<team_id>/<task_id>` 分层；元数据已按团队隔离在 Supabase。 |
| FR-BIZ-0003 | 自动解析需求并启动 AI 工作流 | 已闭环 | CSV 上传后默认 `auto_run=true`：先执行真实 AI 解析，再自动进入 `run_task` 的 MLZero 工作流；任务运行写入 6 个阶段状态；MLZero 执行后回写结果、账本和阶段记录。 | 如触发 `before_run` 人机策略会自动停在等待人工节点；运行失败会保留真实错误和尝试目录，不伪装成功。 |
| FR-BIZ-0004 | 智能体工作进度可视化 | 已闭环 | `task_agent_runs` 持久化 6 个后端 Agent Runtime，`task_agent_events` 记录 Agent 事件流，`task_agent_messages` 记录 Agent 间协作、交接、确认、阻塞和人工节点消息；`GET /api/teams/{team_id}/tasks/{task_id}/agent-collaboration` 返回 Agent Runtime 快照；`GET /api/teams/{team_id}/tasks/{task_id}/run-progress` 返回真实日志、leaderboard、训练遥测和观察层状态；运行控制台统一展示这些运行态信息。 | 运行控制台负责运行态；复核待办只处理人工决策；AI 记录只展示手动对话。当前是阶段编排中的真实协作消息，不声称启动了 6 个并行 OS 进程或自由辩论 worker。 |
| FR-BIZ-0005 | 模型训练结果输出 | 已闭环 | `run_summary.json`、leaderboard、`token_usage.json` 严格解析；任务详情和 `LeaderboardPanel` 展示最佳模型、指标、候选模型、输出目录。 | 依赖 MLZero 产物完整性；缺少真实 summary/leaderboard/token_usage 时会失败，不制造结果。 |
| FR-BIZ-0008 | 按阶段选择 AI 或使用管理员默认组合 | 已闭环 | 任务表单支持阶段覆盖；团队默认 AI 页面保存阶段路由；后端解析任务覆盖优先，再继承团队默认。 | “什么都不选也能运行”的前提是团队已配置默认阶段路由；没有默认路由时系统按严格模式报错。 |
| FR-DEV-0001 | 阶段级人工复核策略与干预机制 | 已闭环 | 任务创建/配置可保存 `interaction_policies`；复核请求、决策、转交、过期、恢复、审计、重跑提示已实现。 | 没有独立消息通知系统；待办主要在前端复核待办页展示，不再混入运行控制台或 AI 记录。 |

## P1 覆盖矩阵

| 编号 | 需求 | 当前状态 | 当前依据 | 主要缺口 / 说明 |
| --- | --- | --- | --- | --- |
| FR-ADM-0003 | 数据中心管理 | 已闭环 | `platform_assets` 支持 dataset/model/workflow/report；资产页支持登记、分类、标签、可见性、审核、发布、Fork；可从当前任务沉淀数据集资产。 | 数据集预览主要来自任务详情的 `dataset_profile`，资产中心本身还不是专门的数据集浏览器。 |
| FR-ADM-0004 | 模型广场管理 | 部分闭环 | 模型资产可登记、带 `model_card`、来源任务、指标元数据、审核/发布/Fork；资产页可筛选模型。 | 目前是统一资产中心表格，不是完整“模型广场”体验；模型卡片展示、模型详情页、搜索推荐仍偏弱。 |
| FR-BIZ-0007 | 生成模型分析报告 | 部分闭环 | `GET /api/teams/{team_id}/tasks/{task_id}/report` 基于真实任务、数据集画像、运行结果、特征重要性文件生成报告；前端报告页已接入。 | 图表化报告和自然语言深度解释仍有限；特征重要性依赖真实产物，缺少文件时会明确不展示而不是伪造。 |
| FR-DEV-0003 | 查看最终生成的 Python 源代码 | 已闭环 | 代码工作区可读取真实运行目录，识别 `generated_code.py`、脚本、日志、状态和结果文件；支持查看、下载、版本历史。 | 权限边界依赖现有团队开发/管理员鉴权；更细的阶段级源码授权还可继续强化。 |
| FR-DEV-0005 | 工作流分享 | 部分闭环 | 工作流可作为 `workflow` 类型资产登记、审核、发布；从当前任务沉淀工作流资产时保存阶段路由、人机策略、运行信息。 | 发布后的工作流还不能一键作为模板创建并执行新任务；当前主要是资产沉淀和浏览层闭环。 |
| FR-DEV-0006 | Fork 与复用 | 部分闭环 | 资产 Fork 会创建独立副本，保留 `source_asset_id`、来源 metadata、版本和当前归属。 | Fork 后的工作流/模型资产还没有完整“套用到新任务继续运行”的产品链路。 |

## P2 覆盖矩阵

| 编号 | 需求 | 当前状态 | 当前依据 | 主要缺口 / 说明 |
| --- | --- | --- | --- | --- |
| FR-BIZ-0006 | 一键获得 Web Demo / 在线测试接口 | 已闭环 | `POST /api/teams/{team_id}/tasks/{task_id}/prediction-demo` 会加载真实 AutoGluon predictor 或安全的 `generated_code.py predict()` 合约；前端在线预测页已接入。 | 不是自动发布独立 Web Demo；没有可加载模型或预测合约时会明确返回不支持。 |
| FR-DEV-0002 | 节点级人工确认、驳回与重试 | 已闭环 | 人工决策支持 approve/revise/reject/block/reassign/skip；reject/revise 会记录 `rerun_from_stage`；严格增量重跑覆盖多个阶段。 | 多节点通知和升级策略还可增强，但核心确认、驳回、转交、阶段重跑已经真实可用。 |
| FR-DEV-0004 | 修改 Python 源代码 | 部分闭环 | 代码工作区支持编辑保存、版本记录、下载和单文件/工件重跑，stdout/stderr 写回真实目录。 | 保存后的修改尚未完全并入任务级 MLZero run summary/leaderboard 同步链路；更像工件编辑器，还不是完整 IDE。 |

## 跨切面验收项

| 领域 | 当前覆盖 | 状态 | 说明 |
| --- | --- | --- | --- |
| Supabase 统一身份与团队隔离 | Supabase Auth、team_members、RLS、FastAPI bearer token + `/api/teams/{team_id}/...` 团队作用域路径 | 已闭环 | 主应用已不挂载旧 FastAPI `/auth`、`/users`，业务 API 不再正式暴露非团队作用域路径；旧本地用户路由、模型、JWT 工具和 `UserStore` 已清理出仓库。 |
| 审计日志 | 团队治理、连接器、任务、运行、人工复核、代码工作区、资产等关键操作写 `audit_logs` | 已闭环 | 管理员审计页面读取真实记录。 |
| 失败可观察性 | 严格禁止 fake success / hidden fallback；缺 route、缺产物、缺 token usage 时明确失败 | 已闭环 | 与当前项目记忆中的“不伪造、不静默兜底”约束一致。 |
| 数据模型 | `ai_tasks`、`workflow_stage_records`、`task_agent_runs`、`task_agent_events`、`task_agent_messages`、`human_interaction_requests`、`quota_accounts`、`token_ledgers`、`platform_assets` 等已在 schema 中定义 | 已闭环 | 上线 Supabase 必须应用最新 `supabase/schema.sql`。 |
| 文件存储结构 | 任务数据集和 MLZero 运行产物写本地 `storage/` | 部分闭环 | 任务文件目录与旧需求文档存在 team_id 分层差异；建议下一步统一文档或调整 `TaskStore._task_dir()`。 |
| 性能体验 | 前端 GET 缓存、请求去重、页面懒加载、协作快照缓存、有限页面保活；后端 Supabase auth 短缓存 | 部分闭环 | 还没有接口耗时监控和后端聚合缓存；页面保活当前只保留 2 个 pane。 |

## 优先处理缺口建议

1. 修正或确认任务文件目录：在文档和实现之间统一 `storage/tasks/<task_id>` 与 `storage/tasks/<team_id>/<task_id>` 的口径。
2. 强化工作流资产复用：让已发布或 Fork 的 workflow 资产可以一键生成新任务配置，而不仅是资产记录。
3. 完善报告体验：补图表、自然语言解释和报告导出，同时继续坚持缺真实产物就明确说明不可用。
