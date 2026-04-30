# AI4ML Backend Unification Plan

## 目标

把当前“Supabase 管一部分、FastAPI 管一部分、FastAPI 里还残留一套本地用户系统”的状态，收敛成一套职责清晰、权限统一、数据归属明确的架构。

这里的“统一”不一定意味着必须只剩一个进程或一个服务，而是要做到：

- 身份来源唯一
- 团队归属唯一
- 任务归属唯一
- 权限判断唯一
- 前端调用路径清晰

## 当前问题

### 1. 身份体系有两套

- 前端当前登录、注册、团队创建、团队加入，使用的是 Supabase
- FastAPI 自己还保留了 `/auth`、`/users`、本地 `UserStore`、默认 admin 账号
- 前端并没有使用 FastAPI 这套本地用户体系

结果：

- 前端眼中的“当前用户”来自 Supabase
- FastAPI 眼中的“当前用户”可能来自本地 JWT 和 `storage/users`
- 两边不是同一个真相源

### 2. 团队体系只在 Supabase 里真实存在

- `profiles`、`teams`、`team_members` 在 Supabase 中存在
- 当前任务接口没有真正把任务和 `team_id` 绑定
- 前端虽然有“当前 team”的概念，但 FastAPI 任务还没有按团队隔离

结果：

- UI 上看起来有团队
- 实际任务数据还不是严格的团队内数据

### 3. 任务权限没有和身份体系打通

- FastAPI 当前的 `/tasks` 接口没有基于 Supabase 会话做权限校验
- 前端可以在登录 Supabase 后看到工作区，但任务接口本身并不理解 Supabase 用户是谁

结果：

- 认证和业务执行是分离的
- 后续做“按团队看任务、按成员做配额、按角色限制操作”会越来越难

## 推荐的统一方案

推荐保留：

- Supabase 作为身份与协作层
- FastAPI 作为业务与执行层

也就是：

- Supabase 负责：登录、注册、用户资料、团队、成员关系、RLS
- FastAPI 负责：任务、CSV 上传、MLZero 执行、运行结果、健康检查、后续报告生成

同时明确一条规则：

> Supabase 是用户和团队的唯一真相源。

FastAPI 不再自己维护独立的用户体系，只信任 Supabase 发出的身份信息。

## 为什么推荐这个方案

这是当前仓库改动最小、风险最低、也最符合现状的收敛路线。

原因：

- 前端已经接上了 Supabase 登录和团队
- Supabase schema 已经建好了 profiles / teams / team_members
- FastAPI 已经在做任务执行，不需要再重复造认证和团队系统
- 如果反过来把 Supabase 废掉，等于要重写前端现有登录与团队流

## 目标架构

### 统一后的职责边界

#### Supabase

- 用户登录 / 注册
- 会话管理
- 用户资料
- 团队与成员关系
- 后续可扩展的配额 / 审计 / 分享元数据

#### FastAPI

- 校验 Supabase Bearer Token
- 识别当前用户 `user_id`
- 识别当前团队 `team_id`
- 任务创建 / 查询 / 上传 / 执行
- 运行结果和模型报告
- 本地文件与 MLZero runtime 管理

### 前端调用原则

- 登录、注册、团队相关：直接调用 Supabase
- 任务和执行相关：调用 FastAPI
- 每次调用 FastAPI 时，必须带上：
  - `Authorization: Bearer <supabase_access_token>`
  - 当前 `team_id`

## 需要落地的统一动作

## 阶段 1：冻结 FastAPI 本地用户体系

目标：

- 前端不再考虑接入 FastAPI 的 `/auth` 和 `/users`
- 后端本地 `UserStore` 标记为待移除

建议处理：

- 保留代码一小段过渡期，但不再作为正式架构的一部分
- 在文档中明确：本地用户系统已废弃

涉及文件：

- `backend/app/api/routes/users.py`
- `backend/app/services/user_store.py`
- `backend/app/core/security.py`
- `backend/app/core/deps.py`

## 阶段 2：FastAPI 改为信任 Supabase 身份

目标：

- FastAPI 从前端 Bearer Token 中识别 Supabase 用户

做法：

- 新增 Supabase JWT 校验逻辑
- 新增依赖，例如 `get_current_supabase_user()`
- 从 token 中提取 `sub` 作为 `user_id`

说明：

- 这一步之后，FastAPI 不再依赖本地 `storage/users` 判断“是谁在请求”

建议新增文件：

- `backend/app/core/supabase_auth.py`

建议改动文件：

- `backend/app/core/deps.py`
- `backend/app/main.py`
- `backend/app/api/routes/tasks.py`

## 阶段 3：任务必须绑定 team_id 和 created_by

目标：

- 每个任务都清楚属于哪个团队、由谁创建

建议新增字段：

- `team_id`
- `created_by`
- `updated_by`（可选）

建议改动：

- `TaskCreateRequest` 支持或隐式绑定团队信息
- `TaskRecord` 增加团队和用户字段
- `TaskStore` 改成按团队组织

推荐目录结构：

```text
storage/tasks/
  <team_id>/
    <task_id>/
      task.json
      dataset.csv
```

涉及文件：

- `backend/app/models/task.py`
- `backend/app/services/task_store.py`
- `backend/app/api/routes/tasks.py`

## 阶段 4：任务接口强制做团队权限校验

目标：

- 用户只能访问自己所在团队的任务

做法：

- 前端调用 FastAPI 时传入当前团队 `team_id`
- FastAPI 根据 Supabase 用户 `user_id` 和 `team_id` 校验成员关系
- 校验通过后才允许：
  - 列任务
  - 看任务
  - 上传数据
  - 运行任务

实现方式有两种：

### 方案 A：FastAPI 通过 Supabase 查询团队成员关系

优点：

- 清晰直接
- 与当前 schema 一致

缺点：

- FastAPI 需要访问 Supabase

### 方案 B：把团队信息放进前端请求头并完全信前端

不推荐。

原因：

- 安全性不够
- 权限控制会失真

推荐采用方案 A。

## 阶段 5：前端 API 层统一注入 token 和 team_id

目标：

- 前端所有 FastAPI 请求都带同样的认证上下文

做法：

- `frontend/src/lib/api.js` 改为支持：
  - access token
  - active team id
- 在 `App.jsx` 中调用 API 时注入当前 Supabase session token 和 activeTeamId

建议形式：

- `Authorization: Bearer <token>`
- `X-Team-Id: <team_id>`

涉及文件：

- `frontend/src/lib/api.js`
- `frontend/src/App.jsx`

## 阶段 6：删除或下线 FastAPI 本地用户接口

目标：

- 项目里只保留一套正式身份体系

完成标志：

- 前端不再使用 `/auth` `/users`
- FastAPI 内部也不再依赖 `UserStore`
- `storage/users` 不再作为正式业务存储

届时可以移除：

- `backend/app/api/routes/users.py`
- `backend/app/services/user_store.py`
- 与本地 JWT 相关的旧逻辑

## 阶段 7：把配额、审计、分享等平台能力也收口到同一数据面

目标：

- 后面新增的平台能力不要再分叉

推荐：

- 配额、审计、团队元数据、工作流分享信息，优先放在 Supabase
- 本地文件系统只保存：
  - 上传文件
  - 运行产物
  - 模型输出
  - 日志

这样分层最稳定：

- Supabase 管结构化业务数据
- FastAPI 管执行逻辑
- 本地文件系统管大文件和运行产物

## 最推荐的实施顺序

按风险从低到高，建议这样做：

1. 前端 API 层统一携带 Supabase token 和 `team_id`
2. FastAPI 增加 Supabase token 校验
3. `TaskRecord` 增加 `team_id` / `created_by`
4. `TaskStore` 改成按团队存储
5. `/tasks` 接口增加团队权限校验
6. 下线 `/auth` `/users` 和 `UserStore`

## 统一完成后的效果

统一完成后，项目会变成：

- 登录身份只有一套：Supabase
- 团队只有一套：Supabase teams
- 任务只有一套归属：FastAPI 中绑定 team_id 的任务
- 权限只有一套判断逻辑：Supabase 用户 + 团队成员关系
- 前端只有一套业务调用方式：Supabase 做身份，FastAPI 做任务

## 一句话结论

最好的统一方式不是“强行只剩一个后端进程”，而是：

> 保留 Supabase 作为身份和团队真相源，保留 FastAPI 作为任务和执行服务，并让 FastAPI 全面信任 Supabase 身份、按团队隔离任务，从而消除双用户体系和双权限体系。

## 下一步建议

下一步最值得直接开始做的是：

1. 让 FastAPI 识别 Supabase Bearer Token
2. 给任务加 `team_id` 和 `created_by`
3. 让 `/tasks` 按当前团队隔离

这三步一做，整个项目的主干就会真正统一起来。
