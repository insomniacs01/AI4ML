export const navItems = [
  { id: "dashboard", label: "仪表盘", icon: "dashboard" },
  { id: "monitoring", label: "监控中心", icon: "pulse" },
  { id: "workflow", label: "工作流", icon: "workflow" },
  { id: "report", label: "模型报告", icon: "report" },
  { id: "members", label: "团队成员", icon: "users" },
  { id: "connectors", label: "AI 连接器", icon: "plug" },
  { id: "routing", label: "路由策略", icon: "route" },
  { id: "quotas", label: "配额管理", icon: "quota" },
  { id: "system", label: "系统信息", icon: "server" },
  { id: "audit", label: "审计日志", icon: "logs" }
];

export const monitoringMetrics = [
  { label: "总请求数", dependency: "需要后端服务的聚合请求指标。" },
  { label: "成功率", dependency: "需要任务状态聚合和失败分类能力。" },
  { label: "输入 Token", dependency: "需要接入用量账本或 Token 统计数据。" },
  { label: "输出 Token", dependency: "需要接入用量账本或分词统计能力。" }
];

export const reportSections = [
  { title: "指标摘要", dependency: "任务完成运行后，已可以从 task.last_run 中读取部分结果。" },
  { title: "特征重要性", dependency: "仍然需要后端提供独立的报告载荷。" },
  { title: "文字总结", dependency: "仍然需要自然语言报告生成输出。" }
];

export const connectorFields = [
  "显示名称",
  "提供方",
  "基础地址",
  "可用模型",
  "凭证状态"
];

export const routingStages = [
  "需求分析",
  "数据处理",
  "模型选择",
  "训练与验证",
  "报告生成"
];

export const quotaChecks = [
  "按成员查看配额概览",
  "按成员与连接器拆分配额",
  "Token 账本用量",
  "运行前配额保护"
];

export const auditScopes = [
  "角色变更",
  "配额变更",
  "连接器配置",
  "人工干预",
  "工作流发布与分叉"
];

export const systemFields = [
  { label: "状态", key: "status" },
  { label: "选定基础方案", key: "selected_project_base" },
  { label: "运行时", key: "execution_runtime" },
  { label: "执行模式", key: "execution_mode" },
  { label: "提供方模式", key: "provider_mode" },
  { label: "接口线路", key: "provider_wire_api" },
  { label: "提供方状态", key: "provider_status" },
  { label: "提供方详情", key: "provider_detail" },
  { label: "任务执行器", key: "task_executor" },
  { label: "执行器状态", key: "executor_status" },
  { label: "执行器详情", key: "executor_detail" },
  { label: "提供方地址", key: "provider_base_url" },
  { label: "模型别名", key: "model_alias" },
  { label: "任务存储目录", key: "storage_dir" },
  { label: "运行输出目录", key: "run_output_dir" }
];

export const monitoringRangeOptions = ["今天", "7天", "14天", "30天"];

export const monitoringSummaryCards = [
  {
    label: "总请求数",
    value: "21,434",
    detail: "按当前筛选区间统计",
    hint: "模板数据，等待真实聚合接口接入",
    icon: "pulse"
  },
  {
    label: "成功率",
    value: "98.68%",
    detail: "成功 21,150 / 失败 284",
    hint: "后续应由任务状态聚合接口提供",
    icon: "shield"
  },
  {
    label: "总 Token",
    value: "1,481,747,869",
    detail: "输入 + 输出 + 推理缓存",
    hint: "当前仅作界面模板展示",
    icon: "sigma"
  },
  {
    label: "输出 Token",
    value: "9,070,766",
    detail: "输入 Token: 1,472,677,103",
    hint: "后续应由用量账本提供",
    icon: "coins"
  }
];

export const monitoringModelDistribution = [
  { name: "kimi-k2.5", value: "10.2k", share: 47.4, color: "#5b8ff9" },
  { name: "gpt-5.4", value: "9.1k", share: 42.5, color: "#34c98c" },
  { name: "gpt-5.2", value: "2.2k", share: 10.0, color: "#9b7bff" },
  { name: "kimi-k2", value: "18", share: 0.1, color: "#ffb020" },
  { name: "gpt-5.1-codex-mini", value: "4", share: 0.0, color: "#ff6485" }
];

export const monitoringTrendSeries = [
  { label: "03/26", totalTokens: 120, requests: 1600 },
  { label: "03/27", totalTokens: 84, requests: 1150 },
  { label: "03/28", totalTokens: 118, requests: 1680 },
  { label: "03/29", totalTokens: 148, requests: 1760 },
  { label: "03/30", totalTokens: 388, requests: 5120 },
  { label: "03/31", totalTokens: 326, requests: 4010 },
  { label: "04/01", totalTokens: 338, requests: 3520 }
];

export const monitoringApiKeyShares = [
  { name: "default-service", value: "15.2k", share: 70.8, color: "#5b8ff9" },
  { name: "analysis-runner", value: "3.4k", share: 15.7, color: "#34c98c" },
  { name: "ops-dashboard", value: "1.2k", share: 5.8, color: "#9b7bff" },
  { name: "staging-proxy", value: "0.9k", share: 4.2, color: "#ffb020" },
  { name: "manual-debug", value: "0.7k", share: 3.5, color: "#ff6485" }
];
