import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import AuthScreen from "./components/AuthScreen.jsx";
import SystemPanel from "./components/SystemPanel.jsx";
import TaskCard from "./components/TaskCard.jsx";
import TaskForm from "./components/TaskForm.jsx";
import TeamOnboarding from "./components/TeamOnboarding.jsx";
import TokenUsagePanel, { formatTokenValue, hasTokenUsage } from "./components/TokenUsagePanel.jsx";
import { api } from "./lib/api.js";
import {
  formatMetricName as formatCatalogMetricName,
  getMetricDirectionLabel,
} from "./lib/metrics.js";
import { readSupabaseAuthSettings, supabase, supabaseReady } from "./lib/supabase.js";
import {
  formatDateTime,
  compactStatusLabel,
  formatProblemType,
  formatRuntimeStatusLabel,
  formatTaskAnalysisStatus,
  formatTaskStatus,
  formatWorkflowStage,
  getReadableRuntimeActivity,
  getTaskRuntimeStatus,
  getTaskStatusTone,
  isRawRuntimeDebugText,
  isRecoverableRunBlockedTask,
  sanitizeRuntimeText,
} from "./lib/taskPresentation.js";

const PAGE_LOADERS = {
  agents: () => import("./components/MultiAgentCollaborationPanel.jsx"),
  assets: () => import("./components/AssetCenterPanel.jsx"),
  audit: () => import("./components/AuditLogPanel.jsx"),
  code: () => import("./components/CodeWorkspacePanel.jsx"),
  connectors: () => import("./components/ConnectorManagementPanel.jsx"),
  conversations: () => import("./components/AIConversationPanel.jsx"),
  demo: () => import("./components/PredictionDemoPanel.jsx"),
  human: () => import("./components/HumanCollaborationPanel.jsx"),
  quotas: () => import("./components/QuotaManagementPanel.jsx"),
  report: () => import("./components/ModelReportPanel.jsx"),
  routing: () => import("./components/RoutingPolicyPanel.jsx"),
  team: () => import("./components/TeamMembersPanel.jsx"),
};

function preloadPageComponent(pageId) {
  const loader = PAGE_LOADERS[pageId];
  if (loader) void loader();
}

const AIConversationPanel = lazy(PAGE_LOADERS.conversations);
const AssetCenterPanel = lazy(PAGE_LOADERS.assets);
const AuditLogPanel = lazy(PAGE_LOADERS.audit);
const CodeWorkspacePanel = lazy(PAGE_LOADERS.code);
const ConnectorManagementPanel = lazy(PAGE_LOADERS.connectors);
const HumanCollaborationPanel = lazy(PAGE_LOADERS.human);
const ModelReportPanel = lazy(PAGE_LOADERS.report);
const MultiAgentCollaborationPanel = lazy(PAGE_LOADERS.agents);
const PredictionDemoPanel = lazy(PAGE_LOADERS.demo);
const QuotaManagementPanel = lazy(PAGE_LOADERS.quotas);
const RoutingPolicyPanel = lazy(PAGE_LOADERS.routing);
const TeamMembersPanel = lazy(PAGE_LOADERS.team);

const NAV_GROUPS = [
  { id: "main", label: "建模流程" },
];

const NAV_ITEMS = [
  { id: "tasks", pageId: "tasks", label: "开始建模", short: "1", group: "main", helper: "说清目标并上传数据", taskMode: "create" },
  { id: "taskQueue", pageId: "tasks", label: "我的任务", short: "2", group: "main", helper: "查看进度和历史", taskMode: "queue" },
  { id: "report", label: "结果报告", short: "3", group: "main", helper: "看懂模型结论" },
  { id: "human", label: "复核待办", short: "4", group: "main", helper: "确认关键节点" },
  { id: "team", label: "团队管理", short: "5", group: "main", helper: "成员与权限" },
];

const EXPERT_ITEMS = [
  { id: "agents", label: "运行详情", helper: "查看自动建模进度和日志", requiresDeveloper: true },
  { id: "code", label: "生成代码", helper: "查看和编辑本次生成的代码", requiresDeveloper: true },
  { id: "conversations", label: "AI 记录", helper: "查看任务 AI 对话记录", requiresDeveloper: true },
  { id: "demo", label: "试算一下", helper: "用模型试算一条数据", requiresDeveloper: true },
  { id: "usage", label: "使用记录", helper: "查看 AI 使用次数和明细", requiresAdmin: true },
  { id: "assets", label: "成果库", helper: "保存和复用团队成果", requiresDeveloper: true },
  { id: "connectors", label: "AI 设置", helper: "配置要使用的 AI 服务", requiresAdmin: true },
  { id: "routing", label: "默认 AI 设置", helper: "设置每一步默认用哪个 AI", requiresAdmin: true },
  { id: "quotas", label: "使用上限", helper: "管理成员可用额度", requiresAdmin: true },
  { id: "audit", label: "操作记录", helper: "查看团队重要操作", requiresAdmin: true },
  { id: "system", label: "系统状态", helper: "检查后端和 AI 是否可用", requiresAdmin: true },
];

const TASK_QUEUE_RENDER_LIMIT = 24;

function createEmptyTaskPolicy() {
  return {
    client_id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    stage: "requirement_analysis",
    trigger_mode: "before_run",
    assignee_type: "member",
    assignee_value: "",
    request_type: "requirement_review",
    title: "",
    summary: "",
    suggested_action: "",
    timeout_minutes: "",
  };
}

const EMPTY_TASK_FORM = {
  name: "",
  description: "",
  stage_routing: [
    { stage: "requirement_analysis", connector_id: "", model_name: "" },
    { stage: "data_analysis", connector_id: "", model_name: "" },
    { stage: "feature_engineering", connector_id: "", model_name: "" },
    { stage: "model_selection", connector_id: "", model_name: "" },
    { stage: "training_validation", connector_id: "", model_name: "" },
    { stage: "report_generation", connector_id: "", model_name: "" },
  ],
  interaction_policies: [],
};
const EMPTY_CONNECTOR_FORM = { display_name: "", endpoint_url: "", model_name: "", wire_api: "auto", api_key: "" };
const DEFAULT_RUN_TIME_LIMIT = null;

const TEAM_ROLE_LABELS = {
  team_owner: "团队所有者",
  admin: "管理员",
  business_user: "业务成员",
  developer_user: "开发成员",
  member: "成员",
};

function cn(...parts) { return parts.filter(Boolean).join(" "); }
function formatElapsedSeconds(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "暂无";
  if (value < 60) return `${Math.round(value)} 秒`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟`;
  return `${Math.round(value / 360) / 10} 小时`;
}
function getProgressTone(progress) {
  if (progress?.status === "blocked") return "warning";
  if (progress?.status === "repairing") return "info";
  if (progress?.stale || progress?.status === "stale") return "danger";
  if (progress?.status === "completed") return "success";
  if (progress?.status === "failed") return "danger";
  if (progress?.status === "running") return "info";
  return "warning";
}
function formatMetricValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}
function formatMetricName(name) { return formatCatalogMetricName(name); }
function combineTokenUsageReports(...reports) {
  const availableReports = reports.filter((report) => hasTokenUsage(report));
  if (!availableReports.length) return null;
  return availableReports.reduce(
    (combined, report) => ({
      input_tokens: combined.input_tokens + (Number.isFinite(report.input_tokens) ? report.input_tokens : 0),
      output_tokens: combined.output_tokens + (Number.isFinite(report.output_tokens) ? report.output_tokens : 0),
      total_tokens: combined.total_tokens + (Number.isFinite(report.total_tokens) ? report.total_tokens : 0),
      sessions: [],
      conversations: [],
    }),
    { input_tokens: 0, output_tokens: 0, total_tokens: 0, sessions: [], conversations: [] },
  );
}
function getTaskAnalysis(task) { return task?.structured_requirements && typeof task.structured_requirements === "object" ? task.structured_requirements : null; }
function getTaskAgentLoop(task) {
  const analysis = getTaskAnalysis(task);
  return analysis?.agent_loop && typeof analysis.agent_loop === "object" ? analysis.agent_loop : null;
}
function getTaskDatasetProfile(task) {
  const analysis = getTaskAnalysis(task);
  return task?.dataset_profile && typeof task.dataset_profile === "object"
    ? task.dataset_profile
    : analysis?.dataset_profile && typeof analysis.dataset_profile === "object"
      ? analysis.dataset_profile
      : null;
}
function getTaskConfidence(task) { const analysis = getTaskAnalysis(task); return typeof analysis?.confidence === "number" ? analysis.confidence : null; }
function formatConfidence(value) { return typeof value === "number" && !Number.isNaN(value) ? `${Math.round(value * 100)}%` : "暂无"; }
function formatRatio(value) { return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 1000) / 10}%` : "暂无"; }
function getTaskMetricName(task) {
  const analysis = getTaskAnalysis(task);
  if (typeof analysis?.metric_name === "string" && analysis.metric_name.trim()) return analysis.metric_name.trim();
  return task?.last_run?.metric_name ?? null;
}
function getRunMetricSummaryText(run) {
  if (!run) return "尚未运行";
  return `${formatMetricName(run.metric_name)}（${getMetricDirectionLabel(run.metric_name)}）：${formatMetricValue(run.metric_value)}`;
}
function getTaskRerunStage(task) {
  const humanLoop = task?.structured_requirements?.human_loop;
  if (!humanLoop || humanLoop.rerun_requested !== true) return null;
  const stage = typeof humanLoop.rerun_from_stage === "string" ? humanLoop.rerun_from_stage : "";
  return stage || null;
}
function getTaskRunAttempt(task) { return task?.last_run_attempt && typeof task.last_run_attempt === "object" ? task.last_run_attempt : null; }
function getTaskDiagnosticText(task, runProgress = null) {
  const attempt = getTaskRunAttempt(task);
  const parts = [attempt?.diagnosis, attempt?.diagnosis_detail].filter(Boolean);
  if (parts.length) return sanitizeRuntimeText(parts.join(" "));
  const readable = getReadableRuntimeActivity(runProgress);
  if (readable) return readable;
  if (task?.notes && !isRawRuntimeDebugText(task.notes)) return sanitizeRuntimeText(task.notes);
  return "";
}
function getRunErrorArtifactPath(task, runProgress = null) {
  return runProgress?.artifacts?.error_log_path || getTaskRunAttempt(task)?.error_artifact_path || "";
}
function getTaskAnalysisStepText(task, runProgress) {
  if (!task) return "等待任务";
  if (task.label_column && task.problem_type) return `预测目标 ${task.label_column} · ${formatProblemType(task.problem_type)}`;
  if (task.dataset_filename && ["running", "repairing", "blocked"].includes(runProgress?.status)) {
    const readable = getReadableRuntimeActivity(runProgress);
    return readable ? String(readable).slice(0, 34) : "等待系统给出解析结果";
  }
  if (task.dataset_filename) return formatTaskAnalysisStatus(task);
  return "等待 CSV";
}
function getTaskTrainingStepText(task, runProgress) {
  if (!task) return "等待运行";
  if (runProgress?.status === "blocked" || isRecoverableRunBlockedTask(task)) {
    const readable = getReadableRuntimeActivity(runProgress);
    return readable ? String(readable).slice(0, 42) : "自动处理受阻，等待重试";
  }
  if (runProgress?.status === "stale") return "疑似卡住，需要处理";
  if (runProgress?.status === "running" || runProgress?.status === "repairing") {
    const readable = getReadableRuntimeActivity(runProgress);
    if (readable) return String(readable).slice(0, 42);
    const candidateText = runProgress.completed_model_count != null || runProgress.total_model_count
      ? ` · 候选 ${runProgress.completed_model_count ?? 0}/${runProgress.total_model_count ?? "?"}`
      : "";
    if (runProgress.current_model) return `训练 ${runProgress.current_model}${candidateText}`;
    if (runProgress.current_iteration && runProgress.total_iterations) return `搜索轮次 ${runProgress.current_iteration}/${runProgress.total_iterations}`;
    if (runProgress.current_stage) return `当前阶段 ${formatWorkflowStage(runProgress.current_stage)}`;
    return "等待系统更新";
  }
  if (task.last_run) return getRunMetricSummaryText(task.last_run);
  if (task.status === "failed") return "运行失败，需要处理";
  return formatTaskStatus(task.status);
}
function getTaskRunButtonLabel(task, running) {
  if (running) return "自动建模中...";
  const rerunStage = getTaskRerunStage(task);
  if (rerunStage) return `从${formatWorkflowStage(rerunStage)}重跑`;
  return "开始自动建模";
}
function getTaskRunUsage(task) {
  const lastAttempt = getTaskRunAttempt(task);
  if (hasTokenUsage(lastAttempt?.token_usage)) return lastAttempt.token_usage;
  return hasTokenUsage(task?.last_run?.token_usage) ? task.last_run.token_usage : null;
}
function getTaskSummary(task) {
  if (!task?.label_column && !task?.problem_type) return "当前还没有拿到 AI 理解结果。";
  if (task?.label_column && task?.problem_type) return `预测目标 ${task.label_column}，问题类型 ${formatProblemType(task.problem_type)}。`;
  if (task?.label_column) return `已识别预测目标 ${task.label_column}，问题类型待补全。`;
  return `已识别问题类型 ${formatProblemType(task.problem_type)}，预测目标待补全。`;
}
function getTaskNextStep(task, runtimeStatus = task?.status) {
  if (!task) {
    return {
      tone: "info",
      title: "新建一个建模任务",
      body: "填写任务名称、业务描述并上传 CSV。",
      action: "提交需求并上传 CSV",
      page: "tasks",
    };
  }
  if (!task.dataset_filename) {
    return {
      tone: "warning",
      title: "补上传 CSV 数据集",
      body: "这个任务还没有数据文件，暂时不能进入 AI 理解和运行。",
      action: "选择 CSV 文件",
      page: "tasks",
    };
  }
  if (!task.label_column || !task.problem_type) {
    return {
      tone: "warning",
      title: "让 AI 理解数据和目标",
      body: "解析完成后，系统才能知道要预测什么、怎么训练模型。",
      action: "开始理解",
      page: "tasks",
    };
  }
  if (["paused_for_review", "waiting_human"].includes(task.status)) {
    return {
      tone: "warning",
      title: "处理人工复核待办",
      body: "任务正在等待人工确认、修改或恢复。",
      action: "打开复核待办",
      page: "human",
    };
  }
  if (runtimeStatus === "running") {
    return {
      tone: "info",
      title: "等待本次运行完成",
      body: "运行结束后会回写指标、候选模型和输出目录。",
      action: "查看任务进度",
      page: "tasks",
    };
  }
  if (runtimeStatus === "blocked") {
    const diagnosis = getTaskDiagnosticText(task);
    return {
      tone: "warning",
      title: "自动处理受阻",
      body: diagnosis || "本次运行遇到可恢复问题。重新运行会继续尝试处理。",
      action: "重新运行",
      page: "tasks",
    };
  }
  if (runtimeStatus === "stale") {
    const diagnosis = getTaskDiagnosticText(task);
    return {
      tone: "danger",
      title: "任务疑似卡住",
      body: diagnosis || "运行目录长时间没有更新，请先查看任务状态并联系管理员处理。",
      action: "查看任务状态",
      page: "tasks",
    };
  }
  if (task.status === "failed") {
    const diagnosis = getTaskDiagnosticText(task);
    return {
      tone: "danger",
      title: "查看失败原因或重新运行",
      body: diagnosis || "最近一次运行失败，系统已保留诊断信息。",
      action: "查看任务状态",
      page: "tasks",
    };
  }
  if (!task.last_run) {
    return {
      tone: "info",
      title: "开始自动训练模型",
      body: "AI 已经理解任务目标，可以开始自动建模。",
      action: "开始自动建模",
      page: "tasks",
    };
  }
  return {
    tone: "success",
    title: "查看结果报告",
    body: "模型结果已经回写，可以继续看报告并安排人工复核。",
    action: "打开模型报告",
    page: "report",
  };
}
function getTaskLifecycleSteps(task, runtimeStatus = task?.status) {
  const loopSteps = getTaskAgentLoop(task)?.workflow;
  if (Array.isArray(loopSteps) && loopSteps.length) {
    return loopSteps.map((step) => ({
      key: step.key,
      label: step.label,
      state: normalizeAgentLoopStepState(step.status, runtimeStatus),
      detail: step.detail,
    }));
  }
  return [
    { key: "task", label: "任务", state: task ? "done" : "active" },
    { key: "dataset", label: "数据", state: task?.dataset_filename ? "done" : task ? "active" : "pending" },
    { key: "analysis", label: "理解目标", state: task?.label_column && task?.problem_type ? "done" : task?.dataset_filename ? "active" : "pending" },
    { key: "run", label: "训练", state: runtimeStatus === "running" || runtimeStatus === "repairing" || runtimeStatus === "blocked" ? "active" : runtimeStatus === "stale" ? "danger" : task?.last_run ? "done" : runtimeStatus === "failed" ? "danger" : "pending" },
  ];
}
function normalizeAgentLoopStepState(status, runtimeStatus) {
  if (status === "completed" || status === "passed" || status === "accepted") return "done";
  if (status === "running" || status === "proposed") return "active";
  if (status === "blocked" || status === "failed") return "danger";
  if (status === "warning" || status === "needs_improvement") return "warning";
  if (runtimeStatus === "running" && status === "pending") return "pending";
  return "pending";
}
function getAgentLoopSummary(task) {
  const loop = getTaskAgentLoop(task);
  if (!loop) return null;
  const checklist = Array.isArray(loop.checklist) ? loop.checklist : [];
  const gates = Array.isArray(loop.quality_gates) ? loop.quality_gates : [];
  const attempts = Array.isArray(loop.tuning_attempts) ? loop.tuning_attempts : [];
  const blocked = checklist.filter((item) => item.status === "blocked").length + gates.filter((item) => item.status === "blocked").length;
  const warning = checklist.filter((item) => item.status === "warning").length + gates.filter((item) => item.status === "warning").length;
  return {
    checklistCount: checklist.length,
    blocked,
    warning,
    attemptCount: attempts.length,
    baseline: loop.baseline && typeof loop.baseline === "object" ? loop.baseline : null,
    nextImprovement: loop.next_improvement && typeof loop.next_improvement === "object" ? loop.next_improvement : null,
  };
}
function formatAgentMetric(metric) {
  if (!metric || metric.status !== "completed") return metric?.detail || "等待计算";
  return `${formatMetricName(metric.metric_name)}：${formatMetricValue(metric.metric_value)}`;
}
function getAgentLoopStatusTone(status) {
  if (status === "passed" || status === "completed" || status === "accepted") return "success";
  if (status === "blocked" || status === "failed") return "danger";
  if (status === "warning" || status === "proposed" || status === "needs_improvement") return "warning";
  return "info";
}
function getAgentLoopStatusLabel(status) {
  if (status === "passed" || status === "completed") return "通过";
  if (status === "accepted") return "采纳";
  if (status === "blocked") return "阻塞";
  if (status === "warning") return "需确认";
  if (status === "failed") return "失败";
  if (status === "proposed") return "建议";
  if (status === "pending") return "等待";
  return status || "未知";
}
function getAnalysisSourceLabel(task) {
  const source = getTaskAnalysis(task)?.analysis_source;
  if (!source) return "未标注";
  if (source === "ai_connector") return "当前 AI 配置";
  if (source === "human_correction") return "人工修正";
  return String(source);
}
function getTeamRoleLabel(role) { return TEAM_ROLE_LABELS[role] ?? role ?? "未识别角色"; }
function getNavItemPageId(item) { return item?.pageId ?? item?.id ?? "tasks"; }
function getTaskCreatedAtMs(task) {
  const value = task?.created_at ? new Date(task.created_at).getTime() : 0;
  return Number.isNaN(value) ? 0 : value;
}
function sortTasksForDisplay(items) {
  return [...(items ?? [])].sort((left, right) => {
    const createdDelta = getTaskCreatedAtMs(right) - getTaskCreatedAtMs(left);
    if (createdDelta !== 0) return createdDelta;
    return String(right?.id ?? "").localeCompare(String(left?.id ?? ""));
  });
}
function mergeTaskIntoList(items, nextTask) {
  const existingIndex = items.findIndex((task) => task.id === nextTask.id);
  if (existingIndex < 0) return sortTasksForDisplay([nextTask, ...items]);
  const nextItems = [...items];
  nextItems[existingIndex] = { ...items[existingIndex], ...nextTask };
  return nextItems;
}
function mergeConnectorIntoList(items, nextConnector) {
  const nextItems = items.map((item) => item.id === nextConnector.id ? nextConnector : nextConnector.is_active ? { ...item, is_active: false } : item);
  return nextItems.some((item) => item.id === nextConnector.id) ? nextItems : [nextConnector, ...nextItems];
}
function getUserLabel(user) { return user?.user_metadata?.display_name || user?.email || user?.id || ""; }
function buildTaskCreationMessage(task) {
  if (task.status === "paused_for_review") return "任务已创建，但需要人工确认后再继续。请先处理复核待办。";
  if (task.status === "waiting_human") return "任务已创建，当前正在等待人工确认。";
  if (task.status === "completed" && task.last_run) return `任务已创建、CSV 已上传，自动建模已完成。${getRunMetricSummaryText(task.last_run)}。`;
  if (isRecoverableRunBlockedTask(task)) return "任务已创建，系统遇到需要确认的问题，请在复核待办里处理。";
  if (task.status === "failed") return "任务已创建并自动进入工作流，但本次运行失败。请在任务状态中查看原因后再重试。";
  return task.label_column && task.problem_type
    ? "任务已创建，CSV 已上传，并且 AI 已完成任务解析；自动建模已启动。"
    : "任务已创建，CSV 已上传，但 AI 理解还未完成。请检查团队模型配置后重试。";
}
function translateServerMessage(message) {
  const lowered = message.toLowerCase();
  if (lowered.includes("agent 诊断")) return message.replace(/agent 诊断/gi, "诊断结论");
  if (lowered.includes("mlzero run failed") || lowered.includes("return code:") || lowered.includes("traceback")) {
    return "自动建模运行失败，系统已保留诊断结论；请在任务状态中查看后再决定是否重试。";
  }
  if (lowered.includes("invalid login credentials")) return "邮箱或密码不正确。";
  if (lowered.includes("user already registered")) return "这个邮箱已经注册过了，可以直接登录。";
  if (lowered.includes("invite code not found")) return "没有找到对应的邀请码。";
  if (lowered.includes("team name is required")) return "请先填写团队名称。";
  if (lowered.includes("dataset has not been uploaded")) return "请先上传 CSV 数据集。";
  if (lowered.includes("only csv uploads are supported")) return "目前只支持 CSV 文件。";
  if (lowered.includes("task not found")) return "没有找到对应任务。";
  if (lowered.includes("connector not found")) return "没有找到对应的 AI 设置。";
  if (lowered.includes("x-team-id header is required")) return "请先选择团队。";
  if (lowered.includes("you do not have access to the requested team")) return "你没有当前团队的访问权限。";
  if (lowered.includes("membership in the requested team is not active")) return "你在当前团队中的成员状态不是 active，暂时不能继续操作。";
  if (lowered.includes("missing supabase bearer token")) return "登录状态失效，请重新登录。";
  if (lowered.includes("requires a team admin role")) return "当前操作需要团队管理员权限。";
  if (lowered.includes("requires the team owner role")) return "当前操作需要团队所有者权限。";
  if (lowered.includes("only the current team owner can transfer ownership")) return "只有当前团队所有者可以转移所有权。";
  if (lowered.includes("team_owner must be assigned through the ownership transfer endpoint")) return "团队所有者只能通过所有权转移入口变更。";
  if (lowered.includes("team_owner cannot demote themselves")) return "团队所有者不能在成员表里降级自己，请使用所有权转移。";
  if (lowered.includes("requires a developer or team admin role")) return "当前操作需要开发成员或团队管理员权限。";
  if (lowered.includes("connector storage request")) return "AI 设置保存失败，请检查当前团队权限。";
  if (lowered.includes("governance request")) return "团队设置保存失败，请检查当前团队权限。";
  if (lowered.includes("waiting for human collaboration")) return "当前任务正在等待人工复核，请先处理复核请求或恢复任务。";
  if (lowered.includes("open human collaboration requests")) return "当前任务还有未处理的复核请求，请先处理。";
  if (lowered.includes("still in progress")) return "当前任务仍在运行中，暂时不能创建复核请求。";
  if (lowered.includes("quota")) return message;
  return message;
}
function getErrorMessage(error) { return error instanceof Error && error.message ? translateServerMessage(error.message) : `收到未知错误：${String(error)}`; }

function RouteLoading() {
  return <div className="empty-state">正在极速打开页面...</div>;
}

function RoutePane({ pageId, activePage, children }) {
  const isActive = activePage === pageId;
  if (!isActive) return null;
  return (
    <div className="route-pane active">
      {children}
    </div>
  );
}

export default function App() {
  const [activePage, setActivePage] = useState("tasks");
  const [health, setHealth] = useState(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState("");
  const [authMode, setAuthMode] = useState("login");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authMessage, setAuthMessage] = useState("");
  const [requiresEmailVerification, setRequiresEmailVerification] = useState(false);
  const [session, setSession] = useState(null);
  const [currentUser, setCurrentUser] = useState(null);
  const [memberships, setMemberships] = useState([]);
  const [activeTeamId, setActiveTeamId] = useState("");
  const [teamMembers, setTeamMembers] = useState([]);
  const [teamSettings, setTeamSettings] = useState(null);
  const [teamSettingsState, setTeamSettingsState] = useState("idle");
  const [teamSettingsSaving, setTeamSettingsSaving] = useState(false);
  const [ownershipTransferring, setOwnershipTransferring] = useState(false);
  const [teamBusy, setTeamBusy] = useState(false);
  const [teamError, setTeamError] = useState("");
  const [teamMessage, setTeamMessage] = useState("");
  const [tasks, setTasks] = useState([]);
  const [tasksState, setTasksState] = useState("idle");
  const [usageSummary, setUsageSummary] = useState(null);
  const [usageState, setUsageState] = useState("idle");
  const [usageError, setUsageError] = useState("");
  const [tokenLedgers, setTokenLedgers] = useState(null);
  const [tokenLedgerState, setTokenLedgerState] = useState("idle");
  const [tokenLedgerError, setTokenLedgerError] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");
  const [taskPanelMode, setTaskPanelMode] = useState("create");
  const [taskForm, setTaskForm] = useState(EMPTY_TASK_FORM);
  const [taskFile, setTaskFile] = useState(null);
  const [taskUploadToken, setTaskUploadToken] = useState(0);
  const [submittingTask, setSubmittingTask] = useState(false);
  const [runningTaskId, setRunningTaskId] = useState("");
  const [analyzingTaskId, setAnalyzingTaskId] = useState("");
  const [semanticSavingTaskId, setSemanticSavingTaskId] = useState("");
  const [deletingTaskId, setDeletingTaskId] = useState("");
  const [taskMessage, setTaskMessage] = useState("");
  const [taskError, setTaskError] = useState("");
  const [taskAIConversations, setTaskAIConversations] = useState(null);
  const [taskAIConversationsState, setTaskAIConversationsState] = useState("idle");
  const [taskAIConversationsError, setTaskAIConversationsError] = useState("");
  const [taskChatSubmitting, setTaskChatSubmitting] = useState(false);
  const [taskChatError, setTaskChatError] = useState("");
  const [taskModelReport, setTaskModelReport] = useState(null);
  const [taskModelReportState, setTaskModelReportState] = useState("idle");
  const [taskModelReportError, setTaskModelReportError] = useState("");
  const [taskRunProgress, setTaskRunProgress] = useState(null);
  const [taskRunProgressByTaskId, setTaskRunProgressByTaskId] = useState({});
  const [taskRunProgressState, setTaskRunProgressState] = useState("idle");
  const [taskRunProgressError, setTaskRunProgressError] = useState("");
  const [humanRequestPreset, setHumanRequestPreset] = useState(null);
  const [connectors, setConnectors] = useState([]);
  const [connectorsState, setConnectorsState] = useState("idle");
  const [connectorForm, setConnectorForm] = useState(EMPTY_CONNECTOR_FORM);
  const [savingConnector, setSavingConnector] = useState(false);
  const [testingConnectorId, setTestingConnectorId] = useState("");
  const [activatingConnectorId, setActivatingConnectorId] = useState("");
  const [updatingConnectorId, setUpdatingConnectorId] = useState("");
  const [deactivatingConnectorId, setDeactivatingConnectorId] = useState("");
  const [deletingConnectorId, setDeletingConnectorId] = useState("");
  const [healthCheckingConnectors, setHealthCheckingConnectors] = useState(false);
  const [connectorMessage, setConnectorMessage] = useState("");
  const [connectorError, setConnectorError] = useState("");
  const [inviteInfo, setInviteInfo] = useState(null);
  const [inviteBusy, setInviteBusy] = useState(false);
  const [roleUpdatingUserId, setRoleUpdatingUserId] = useState("");
  const [statusUpdatingUserId, setStatusUpdatingUserId] = useState("");
  const [quotaSummary, setQuotaSummary] = useState([]);
  const [quotaState, setQuotaState] = useState("idle");
  const [quotaError, setQuotaError] = useState("");
  const [quotaMessage, setQuotaMessage] = useState("");
  const [quotaSavingKey, setQuotaSavingKey] = useState("");
  const [routingPolicies, setRoutingPolicies] = useState([]);
  const [routingState, setRoutingState] = useState("idle");
  const [routingError, setRoutingError] = useState("");
  const [routingMessage, setRoutingMessage] = useState("");
  const [routingSaving, setRoutingSaving] = useState(false);
  const [assetItems, setAssetItems] = useState([]);
  const [assetState, setAssetState] = useState("idle");
  const [assetError, setAssetError] = useState("");
  const [assetMessage, setAssetMessage] = useState("");
  const [assetCreating, setAssetCreating] = useState(false);
  const [assetReviewingId, setAssetReviewingId] = useState("");
  const [assetPublishingId, setAssetPublishingId] = useState("");
  const [assetForkingId, setAssetForkingId] = useState("");
  const [auditLogs, setAuditLogs] = useState([]);
  const [auditState, setAuditState] = useState("idle");
  const [auditError, setAuditError] = useState("");

  const requestContext = useMemo(() => ({ accessToken: session?.access_token, teamId: activeTeamId || undefined }), [activeTeamId, session]);
  const activeTeam = useMemo(() => memberships.find((item) => item.id === activeTeamId) ?? null, [activeTeamId, memberships]);
  const selectedTask = useMemo(() => tasks.find((task) => task.id === selectedTaskId) ?? tasks[0] ?? null, [selectedTaskId, tasks]);
  const activeConnector = useMemo(() => connectors.find((connector) => connector.is_active) ?? null, [connectors]);
  const teamCanManage = useMemo(() => ["admin", "team_owner"].includes(activeTeam?.role ?? ""), [activeTeam?.role]);
  const teamCanDevelop = useMemo(() => ["team_owner", "admin", "developer_user"].includes(activeTeam?.role ?? ""), [activeTeam?.role]);
  const teamCanOwn = useMemo(() => activeTeam?.role === "team_owner", [activeTeam?.role]);
  const visibleNavItems = useMemo(
    () => NAV_ITEMS.filter((item) => {
      const canSeeByRole = (!item.requiresAdmin || teamCanManage) && (!item.requiresDeveloper || teamCanDevelop);
      return canSeeByRole;
    }),
    [teamCanDevelop, teamCanManage],
  );
  const visibleExpertItems = useMemo(
    () => EXPERT_ITEMS.filter((item) => {
      const canSeeByRole = (!item.requiresAdmin || teamCanManage) && (!item.requiresDeveloper || teamCanDevelop);
      return canSeeByRole;
    }),
    [teamCanDevelop, teamCanManage],
  );
  const activeNavItem = useMemo(
    () => (activePage === "tasks" && taskPanelMode === "detail"
      ? { label: "任务进度", helper: "查看当前建模状态" }
      : visibleNavItems.find((item) => getNavItemPageId(item) === activePage && item.taskMode === taskPanelMode))
      ?? visibleExpertItems.find((item) => item.id === activePage)
      ?? visibleNavItems.find((item) => item.id === activePage)
      ?? visibleNavItems.find((item) => getNavItemPageId(item) === activePage)
      ?? visibleNavItems[0]
      ?? null,
    [activePage, taskPanelMode, visibleExpertItems, visibleNavItems],
  );
  const completedTaskCount = useMemo(() => tasks.filter((task) => task.status === "completed" || task.last_run).length, [tasks]);
  const waitingTaskCount = useMemo(() => tasks.filter((task) => ["paused_for_review", "waiting_human"].includes(task.status)).length, [tasks]);
  const selectedTaskRunProgress = useMemo(
    () => (selectedTask?.id ? taskRunProgressByTaskId[selectedTask.id] ?? taskRunProgress : null),
    [selectedTask?.id, taskRunProgress, taskRunProgressByTaskId],
  );
  const runningTaskProgressIds = useMemo(
    () => tasks
      .filter((task) => task.status === "running" || isRecoverableRunBlockedTask(task))
      .map((task) => task.id)
      .slice(0, 4),
    [tasks],
  );
  const workspaceNextStep = useMemo(
    () => getTaskNextStep(selectedTask, getTaskRuntimeStatus(selectedTask, selectedTaskRunProgress)),
    [selectedTask, selectedTaskRunProgress],
  );

  async function loadHealth() {
    setHealthLoading(true);
    setHealthError("");
    try { setHealth(await api.health()); } catch (error) { setHealthError(getErrorMessage(error)); } finally { setHealthLoading(false); }
  }

  async function loadMemberships(preferredTeamId) {
    if (!supabase || !session?.user) {
      setMemberships([]);
      setActiveTeamId("");
      return;
    }

    setTeamBusy(true);
    setTeamError("");

    try {
      const { data: membershipRows, error: membershipError } = await supabase
        .from("team_members")
        .select("team_id, role, member_status, joined_at")
        .eq("user_id", session.user.id)
        .in("member_status", ["active", "invited"])
        .order("joined_at", { ascending: true });
      if (membershipError) throw membershipError;
      if (!membershipRows?.length) {
        setMemberships([]);
        setActiveTeamId("");
        setTeamMembers([]);
        setTeamSettings(null);
        setTeamSettingsState("idle");
        return;
      }

      const teamIds = membershipRows.map((row) => row.team_id);
      const { data: teamRows, error: teamRowsError } = await supabase.from("teams").select("id, name, invite_code, created_by, description, status, created_at, updated_at").in("id", teamIds);
      if (teamRowsError) throw teamRowsError;
      const teamMap = new Map((teamRows ?? []).map((team) => [team.id, team]));
      const nextMemberships = membershipRows.map((row) => ({
        id: row.team_id,
        role: row.role,
        member_status: row.member_status,
        joined_at: row.joined_at,
        name: teamMap.get(row.team_id)?.name ?? row.team_id,
        invite_code: teamMap.get(row.team_id)?.invite_code ?? "",
        created_by: teamMap.get(row.team_id)?.created_by ?? "",
        description: teamMap.get(row.team_id)?.description ?? "",
        status: teamMap.get(row.team_id)?.status ?? "active",
        created_at: teamMap.get(row.team_id)?.created_at ?? row.joined_at,
        updated_at: teamMap.get(row.team_id)?.updated_at ?? row.joined_at,
      }));
      setMemberships(nextMemberships);
      setActiveTeamId((current) => {
        if (preferredTeamId && nextMemberships.some((item) => item.id === preferredTeamId)) return preferredTeamId;
        if (current && nextMemberships.some((item) => item.id === current)) return current;
        return nextMemberships[0]?.id ?? "";
      });
    } catch (error) {
      setTeamError(getErrorMessage(error));
    } finally {
      setTeamBusy(false);
    }
  }

  async function loadTeamMembers(teamId = activeTeamId) {
    if (!session?.access_token || !teamId) {
      setTeamMembers([]);
      return;
    }
    setTeamBusy(true);
    try {
      const response = await api.teamMembers({ accessToken: session.access_token, teamId });
      setTeamMembers(response.items ?? []);
    } catch (error) {
      setTeamError(getErrorMessage(error));
    } finally {
      setTeamBusy(false);
    }
  }

  async function loadTeamSettings(teamId = activeTeamId) {
    if (!session?.access_token || !teamId) {
      setTeamSettings(null);
      setTeamSettingsState("idle");
      return;
    }
    setTeamSettingsState("loading");
    try {
      const response = await api.teamSettings({ accessToken: session.access_token, teamId });
      setTeamSettings(response.team ?? null);
    } catch (error) {
      setTeamError(getErrorMessage(error));
      setTeamSettings(null);
    } finally {
      setTeamSettingsState("ready");
    }
  }

  async function loadTasks() {
    if (!session?.access_token || !activeTeamId) {
      setTasks([]);
      return;
    }
    setTasksState("loading");
    try { setTasks(sortTasksForDisplay((await api.listTasks(requestContext)).items ?? [])); } catch (error) { setTaskError(getErrorMessage(error)); } finally { setTasksState("ready"); }
  }

  async function loadTaskAIConversations(taskId = selectedTask?.id) {
    if (!session?.access_token || !activeTeamId || !taskId) {
      setTaskAIConversations(null);
      setTaskAIConversationsState("idle");
      setTaskAIConversationsError("");
      return;
    }
    setTaskAIConversationsState("loading");
    setTaskAIConversationsError("");
    try {
      setTaskAIConversations(await api.taskAIConversations(taskId, requestContext));
    } catch (error) {
      setTaskAIConversations(null);
      setTaskAIConversationsError(getErrorMessage(error));
    } finally {
      setTaskAIConversationsState("ready");
    }
  }

  async function loadTaskModelReport(taskId = selectedTask?.id) {
    if (!session?.access_token || !activeTeamId || !taskId) {
      setTaskModelReport(null);
      setTaskModelReportState("idle");
      setTaskModelReportError("");
      return;
    }
    setTaskModelReportState("loading");
    setTaskModelReportError("");
    try {
      setTaskModelReport(await api.taskModelReport(taskId, requestContext));
    } catch (error) {
      setTaskModelReport(null);
      setTaskModelReportError(getErrorMessage(error));
    } finally {
      setTaskModelReportState("ready");
    }
  }

  async function loadTaskRunProgress(taskId = selectedTask?.id, options = {}) {
    const { background = false, silent = false } = options;
    if (!session?.access_token || !activeTeamId || !taskId) {
      setTaskRunProgress(null);
      if (!background) setTaskRunProgressByTaskId({});
      setTaskRunProgressState("idle");
      setTaskRunProgressError("");
      return null;
    }
    if (!background) setTaskRunProgressState((current) => current === "ready" ? "refreshing" : "loading");
    setTaskRunProgressError("");
    try {
      const progress = await api.taskRunProgress(taskId, requestContext);
      if (!background) setTaskRunProgress(progress);
      setTaskRunProgressByTaskId((current) => ({ ...current, [taskId]: progress }));
      if (progress?.task?.id) {
        setTasks((current) => mergeTaskIntoList(current, progress.task));
        if (progress.repaired && !silent) {
          setTaskMessage("检测到任务长时间无更新，已标记为需要处理，并保留诊断信息。");
        }
      }
      return progress;
    } catch (error) {
      setTaskRunProgressError(getErrorMessage(error));
      return null;
    } finally {
      if (!background) setTaskRunProgressState("ready");
    }
  }

  async function loadUsageSummary() {
    if (!session?.access_token || !activeTeamId) {
      setUsageSummary(null);
      setUsageState("idle");
      return;
    }
    setUsageState("loading");
    setUsageError("");
    try {
      setUsageSummary(await api.usageSummary(requestContext));
    } catch (error) {
      setUsageError(getErrorMessage(error));
    } finally {
      setUsageState("ready");
    }
  }

  async function loadTokenLedgers() {
    if (!session?.access_token || !activeTeamId || !teamCanManage) {
      setTokenLedgers(null);
      setTokenLedgerState("idle");
      setTokenLedgerError("");
      return;
    }
    setTokenLedgerState("loading");
    setTokenLedgerError("");
    try {
      setTokenLedgers(await api.teamTokenLedgers({ limit: 500 }, requestContext));
    } catch (error) {
      setTokenLedgerError(getErrorMessage(error));
    } finally {
      setTokenLedgerState("ready");
    }
  }

  async function loadConnectors() {
    if (!session?.access_token || !activeTeamId) {
      setConnectors([]);
      return;
    }
    setConnectorsState("loading");
    try { setConnectors((await api.listConnectors(requestContext)).items ?? []); } catch (error) { setConnectorError(getErrorMessage(error)); } finally { setConnectorsState("ready"); }
  }

  async function loadQuotaSummary() {
    if (!session?.access_token || !activeTeamId || !teamCanManage) {
      setQuotaSummary([]);
      setQuotaState("idle");
      setQuotaError("");
      return;
    }
    setQuotaState("loading");
    setQuotaError("");
    try {
      setQuotaSummary((await api.teamQuotas(requestContext)).items ?? []);
    } catch (error) {
      setQuotaError(getErrorMessage(error));
    } finally {
      setQuotaState("ready");
    }
  }

  async function loadRoutingPolicies() {
    if (!session?.access_token || !activeTeamId) {
      setRoutingPolicies([]);
      setRoutingState("idle");
      setRoutingError("");
      return;
    }
    setRoutingState("loading");
    setRoutingError("");
    try {
      setRoutingPolicies((await api.teamRouting(requestContext)).items ?? []);
    } catch (error) {
      setRoutingError(getErrorMessage(error));
    } finally {
      setRoutingState("ready");
    }
  }

  async function loadAssets() {
    if (!session?.access_token || !activeTeamId) {
      setAssetItems([]);
      setAssetState("idle");
      setAssetError("");
      return;
    }
    setAssetState("loading");
    setAssetError("");
    try {
      setAssetItems((await api.teamAssets(undefined, requestContext)).items ?? []);
    } catch (error) {
      setAssetError(getErrorMessage(error));
    } finally {
      setAssetState("ready");
    }
  }

  async function loadAuditLogs() {
    if (!session?.access_token || !activeTeamId || !teamCanManage) {
      setAuditLogs([]);
      setAuditState("idle");
      setAuditError("");
      return;
    }
    setAuditState("loading");
    setAuditError("");
    try {
      setAuditLogs((await api.teamAuditLogs(requestContext)).items ?? []);
    } catch (error) {
      setAuditError(getErrorMessage(error));
    } finally {
      setAuditState("ready");
    }
  }

  function warmPage(pageId) {
    preloadPageComponent(pageId);
  }

  function openNavItem(item) {
    const nextPageId = getNavItemPageId(item);
    if (item.taskMode) setTaskPanelMode(item.taskMode);
    warmPage(nextPageId);
    setActivePage(nextPageId);
  }

  function openExpertPage(pageId) {
    if (!pageId) return;
    warmPage(pageId);
    setActivePage(pageId);
  }

  function isNavItemActive(item) {
    const itemPageId = getNavItemPageId(item);
    if (activePage === "tasks" && taskPanelMode === "detail") return item.taskMode === "queue";
    if (item.taskMode) return activePage === itemPageId && taskPanelMode === item.taskMode;
    return activePage === item.id;
  }

  async function refreshWorkspaceData() {
    if (activePage === "system") return loadHealth();
    if (activePage === "tasks") return loadTasks();
    if (activePage === "agents") return selectedTask?.id ? Promise.allSettled([loadTaskRunProgress(selectedTask.id), loadTasks()]) : loadTasks();
    if (activePage === "usage") return Promise.allSettled([loadUsageSummary(), loadTokenLedgers()]);
    if (activePage === "quotas") return loadQuotaSummary();
    if (activePage === "routing") return loadRoutingPolicies();
    if (activePage === "assets") return loadAssets();
    if (activePage === "audit") return loadAuditLogs();
    if (activePage === "team") return Promise.allSettled([loadTeamMembers(), loadTeamSettings()]);
    if (activePage === "conversations") return loadTaskAIConversations();
    if (activePage === "report") return loadTaskModelReport();
    if (activePage === "connectors") return loadConnectors();
    return loadTasks();
  }

  async function refreshActiveTaskHeavyData(taskId) {
    const loaders = [];
    if (activePage === "usage") loaders.push(loadUsageSummary, loadTokenLedgers);
    if (activePage === "conversations" && taskId) loaders.push(() => loadTaskAIConversations(taskId));
    if (activePage === "report" && taskId) loaders.push(() => loadTaskModelReport(taskId));
    if ((activePage === "tasks" || activePage === "agents") && taskId) loaders.push(() => loadTaskRunProgress(taskId));
    if (!loaders.length) return;
    await Promise.allSettled(loaders.map((loader) => loader()));
  }

  useEffect(() => {
    void loadHealth();
    if (!supabaseReady || !supabase) return undefined;
    let active = true;

    async function bootstrapAuth() {
      try {
        const settings = await readSupabaseAuthSettings();
        if (active && settings) setRequiresEmailVerification(Boolean(settings.mailer_autoconfirm === false));
      } catch {
        // Ignore auth settings fetch failures.
      }
      const { data, error } = await supabase.auth.getSession();
      if (!active) return;
      if (error) {
        setAuthError(getErrorMessage(error));
        return;
      }
      setSession(data.session ?? null);
      setCurrentUser(data.session?.user ?? null);
    }

    void bootstrapAuth();
    const { data: authSubscription } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession ?? null);
      setCurrentUser(nextSession?.user ?? null);
      setAuthError("");
      if (!nextSession) {
        setMemberships([]);
        setActiveTeamId("");
        setTeamMembers([]);
        setTeamSettings(null);
        setTeamSettingsState("idle");
        setTasks([]);
        setTaskAIConversations(null);
        setTaskAIConversationsState("idle");
        setTaskAIConversationsError("");
        setTaskModelReport(null);
        setTaskModelReportState("idle");
        setTaskModelReportError("");
        setUsageSummary(null);
        setUsageState("idle");
        setUsageError("");
        setTokenLedgers(null);
        setTokenLedgerState("idle");
        setTokenLedgerError("");
        setConnectors([]);
        setInviteInfo(null);
        setQuotaSummary([]);
        setQuotaState("idle");
        setQuotaError("");
        setRoutingPolicies([]);
        setRoutingState("idle");
        setRoutingError("");
        setAssetItems([]);
        setAssetState("idle");
        setAssetError("");
        setAuditLogs([]);
        setAuditState("idle");
        setAuditError("");
      }
    });

    return () => {
      active = false;
      authSubscription.subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (session?.user) void loadMemberships();
  }, [session?.user?.id]);

  useEffect(() => {
    if (!activeTeamId) {
      setTasks([]);
      setTaskAIConversations(null);
      setTaskAIConversationsState("idle");
      setTaskAIConversationsError("");
      setTaskModelReport(null);
      setTaskModelReportState("idle");
      setTaskModelReportError("");
      setUsageSummary(null);
      setUsageState("idle");
      setUsageError("");
      setTokenLedgers(null);
      setTokenLedgerState("idle");
      setTokenLedgerError("");
      setConnectors([]);
      setTeamMembers([]);
      setTeamSettings(null);
      setTeamSettingsState("idle");
      setInviteInfo(null);
      setQuotaSummary([]);
      setQuotaState("idle");
      setQuotaError("");
      setRoutingPolicies([]);
      setRoutingState("idle");
      setRoutingError("");
      setAssetItems([]);
      setAssetState("idle");
      setAssetError("");
      setAuditLogs([]);
      setAuditState("idle");
      setAuditError("");
      return;
    }
    setTeamMembers([]);
    setTeamSettings(null);
    setTeamSettingsState("idle");
    setInviteInfo(null);
    void Promise.all([
      loadTasks(),
      loadConnectors(),
    ]);
  }, [activeTeamId, session?.access_token, teamCanManage]);

  useEffect(() => {
    if (!activeTeamId || !session?.access_token) return;
    if (activePage === "usage") void Promise.all([loadUsageSummary(), loadTokenLedgers()]);
    if (activePage === "quotas") void loadQuotaSummary();
    if (activePage === "routing") void loadRoutingPolicies();
    if (activePage === "assets") void loadAssets();
    if (activePage === "audit") void loadAuditLogs();
    if (activePage === "team") void Promise.all([loadTeamMembers(), loadTeamSettings()]);
  }, [activePage, activeTeamId, session?.access_token, teamCanManage]);

  useEffect(() => {
    if (!tasks.length) {
      setSelectedTaskId("");
      return;
    }
    if (!tasks.some((task) => task.id === selectedTaskId)) setSelectedTaskId(tasks[0].id);
  }, [selectedTaskId, tasks]);

  useEffect(() => {
    const visiblePageIds = new Set([
      ...visibleNavItems.map((item) => getNavItemPageId(item)),
      ...visibleExpertItems.map((item) => item.id),
    ]);
    if (!visiblePageIds.has(activePage)) {
      setActivePage(getNavItemPageId(visibleNavItems[0]) ?? "tasks");
    }
  }, [activePage, visibleExpertItems, visibleNavItems]);

  useEffect(() => {
    setTaskChatError("");
    setTaskRunProgress(null);
    setTaskRunProgressError("");
    setTaskRunProgressState("idle");
  }, [selectedTask?.id]);

  useEffect(() => {
    if (!selectedTask?.id || !session?.access_token || !activeTeamId) {
      setTaskRunProgress(null);
      setTaskRunProgressState("idle");
      setTaskRunProgressError("");
      return undefined;
    }
    const runRequestInFlight = runningTaskId === selectedTask.id;
    const shouldInspect = activePage === "agents"
      || (activePage === "tasks" && taskPanelMode === "detail")
      || runRequestInFlight;
    if (!shouldInspect) return undefined;

    let active = true;
    const refresh = async (options = {}) => {
      if (!active) return;
      await loadTaskRunProgress(selectedTask.id, options);
    };
    void refresh();
    if (selectedTask.status !== "running" && !runRequestInFlight) {
      return () => { active = false; };
    }
    const intervalId = window.setInterval(() => {
      void refresh({ background: true, silent: true });
    }, 10000);
    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [
    activePage,
    activeTeamId,
    taskPanelMode,
    selectedTask?.id,
    selectedTask?.status,
    selectedTask?.last_run_attempt?.output_dir,
    selectedTask?.last_run?.output_dir,
    runningTaskId,
    session?.access_token,
  ]);

  useEffect(() => {
    if (!["tasks", "agents"].includes(activePage)) return undefined;
    if (!session?.access_token || !activeTeamId || !runningTaskProgressIds.length) return undefined;
    let active = true;
    const refreshLiveTasks = async () => {
      if (!active) return;
      await Promise.allSettled(
        runningTaskProgressIds.map((taskId) => loadTaskRunProgress(taskId, {
          background: true,
          silent: taskId !== selectedTask?.id,
        })),
      );
    };
    void refreshLiveTasks();
    const intervalId = window.setInterval(() => {
      void refreshLiveTasks();
    }, 10000);
    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [activePage, activeTeamId, runningTaskProgressIds.join("|"), selectedTask?.id, session?.access_token]);

  useEffect(() => {
    if (activePage !== "conversations") return;
    if (!selectedTask?.id || !session?.access_token || !activeTeamId) {
      setTaskAIConversations(null);
      setTaskAIConversationsState("idle");
      setTaskAIConversationsError("");
      return;
    }
    if (taskAIConversationsState === "loading") return;
    if (taskAIConversationsState === "ready" && taskAIConversations?.task_id === selectedTask.id) return;
    void loadTaskAIConversations(selectedTask.id);
  }, [
    activePage,
    activeTeamId,
    selectedTask?.id,
    selectedTask?.updated_at,
    selectedTask?.last_run?.output_dir,
    selectedTask?.last_run_attempt?.output_dir,
    session?.access_token,
  ]);

  useEffect(() => {
    if (activePage !== "report") return;
    if (!selectedTask?.id || !session?.access_token || !activeTeamId) {
      setTaskModelReport(null);
      setTaskModelReportState("idle");
      setTaskModelReportError("");
      return;
    }
    if (taskModelReportState === "loading") return;
    if (taskModelReportState === "ready" && taskModelReport?.task_id === selectedTask.id) return;
    void loadTaskModelReport(selectedTask.id);
  }, [
    activePage,
    activeTeamId,
    selectedTask?.id,
    selectedTask?.updated_at,
    selectedTask?.last_run?.output_dir,
    selectedTask?.last_run_attempt?.output_dir,
    session?.access_token,
  ]);

  async function handleLogin(form) {
    if (!supabase) return;
    setAuthBusy(true);
    setAuthError("");
    setAuthMessage("");
    try {
      const { error } = await supabase.auth.signInWithPassword({ email: form.email.trim(), password: form.password });
      if (error) throw error;
      setAuthMessage("登录成功。");
    } catch (error) {
      setAuthError(getErrorMessage(error));
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleRegister(form) {
    if (!supabase) return;
    setAuthBusy(true);
    setAuthError("");
    setAuthMessage("");
    try {
      const { data, error } = await supabase.auth.signUp({ email: form.email.trim(), password: form.password, options: { data: { display_name: form.displayName.trim() } } });
      if (error) throw error;
      setAuthMessage(data.session ? "注册成功，已自动登录。" : "注册成功。当前项目仍要求邮箱验证，请按邮箱提示完成验证后再登录。");
    } catch (error) {
      setAuthError(getErrorMessage(error));
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleLogout() {
    if (!supabase) return;
    await supabase.auth.signOut();
    setAuthMessage("");
    setTeamMessage("");
    setTaskMessage("");
    setConnectorMessage("");
    setQuotaMessage("");
    setRoutingMessage("");
    setAssetMessage("");
  }

  async function handleCreateTeam(teamName) {
    if (!supabase) return;
    setTeamBusy(true);
    setTeamError("");
    setTeamMessage("");
    try {
      const { data, error } = await supabase.rpc("create_team_with_owner", { team_name: teamName.trim() });
      if (error) throw error;
      await loadMemberships(typeof data === "string" ? data : undefined);
      setTeamMessage("团队已创建，你现在是该团队的管理员。");
    } catch (error) {
      setTeamError(getErrorMessage(error));
    } finally {
      setTeamBusy(false);
    }
  }

  async function handleJoinTeam(teamCode) {
    if (!supabase) return;
    setTeamBusy(true);
    setTeamError("");
    setTeamMessage("");
    try {
      const { data, error } = await supabase.rpc("join_team_with_code", { team_code: teamCode.trim().toUpperCase() });
      if (error) throw error;
      await loadMemberships(typeof data === "string" ? data : undefined);
      setTeamMessage("已加入团队。");
    } catch (error) {
      setTeamError(getErrorMessage(error));
    } finally {
      setTeamBusy(false);
    }
  }

  function handleTaskFormFieldChange(field, value) {
    setTaskForm((current) => ({ ...current, [field]: value }));
  }

  function handleTaskStageRoutingChange(stage, field, value) {
    setTaskForm((current) => ({
      ...current,
      stage_routing: current.stage_routing.map((item) => (
        item.stage === stage
          ? {
              ...item,
              [field]: value,
              model_name: field === "connector_id" && !value ? "" : item.model_name,
            }
          : item
      )),
    }));
  }

  function handleAddTaskPolicy() {
    setTaskForm((current) => ({
      ...current,
      interaction_policies: [...current.interaction_policies, createEmptyTaskPolicy()],
    }));
  }

  function handleTaskPolicyChange(index, field, value) {
    setTaskForm((current) => ({
      ...current,
      interaction_policies: current.interaction_policies.map((item, currentIndex) => (
        currentIndex === index ? { ...item, [field]: value } : item
      )),
    }));
  }

  function handleRemoveTaskPolicy(index) {
    setTaskForm((current) => ({
      ...current,
      interaction_policies: current.interaction_policies.filter((_, currentIndex) => currentIndex !== index),
    }));
  }

  async function handleTaskSubmit(event) {
    event.preventDefault();
    if (!activeTeamId) return setTaskError("请先选择团队。");
    if (!taskFile) return setTaskError("请先选择 CSV 文件。");
    const modelOnlyRoute = (taskForm.stage_routing ?? []).find((item) => item.model_name?.trim() && !item.connector_id);
    if (modelOnlyRoute) {
      return setTaskError("高级设置里不能只填写模型名；请同时选择可用模型配置，或清空该项。");
    }
    setSubmittingTask(true);
    setTaskError("");
    setTaskMessage("");
    let createdTaskId = "";
    try {
      const fallbackTaskName = taskForm.name.trim()
        || taskFile?.name?.replace(/\.csv$/i, "").trim()
        || taskForm.description.trim().slice(0, 24)
        || "未命名建模任务";
      const createdTask = await api.createTask({
        name: fallbackTaskName,
        description: taskForm.description.trim(),
        stage_routing: (taskForm.stage_routing ?? [])
          .filter((item) => item.connector_id)
          .map((item) => ({
            stage: item.stage,
            connector_id: item.connector_id || null,
            model_name: item.connector_id ? item.model_name?.trim() || null : null,
          })),
        interaction_policies: (taskForm.interaction_policies ?? [])
          .map((item, index) => ({
            policy_id: item.policy_id || `task-policy-${index + 1}`,
            enabled: true,
            stage: item.stage,
            trigger_mode: item.trigger_mode,
            assignee_type: item.assignee_type,
            assignee_value: item.assignee_value.trim(),
            request_type: item.request_type,
            title: item.title.trim(),
            summary: item.summary.trim(),
            suggested_action: item.suggested_action?.trim() || null,
            timeout_minutes: item.timeout_minutes ? Number.parseInt(item.timeout_minutes, 10) || null : null,
            artifact_paths: [],
          }))
          .filter((item) => item.assignee_value && item.title && item.summary),
      }, requestContext);
      createdTaskId = createdTask.id;
      setTasks((current) => mergeTaskIntoList(current, createdTask));
      setSelectedTaskId(createdTask.id);
      setTaskPanelMode("queue");
      setAnalyzingTaskId(createdTask.id);
      setTaskMessage("任务已创建，正在上传 CSV 并让 AI 理解需求。");
      const uploadedTask = await api.uploadDataset(createdTask.id, taskFile, requestContext, {
        autoRun: false,
        timeLimit: DEFAULT_RUN_TIME_LIMIT,
      });
      setTasks((current) => mergeTaskIntoList(current, uploadedTask));
      setSelectedTaskId(uploadedTask.id);
      setTaskForm(EMPTY_TASK_FORM);
      setTaskFile(null);
      setTaskUploadToken((current) => current + 1);
      void refreshActiveTaskHeavyData(uploadedTask.id);
      setTaskMessage(`${buildTaskCreationMessage(uploadedTask)} 已开始自动建模，你可以在“我的任务”里查看进度。`);
      void handleRunTask(uploadedTask.id);
    } catch (error) {
      await Promise.allSettled([loadTasks(), refreshActiveTaskHeavyData(createdTaskId)]);
      if (createdTaskId) setSelectedTaskId(createdTaskId);
      setTaskError(getErrorMessage(error));
    } finally {
      setAnalyzingTaskId((current) => current === createdTaskId ? "" : current);
      setSubmittingTask(false);
    }
  }

  async function handleAnalyzeTask(taskId) {
    setAnalyzingTaskId(taskId);
    setTaskError("");
    setTaskMessage("");
    try {
      const updatedTask = await api.analyzeTask(taskId, requestContext);
      setTasks((current) => mergeTaskIntoList(current, updatedTask));
      setSelectedTaskId(updatedTask.id);
      void refreshActiveTaskHeavyData(updatedTask.id);
      setTaskMessage(`任务“${updatedTask.name}”已重新完成 AI 理解。`);
    } catch (error) {
      await Promise.allSettled([loadTasks(), refreshActiveTaskHeavyData(taskId)]);
      setTaskError(getErrorMessage(error));
    } finally {
      setAnalyzingTaskId("");
    }
  }

  async function handleUpdateTaskSemantics(event, task) {
    event.preventDefault();
    if (!task?.id) return;
    const formData = new FormData(event.currentTarget);
    const payload = {
      label_column: String(formData.get("label_column") ?? "").trim(),
      problem_type: String(formData.get("problem_type") ?? "").trim(),
      metric_name: String(formData.get("metric_name") ?? "").trim(),
      correction_note: String(formData.get("correction_note") ?? "").trim() || null,
    };
    if (!payload.label_column || !payload.problem_type || !payload.metric_name) {
      setTaskError("请完整填写预测目标、问题类型和评估指标。");
      return;
    }
    setSemanticSavingTaskId(task.id);
    setTaskError("");
    setTaskMessage("");
    try {
      const updatedTask = await api.updateTaskSemantics(task.id, payload, requestContext);
      setTasks((current) => mergeTaskIntoList(current, updatedTask));
      setSelectedTaskId(updatedTask.id);
      void refreshActiveTaskHeavyData(updatedTask.id);
      setTaskMessage("任务语义已人工修正，旧运行结果已从当前任务状态中移除。请重新自动建模生成新的真实结果。");
    } catch (error) {
      await Promise.allSettled([loadTasks(), refreshActiveTaskHeavyData(task.id)]);
      setTaskError(getErrorMessage(error));
    } finally {
      setSemanticSavingTaskId("");
    }
  }

  async function handleRunTask(taskId) {
    setRunningTaskId(taskId);
    setTaskError("");
    setTaskMessage("自动建模已启动，正在读取真实进度。");
    setTaskRunProgressError("");
    setTasks((current) => current.map((task) => (
      task.id === taskId
        ? { ...task, status: "running", notes: "自动建模正在运行，正在读取真实进度。" }
        : task
    )));
    setSelectedTaskId(taskId);
    try {
      const updatedTask = await api.runTask(taskId, DEFAULT_RUN_TIME_LIMIT, requestContext);
      setTasks((current) => mergeTaskIntoList(current, updatedTask));
      setSelectedTaskId(updatedTask.id);
      void refreshActiveTaskHeavyData(updatedTask.id);
      if (updatedTask.status === "paused_for_review") {
        setTaskMessage("任务已根据人工确认设置自动暂停，等待处理复核待办。");
      } else if (isRecoverableRunBlockedTask(updatedTask)) {
        setTaskMessage("系统已完成一次自动修复尝试，但仍需要人工确认后再继续。");
      } else if (updatedTask.status === "failed") {
        setTaskMessage("自动建模运行失败，已保留诊断信息。请在任务状态中查看原因后再决定是否重试。");
      } else if (updatedTask.last_run) {
        setTaskMessage(`自动建模已完成。${getRunMetricSummaryText(updatedTask.last_run)}。`);
      } else {
        setTaskMessage("任务状态已更新。");
      }
    } catch (error) {
      await Promise.allSettled([loadTasks(), refreshActiveTaskHeavyData(taskId)]);
      setTaskError(getErrorMessage(error));
    } finally {
      setRunningTaskId("");
    }
  }

  function handleHumanTaskUpdated(updatedTask) {
    if (!updatedTask?.id) return;
    setTasks((current) => mergeTaskIntoList(current, updatedTask));
    setSelectedTaskId(updatedTask.id);
  }

  function handleOpenHumanCollaboration(taskId, preset = null) {
    if (!taskId) return;
    setSelectedTaskId(taskId);
    setHumanRequestPreset(
      preset
        ? {
            ...preset,
            task_id: taskId,
            preset_id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
          }
        : null,
    );
    setActivePage("human");
  }

  async function handleDeleteTask(taskId) {
    const task = tasks.find((item) => item.id === taskId);
    if (!task || !window.confirm(`确定删除任务“${task.name}”吗？这会同时删除它的 CSV 和运行结果。`)) return;
    setDeletingTaskId(taskId);
    setTaskError("");
    setTaskMessage("");
    try {
      await api.deleteTask(taskId, requestContext);
      setTasks((current) => current.filter((item) => item.id !== taskId));
      await Promise.all([loadUsageSummary(), loadTokenLedgers()]);
      if (selectedTaskId === taskId) {
        setTaskAIConversations(null);
        setTaskAIConversationsState("idle");
        setTaskAIConversationsError("");
        setTaskModelReport(null);
        setTaskModelReportState("idle");
        setTaskModelReportError("");
      }
      setTaskMessage(`任务“${task.name}”已删除。`);
    } catch (error) {
      setTaskError(getErrorMessage(error));
    } finally {
      setDeletingTaskId("");
    }
  }

  async function handleTaskInteractiveChat(prompt) {
    if (!selectedTask?.id) return false;
    setTaskChatSubmitting(true);
    setTaskChatError("");
    try {
      const response = await api.taskInteractiveChat(selectedTask.id, { prompt }, requestContext);
      setTasks((current) => mergeTaskIntoList(current, response.task));
      setSelectedTaskId(response.task.id);
      setTaskAIConversations(response.conversation);
      setTaskAIConversationsState("ready");
      setTaskAIConversationsError("");
      return true;
    } catch (error) {
      setTaskChatError(getErrorMessage(error));
      return false;
    } finally {
      setTaskChatSubmitting(false);
    }
  }

  async function handleConnectorSubmit(event) {
    event.preventDefault();
    if (!activeTeamId) return setConnectorError("请先选择团队。");
    setSavingConnector(true);
    setConnectorError("");
    setConnectorMessage("");
    try {
      const connector = await api.createConnector({
        display_name: connectorForm.display_name.trim(),
        endpoint_url: connectorForm.endpoint_url.trim(),
        model_name: connectorForm.model_name.trim(),
        wire_api: connectorForm.wire_api,
        api_key: connectorForm.api_key.trim(),
      }, requestContext);
      setConnectors((current) => mergeConnectorIntoList(current, connector));
      setConnectorForm(EMPTY_CONNECTOR_FORM);
      setConnectorMessage("AI 服务已保存。建议先测试连接，再设为当前使用。");
    } catch (error) {
      setConnectorError(getErrorMessage(error));
    } finally {
      setSavingConnector(false);
    }
  }

  async function handleTestConnector(connectorId) {
    setTestingConnectorId(connectorId);
    setConnectorError("");
    setConnectorMessage("");
    try {
      const response = await api.testConnector(connectorId, requestContext);
      setConnectors((current) => mergeConnectorIntoList(current, response.connector));
      setConnectorMessage(response.detail);
    } catch (error) {
      setConnectorError(getErrorMessage(error));
    } finally {
      setTestingConnectorId("");
    }
  }

  async function handleActivateConnector(connectorId) {
    setActivatingConnectorId(connectorId);
    setConnectorError("");
    setConnectorMessage("");
    try {
      const response = await api.activateConnector(connectorId, requestContext);
      setConnectors((current) => mergeConnectorIntoList(current, response.connector));
      await loadHealth();
      setConnectorMessage("当前使用的 AI 已切换。之后任务上传、AI 理解和自动建模都会使用它。");
    } catch (error) {
      setConnectorError(getErrorMessage(error));
    } finally {
      setActivatingConnectorId("");
    }
  }

  async function handleUpdateConnector(connectorId, payload) {
    setUpdatingConnectorId(connectorId);
    setConnectorError("");
    setConnectorMessage("");
    try {
      const updatedConnector = await api.updateConnector(connectorId, payload, requestContext);
      setConnectors((current) => mergeConnectorIntoList(current, updatedConnector));
      await Promise.all([loadAuditLogs()]);
      setConnectorMessage("AI 服务配置已更新。请重新测试后再作为稳定服务使用。");
      return true;
    } catch (error) {
      setConnectorError(getErrorMessage(error));
      return false;
    } finally {
      setUpdatingConnectorId("");
    }
  }

  async function handleHealthCheckConnectors() {
    setHealthCheckingConnectors(true);
    setConnectorError("");
    setConnectorMessage("");
    try {
      const response = await api.healthCheckConnectors(requestContext);
      const results = response.items ?? [];
      setConnectors((current) => results.reduce((items, item) => (
        item.connector ? mergeConnectorIntoList(items, item.connector) : items
      ), current));
      const passedCount = results.filter((item) => item.ok).length;
      await loadAuditLogs();
      setConnectorMessage(`${response.detail} ${passedCount}/${results.length} 个 AI 服务通过。`);
    } catch (error) {
      setConnectorError(getErrorMessage(error));
    } finally {
      setHealthCheckingConnectors(false);
    }
  }

  async function handleDeactivateConnector(connectorId) {
    setDeactivatingConnectorId(connectorId);
    setConnectorError("");
    setConnectorMessage("");
    try {
      const response = await api.deactivateConnector(connectorId, requestContext);
      setConnectors((current) => mergeConnectorIntoList(current, response.connector));
      await Promise.all([loadHealth(), loadAuditLogs()]);
      setConnectorMessage(response.detail);
      return true;
    } catch (error) {
      setConnectorError(getErrorMessage(error));
      return false;
    } finally {
      setDeactivatingConnectorId("");
    }
  }

  async function handleDeleteConnector(connectorId) {
    const connector = connectors.find((item) => item.id === connectorId);
    if (!connector || !window.confirm(`确定删除 AI 服务“${connector.display_name}”吗？删除后任务不能再使用它。`)) return false;
    setDeletingConnectorId(connectorId);
    setConnectorError("");
    setConnectorMessage("");
    try {
      const wasActive = connector.is_active;
      const response = await api.deleteConnector(connectorId, requestContext);
      setConnectors((current) => current.filter((item) => item.id !== connectorId));
      await Promise.all([wasActive ? loadHealth() : Promise.resolve(), loadAuditLogs()]);
      setConnectorMessage(response.detail);
      return true;
    } catch (error) {
      setConnectorError(getErrorMessage(error));
      return false;
    } finally {
      setDeletingConnectorId("");
    }
  }

  async function handlePrepareInvite(payload) {
    setInviteBusy(true);
    setTeamError("");
    setTeamMessage("");
    try {
      const response = await api.prepareTeamInvite(payload, requestContext);
      setInviteInfo(response);
      setTeamMessage(response.detail);
    } catch (error) {
      setTeamError(getErrorMessage(error));
    } finally {
      setInviteBusy(false);
    }
  }

  async function handleUpdateTeamMemberRole(memberId, payload) {
    setRoleUpdatingUserId(memberId);
    setTeamError("");
    setTeamMessage("");
    try {
      await api.updateTeamMemberRole(memberId, payload, requestContext);
      await Promise.all([loadTeamMembers(), loadAuditLogs()]);
      setTeamMessage("成员角色已更新。");
    } catch (error) {
      setTeamError(getErrorMessage(error));
    } finally {
      setRoleUpdatingUserId("");
    }
  }

  async function handleUpdateTeamMemberStatus(memberId, payload) {
    setStatusUpdatingUserId(memberId);
    setTeamError("");
    setTeamMessage("");
    try {
      await api.updateTeamMemberStatus(memberId, payload, requestContext);
      await Promise.all([loadTeamMembers(), loadAuditLogs()]);
      setTeamMessage("成员状态已更新。");
    } catch (error) {
      setTeamError(getErrorMessage(error));
    } finally {
      setStatusUpdatingUserId("");
    }
  }

  async function handleUpdateTeamSettings(payload) {
    setTeamSettingsSaving(true);
    setTeamError("");
    setTeamMessage("");
    try {
      const response = await api.updateTeamSettings(payload, requestContext);
      setTeamSettings(response.team ?? null);
      setMemberships((current) => current.map((team) => (
        team.id === activeTeamId
          ? {
              ...team,
              name: response.team?.name ?? team.name,
              description: response.team?.description ?? "",
              status: response.team?.status ?? team.status,
              updated_at: response.team?.updated_at ?? team.updated_at,
            }
          : team
      )));
      await loadAuditLogs();
      setTeamMessage("团队设置已更新。");
      return true;
    } catch (error) {
      setTeamError(getErrorMessage(error));
      return false;
    } finally {
      setTeamSettingsSaving(false);
    }
  }

  async function handleTransferTeamOwnership(newOwnerUserId) {
    if (!newOwnerUserId) return false;
    const target = teamMembers.find((member) => member.user_id === newOwnerUserId);
    const label = target?.profile?.display_name || target?.profile?.email || newOwnerUserId;
    if (!window.confirm(`确定把团队所有权转移给“${label}”吗？转移后你会降为管理员。`)) return false;
    setOwnershipTransferring(true);
    setTeamError("");
    setTeamMessage("");
    try {
      const response = await api.transferTeamOwnership({ new_owner_user_id: newOwnerUserId }, requestContext);
      setTeamSettings(response.team ?? null);
      await Promise.all([loadMemberships(activeTeamId), loadTeamMembers(), loadAuditLogs()]);
      setTeamMessage(response.detail);
      return true;
    } catch (error) {
      setTeamError(getErrorMessage(error));
      return false;
    } finally {
      setOwnershipTransferring(false);
    }
  }

  async function handleSaveTeamQuota(quota, payload) {
    const scopeType = quota?.scope_type ?? "member";
    const scopeKey = quota?.scope_key || quota?.user_id || quota?.connector_id || quota?.team_id;
    if (!scopeKey) {
      setQuotaError("缺少使用上限记录标识，无法保存。");
      return;
    }
    const quotaKey = `${scopeType}:${scopeKey}`;
    setQuotaSavingKey(quotaKey);
    setQuotaError("");
    setQuotaMessage("");
    try {
      await api.adjustTeamQuotaScope({
        ...payload,
        scope_type: scopeType,
        scope_key: scopeKey,
        user_id: scopeType === "member" ? scopeKey : undefined,
        connector_id: scopeType === "connector" ? scopeKey : undefined,
      }, requestContext);
      await Promise.all([loadQuotaSummary(), loadAuditLogs()]);
      setQuotaMessage("使用上限已更新。");
    } catch (error) {
      setQuotaError(getErrorMessage(error));
    } finally {
      setQuotaSavingKey("");
    }
  }

  async function handleSaveRoutingPolicies(payload) {
    setRoutingSaving(true);
    setRoutingError("");
    setRoutingMessage("");
    try {
      const response = await api.saveTeamRouting(payload, requestContext);
      setRoutingPolicies(response.items ?? []);
      await loadAuditLogs();
      setRoutingMessage(response.detail);
    } catch (error) {
      setRoutingError(getErrorMessage(error));
    } finally {
      setRoutingSaving(false);
    }
  }

  async function handleCreateAsset(payload) {
    setAssetCreating(true);
    setAssetError("");
    setAssetMessage("");
    try {
      await api.createTeamAsset(payload, requestContext);
      await Promise.all([loadAssets(), loadAuditLogs()]);
      setAssetMessage("资产记录已创建。");
    } catch (error) {
      setAssetError(getErrorMessage(error));
    } finally {
      setAssetCreating(false);
    }
  }

  async function handleCreateAssetFromTask(assetType) {
    if (!selectedTask?.id) return setAssetError("请先选择一个任务。");
    const datasetProfile = getTaskDatasetProfile(selectedTask);
    const baseTags = [
      selectedTask.problem_type,
      selectedTask.label_column,
      selectedTask.dataset_filename ? "csv" : "",
    ].filter(Boolean);
    const category = selectedTask.problem_type ? `tabular_${selectedTask.problem_type}` : "tabular";
    let payload = null;
    if (assetType === "dataset") {
      if (!selectedTask.dataset_path) return setAssetError("当前任务还没有可登记的数据集路径。");
      payload = {
        asset_type: "dataset",
        title: `${selectedTask.name} 数据集`,
        description: selectedTask.description,
        storage_path: selectedTask.dataset_path,
        category,
        tags: baseTags,
        visibility: "private",
        version: "1.0.0",
        source_task_id: selectedTask.id,
        metadata: { dataset_profile: datasetProfile },
        review_status: "pending_review",
      };
    } else if (assetType === "model") {
      if (!selectedTask.last_run?.output_dir) return setAssetError("当前任务还没有成功结果，不能保存模型成果。");
      payload = {
        asset_type: "model",
        title: `${selectedTask.name} 模型`,
        description: selectedTask.notes || selectedTask.description,
        storage_path: selectedTask.last_run.output_dir,
        category,
        tags: [...baseTags, selectedTask.last_run.best_model].filter(Boolean),
        visibility: "private",
        version: "1.0.0",
        source_task_id: selectedTask.id,
        model_card: {
          task_id: selectedTask.id,
          task_name: selectedTask.name,
          problem_type: selectedTask.problem_type,
          label_column: selectedTask.label_column,
          best_model: selectedTask.last_run.best_model,
          metric_name: selectedTask.last_run.metric_name,
          metric_value: selectedTask.last_run.metric_value,
          output_dir: selectedTask.last_run.output_dir,
          dataset_profile: datasetProfile,
        },
        metadata: { leaderboard: selectedTask.last_run.leaderboard ?? [] },
        review_status: "pending_review",
      };
    } else if (assetType === "report") {
      if (!selectedTask.last_run?.output_dir) return setAssetError("当前任务还没有成功结果，不能保存报告成果。");
      payload = {
        asset_type: "report",
        title: `${selectedTask.name} 分析报告`,
        description: `基于任务 ${selectedTask.name} 的模型报告入口。`,
        storage_path: selectedTask.last_run.output_dir,
        category,
        tags: [...baseTags, "report"],
        visibility: "private",
        version: "1.0.0",
        source_task_id: selectedTask.id,
        metadata: {
          report_api: `/api/teams/${activeTeamId}/tasks/${selectedTask.id}/report`,
          metric_name: selectedTask.last_run.metric_name,
          metric_value: selectedTask.last_run.metric_value,
        },
        review_status: "pending_review",
      };
    } else if (assetType === "workflow") {
      payload = {
        asset_type: "workflow",
        title: `${selectedTask.name} 工作流`,
        description: selectedTask.description,
        storage_path: selectedTask.last_run?.output_dir || selectedTask.dataset_path || null,
        category,
        tags: [...baseTags, "workflow"],
        visibility: "private",
        version: "1.0.0",
        source_task_id: selectedTask.id,
        metadata: {
          task_id: selectedTask.id,
          stage_routing: selectedTask.stage_routing ?? [],
          interaction_policies: selectedTask.interaction_policies ?? [],
          structured_requirements: selectedTask.structured_requirements ?? null,
          last_run: selectedTask.last_run ?? null,
        },
        review_status: "pending_review",
      };
    }
    if (!payload) return;
    setAssetCreating(true);
    setAssetError("");
    setAssetMessage("");
    try {
      await api.createTeamAsset(payload, requestContext);
      await Promise.all([loadAssets(), loadAuditLogs()]);
      setAssetMessage("已从当前任务创建待审核资产。");
      setActivePage("assets");
    } catch (error) {
      setAssetError(getErrorMessage(error));
    } finally {
      setAssetCreating(false);
    }
  }

  async function handleReviewAsset(assetId, payload) {
    setAssetReviewingId(assetId);
    setAssetError("");
    setAssetMessage("");
    try {
      await api.reviewTeamAsset(assetId, payload, requestContext);
      await Promise.all([loadAssets(), loadAuditLogs()]);
      setAssetMessage("资产审核状态已更新。");
    } catch (error) {
      setAssetError(getErrorMessage(error));
    } finally {
      setAssetReviewingId("");
    }
  }

  async function handlePublishAsset(assetId, visibility = "public") {
    setAssetPublishingId(assetId);
    setAssetError("");
    setAssetMessage("");
    try {
      await api.publishTeamAsset(assetId, { visibility }, requestContext);
      await Promise.all([loadAssets(), loadAuditLogs()]);
      setAssetMessage("资产已发布到团队广场。");
    } catch (error) {
      setAssetError(getErrorMessage(error));
    } finally {
      setAssetPublishingId("");
    }
  }

  async function handleForkAsset(asset) {
    if (!asset?.id) return;
    const title = window.prompt("Fork 后的新资产标题", `Fork of ${asset.title}`);
    if (!title) return;
    const version = window.prompt("Fork 后的版本号", asset.version || "1.0.0");
    setAssetForkingId(asset.id);
    setAssetError("");
    setAssetMessage("");
    try {
      await api.forkTeamAsset(asset.id, { title: title.trim(), version: version?.trim() || asset.version || "1.0.0", review_status: "private" }, requestContext);
      await Promise.all([loadAssets(), loadAuditLogs()]);
      setAssetMessage("资产 Fork 已创建。");
    } catch (error) {
      setAssetError(getErrorMessage(error));
    } finally {
      setAssetForkingId("");
    }
  }

  function getTaskProgressPercent(task, runtimeProgress = null) {
    const runtimeStatus = getTaskRuntimeStatus(task, runtimeProgress, runningTaskId === task?.id);
    if (task?.last_run || task?.status === "completed") return 100;
    if (runtimeStatus === "running" || runtimeStatus === "repairing") return Math.max(30, Math.min(85, runtimeProgress?.progress_percent ?? 45));
    if (runtimeStatus === "blocked") return Math.max(10, Math.min(70, runtimeProgress?.progress_percent ?? 35));
    if (task?.status === "failed" || runtimeStatus === "stale") return 10;
    if (task?.label_column && task?.problem_type) return 65;
    if (task?.dataset_filename) return 28;
    return 0;
  }

  function getTaskRowTone(task, runtimeProgress = null) {
    const runtimeStatus = getTaskRuntimeStatus(task, runtimeProgress, runningTaskId === task?.id);
    if (task?.last_run || task?.status === "completed") return "success";
    if (task?.status === "failed" || runtimeStatus === "stale") return "danger";
    if (runtimeStatus === "running" || runtimeStatus === "repairing") return "info";
    if (!task?.dataset_filename || ["waiting_human", "paused_for_review", "blocked"].includes(runtimeStatus)) return "warning";
    return "info";
  }

  function getTaskRowAction(task, runtimeProgress = null) {
    const runtimeStatus = getTaskRuntimeStatus(task, runtimeProgress, runningTaskId === task?.id);
    if (task?.last_run || task?.status === "completed") return { label: "看结果", page: "report" };
    if (task?.status === "failed" || runtimeStatus === "stale") return { label: "查看状态", page: "tasks", mode: "detail" };
    if (runtimeStatus === "running" || runtimeStatus === "repairing" || runtimeStatus === "blocked") return { label: "查看进度", page: "tasks", mode: "detail" };
    if (!task?.dataset_filename) return { label: "继续填写", page: "tasks", mode: "create" };
    return { label: "查看详情", page: "tasks", mode: "detail" };
  }

  function openTaskRow(task, runtimeProgress = null) {
    const action = getTaskRowAction(task, runtimeProgress);
    setSelectedTaskId(task.id);
    if (action.mode) setTaskPanelMode(action.mode);
    setActivePage(action.page);
    if (action.page === "tasks" && action.mode === "detail") void loadTaskRunProgress(task.id, { silent: true });
    if (action.page === "report") void loadTaskModelReport(task.id);
  }

  function renderTaskRow(task, compact = false) {
    const runtimeProgress = taskRunProgressByTaskId[task.id] ?? (selectedTask?.id === task.id ? selectedTaskRunProgress : null);
    const runtimeStatus = getTaskRuntimeStatus(task, runtimeProgress, runningTaskId === task.id);
    const progress = getTaskProgressPercent(task, runtimeProgress);
    const tone = getTaskRowTone(task, runtimeProgress);
    const action = getTaskRowAction(task, runtimeProgress);
    return (
      <article key={task.id} className={cn("showcase-task-row", tone, compact && "compact")}>
        <div className="showcase-task-icon" aria-hidden="true">{tone === "success" ? "✓" : tone === "danger" ? "!" : tone === "warning" ? "↑" : "•"}</div>
        <div className="showcase-task-main">
          <h3>{task.name}</h3>
          <p>创建于 {formatDateTime(task.created_at)}{task.dataset_filename ? ` · 数据：${task.dataset_filename}` : " · 数据：未上传"}</p>
        </div>
        <div className="showcase-task-state">
          <span className={`status-dot ${tone}`} />
          <strong>{formatRuntimeStatusLabel(runtimeStatus, runtimeProgress, 18)}</strong>
          <p>下一步：{getTaskNextStep(task, runtimeStatus).title}</p>
        </div>
        <div className="showcase-progress-ring" style={{ "--value": `${progress}%` }}>
          <span>{progress}%</span>
        </div>
        <button type="button" className="showcase-outline-button" onClick={() => openTaskRow(task, runtimeProgress)}>
          {action.label}
        </button>
        <button type="button" className="showcase-more-button" aria-label="更多操作">⋮</button>
      </article>
    );
  }

  function renderRecentTaskRows(limit = 3) {
    const items = tasks.slice(0, limit);
    if (!items.length && tasksState !== "loading") return <div className="empty-state">还没有任务。</div>;
    if (!items.length) return <div className="empty-state">正在读取任务列表...</div>;
    return <div className="showcase-task-list recent">{items.map((task) => renderTaskRow(task, true))}</div>;
  }

  function renderStartTaskPage() {
    return (
      <div className="showcase-page start-page">
        <section className="showcase-page-title">
          <div>
            <h1>开始建模</h1>
            <span className="mode-badge">新手模式</span>
          </div>
        </section>

        <div className="showcase-stepper" aria-label="建模步骤">
          <article className="active"><span>1</span><strong>说清目标</strong></article>
          <article><span>2</span><strong>上传数据</strong></article>
          <article><span>3</span><strong>AI 自动尝试</strong></article>
          <article><span>4</span><strong>看懂结果</strong></article>
        </div>

        {!activeConnector ? (
          <section className="showcase-warning-line">
            <strong>当前团队的 AI 模型还没有准备好</strong>
            <p>{teamCanManage ? "请先让管理员完成模型配置，上传后才会进行真实 AI 理解。" : "请联系团队管理员准备 AI 模型。"}</p>
          </section>
        ) : null}

        {taskMessage ? <div className="notice-banner">{taskMessage}</div> : null}
        {taskError ? <div className="error-banner">{taskError}</div> : null}

        <div className="showcase-start-grid">
          <TaskForm
            form={taskForm}
            connectors={connectors}
            selectedFile={taskFile}
            fileInputKey={taskUploadToken}
            submitting={submittingTask}
            onFieldChange={handleTaskFormFieldChange}
            onStageRoutingChange={handleTaskStageRoutingChange}
            onAddPolicy={handleAddTaskPolicy}
            onPolicyChange={handleTaskPolicyChange}
            onRemovePolicy={handleRemoveTaskPolicy}
            onFileChange={(event) => setTaskFile(event.target.files?.[0] ?? null)}
            onSubmit={handleTaskSubmit}
          />

          <aside className="showcase-next-card">
            <h2>下一步</h2>
            <div className="next-illustration" aria-hidden="true">⌁</div>
            <p>上传数据后，AI 会先帮你确认要预测什么、适合怎么建模。</p>
            <div className="showcase-tip">
              <strong>不用担心</strong>
              <span>我们会一步步帮你完成建模。</span>
            </div>
          </aside>
        </div>

        <section className="showcase-card recent-task-panel">
          <div className="showcase-section-head">
            <h2>最近任务</h2>
            <button type="button" className="showcase-link-button" onClick={() => setTaskPanelMode("queue")}>查看全部</button>
          </div>
          {renderRecentTaskRows(3)}
        </section>
      </div>
    );
  }

  function renderTaskQueuePage() {
    const completed = tasks.filter((task) => task.last_run || task.status === "completed").length;
    const running = tasks.filter((task) => ["running", "planning"].includes(task.status)).length;
    const blocked = tasks.filter((task) => ["failed", "paused_for_review", "waiting_human"].includes(task.status)).length;
    return (
      <div className="showcase-page queue-page">
        <section className="showcase-page-title with-copy">
          <div>
            <h1>我的任务</h1>
            <p>按状态查看每个建模任务，先看结论，再进入细节。</p>
          </div>
        </section>

        <div className="showcase-queue-layout">
          <main className="showcase-queue-main">
            <div className="showcase-filter-bar">
              <button className="active" type="button">全部</button>
              <button type="button">需要我处理 <span>{waitingTaskCount}</span></button>
              <button type="button">运行中 <span>{running}</span></button>
              <button type="button">已完成 <span>{completed}</span></button>
              <button type="button">遇到问题 <span>{blocked}</span></button>
              <label className="showcase-search">
                <span>⌕</span>
                <input placeholder="搜索任务名称" />
              </label>
            </div>
            {tasks.length > TASK_QUEUE_RENDER_LIMIT ? <div className="notice-banner compact">当前只渲染最近 {TASK_QUEUE_RENDER_LIMIT} 个任务。</div> : null}
            <div className="showcase-task-list">
              {tasksState === "loading" && !tasks.length ? <div className="empty-state">正在读取任务列表...</div> : null}
              {!tasks.length && tasksState !== "loading" ? <div className="empty-state">还没有任务。</div> : null}
              {tasks.slice(0, TASK_QUEUE_RENDER_LIMIT).map((task) => renderTaskRow(task))}
            </div>
            <div className="showcase-pagination">
              <span>共 {tasks.length} 项任务</span>
              <button type="button" disabled>‹</button>
              <button type="button" className="active">1</button>
              <button type="button" disabled>›</button>
            </div>
          </main>

          <aside className="showcase-help-card">
            <h2>怎么判断下一步？</h2>
            <article className="success"><strong>绿色表示可以看结果</strong><span>任务已完成或有可查看的结论。</span></article>
            <article className="warning"><strong>橙色表示需要你补充信息</strong><span>请根据提示补充数据或信息。</span></article>
            <article className="danger"><strong>红色表示需要先处理问题</strong><span>请先查看原因并解决问题。</span></article>
          </aside>
        </div>
      </div>
    );
  }

  function renderTaskProgressPage() {
    if (!selectedTask) {
      return (
        <div className="showcase-page task-progress-page">
          <section className="showcase-card task-progress-empty">
            <h2>还没有选择任务</h2>
            <p>请先从“我的任务”里选择一个任务。</p>
            <button type="button" className="showcase-outline-button" onClick={() => setTaskPanelMode("queue")}>回到任务列表</button>
          </section>
        </div>
      );
    }

    const runProgress = selectedTaskRunProgress?.task?.id === selectedTask.id
      ? selectedTaskRunProgress
      : taskRunProgressByTaskId[selectedTask.id] ?? null;
    const runtimeStatus = getTaskRuntimeStatus(selectedTask, runProgress, runningTaskId === selectedTask.id);
    const runtimeProgressLabel = formatRuntimeStatusLabel(runtimeStatus, runProgress, 24);
    const progress = getTaskProgressPercent(selectedTask, runProgress);
    const lifecycleSteps = getTaskLifecycleSteps(selectedTask, runtimeStatus);
    const agentLoop = getTaskAgentLoop(selectedTask);
    const agentLoopSummary = getAgentLoopSummary(selectedTask);
    const taskDiagnosis = getTaskDiagnosticText(selectedTask, runProgress);
    const runActivity = getReadableRuntimeActivity(runProgress);
    const canRunSelectedTask = Boolean(selectedTask.dataset_filename)
      && runningTaskId !== selectedTask.id
      && !["running", "repairing"].includes(runtimeStatus)
      && !["waiting_human", "paused_for_review"].includes(selectedTask.status);

    return (
      <div className="showcase-page task-progress-page">
        <section className="showcase-page-title with-copy task-progress-title">
          <div>
            <h1>{selectedTask.name}</h1>
            <p>{selectedTask.dataset_filename ? `数据：${selectedTask.dataset_filename}` : "还没有上传数据"}</p>
          </div>
          <button type="button" className="showcase-outline-button" onClick={() => setTaskPanelMode("queue")}>回到任务列表</button>
        </section>

        {taskRunProgressError ? <div className="error-banner">{taskRunProgressError}</div> : null}

        <section className="showcase-card task-progress-hero">
          <div className="task-progress-hero-main">
            <div className="showcase-progress-ring large" style={{ "--value": `${progress}%` }}>
              <span>{progress}%</span>
            </div>
            <div>
              <span className={`runtime-pill ${getProgressTone(runProgress)}`}>{runtimeProgressLabel}</span>
              <h2>{getTaskNextStep(selectedTask, runtimeStatus).title}</h2>
              <p>{runActivity || taskDiagnosis || getTaskNextStep(selectedTask, runtimeStatus).body}</p>
            </div>
          </div>
          <div className="task-progress-actions">
            <button type="button" className="showcase-outline-button" onClick={() => void loadTaskRunProgress(selectedTask.id)} disabled={taskRunProgressState === "loading" || taskRunProgressState === "refreshing"}>
              {taskRunProgressState === "loading" || taskRunProgressState === "refreshing" ? "刷新中" : "刷新进度"}
            </button>
            <button type="button" className="primary-button" onClick={() => setActivePage("report")} disabled={!selectedTask.last_run && selectedTask.status !== "completed"}>
              查看结果
            </button>
          </div>
        </section>

        <section className="showcase-card task-progress-card">
          <div className="showcase-section-head">
            <h2>当前进展</h2>
          </div>
          <div className="task-progress-strip" aria-label="任务阶段">
            {lifecycleSteps.map((step, index) => (
              <div key={step.key} className={`task-progress-step ${step.state}`}>
                <span>{index + 1}</span>
                <strong>{step.label}</strong>
                {step.detail ? <em>{compactStatusLabel(step.detail, 32)}</em> : null}
              </div>
            ))}
          </div>
          <div className="task-progress-facts">
            <article>
              <span>AI 理解</span>
              <strong>{getTaskAnalysisStepText(selectedTask, runProgress)}</strong>
            </article>
            <article>
              <span>训练状态</span>
              <strong>{getTaskTrainingStepText(selectedTask, runProgress)}</strong>
            </article>
            <article>
              <span>当前阶段</span>
              <strong>{formatWorkflowStage(runProgress?.current_stage, "等待更新")}</strong>
            </article>
            <article>
              <span>候选模型</span>
              <strong>{runProgress?.completed_model_count != null ? `${runProgress.completed_model_count}/${runProgress.total_model_count ?? "?"}` : selectedTask.last_run?.leaderboard?.length ?? "暂无"}</strong>
            </article>
          </div>
        </section>

        {agentLoop ? (
          <section className="showcase-card agent-loop-card">
            <div className="showcase-section-head">
              <h2>系统检查</h2>
              <p>先用最简单的方法做对照，再检查结果是否可靠、是否需要继续优化。</p>
            </div>
            <div className="agent-loop-summary-grid">
              <article><span>简单对照</span><strong>{formatAgentMetric(agentLoopSummary?.baseline)}</strong></article>
              <article><span>检查项</span><strong>{agentLoopSummary?.checklistCount ?? 0} 项</strong></article>
              <article><span>优化记录</span><strong>{agentLoopSummary?.attemptCount ?? 0} 次</strong></article>
              <article><span>风险项</span><strong>{(agentLoopSummary?.blocked ?? 0) + (agentLoopSummary?.warning ?? 0)} 项</strong></article>
            </div>
            {Array.isArray(agentLoop.quality_gates) && agentLoop.quality_gates.length ? (
              <div className="agent-loop-chip-list">
                {agentLoop.quality_gates.slice(0, 5).map((gate) => (
                  <span key={gate.id} className={`agent-loop-chip ${getAgentLoopStatusTone(gate.status)}`}>
                    {gate.title} · {getAgentLoopStatusLabel(gate.status)}
                  </span>
                ))}
              </div>
            ) : null}
            {agentLoopSummary?.nextImprovement?.action ? (
              <div className="callout">
              <strong>下一步建议</strong>
                <p>{agentLoopSummary.nextImprovement.action}</p>
              </div>
            ) : null}
          </section>
        ) : null}

        {taskDiagnosis && ["blocked", "failed", "stale"].includes(runtimeStatus) ? (
          <section className="showcase-card task-progress-card warning">
            <div className="showcase-section-head">
              <h2>需要处理的问题</h2>
            </div>
            <p>{taskDiagnosis}</p>
            <button type="button" className="primary-button" onClick={() => void handleRunTask(selectedTask.id)} disabled={!canRunSelectedTask}>
              重新尝试
            </button>
          </section>
        ) : null}
      </div>
    );
  }

  function renderTaskDetail() {
    if (!selectedTask) return <div className="empty-state task-detail-panel">先创建一个任务，或从任务队列中选择已有任务。</div>;
    const runProgress = selectedTaskRunProgress?.task?.id === selectedTask.id ? selectedTaskRunProgress : null;
    const runProgressActivity = getReadableRuntimeActivity(runProgress);
    const runtimeStatus = getTaskRuntimeStatus(selectedTask, runProgress);
    const runtimeProgressLabel = formatRuntimeStatusLabel(runtimeStatus, runProgress);
    const taskDiagnosis = getTaskDiagnosticText(selectedTask, runProgress);
  const rerunStage = getTaskRerunStage(selectedTask);
    const nextStep = getTaskNextStep(selectedTask, runtimeStatus);
    const lifecycleSteps = getTaskLifecycleSteps(selectedTask, runtimeStatus);
    const agentLoop = getTaskAgentLoop(selectedTask);
    const agentLoopSummary = getAgentLoopSummary(selectedTask);
    const canRunSelectedTask = Boolean(selectedTask.dataset_filename)
      && runningTaskId !== selectedTask.id
      && !["running", "repairing"].includes(runtimeStatus)
      && !["waiting_human", "paused_for_review"].includes(selectedTask.status);
    const canAnalyzeSelectedTask = Boolean(selectedTask.dataset_filename)
      && analyzingTaskId !== selectedTask.id
      && runningTaskId !== selectedTask.id
      && !["running", "repairing"].includes(runtimeStatus);

    function handleNextStepClick() {
      if (nextStep.action === "开始理解") {
        if (canAnalyzeSelectedTask) void handleAnalyzeTask(selectedTask.id);
        return;
      }
      if (nextStep.action === "开始自动建模") {
        if (canRunSelectedTask) void handleRunTask(selectedTask.id);
        return;
      }
      if (nextStep.action === "重新运行") {
        if (canRunSelectedTask) void handleRunTask(selectedTask.id);
        return;
      }
      setActivePage(nextStep.page);
    }

    return (
      <div className="detail-stack task-detail-panel task-panel">
        <section className="section-card task-detail-hero">
          <div className="task-detail-titlebar">
            <div>
              <p className="eyebrow">当前任务</p>
              <h3>{selectedTask.name}</h3>
              <p className="task-description-large">{selectedTask.description}</p>
            </div>
            <span className={`runtime-pill ${getTaskStatusTone(runtimeStatus)}`}>{runtimeProgressLabel}</span>
          </div>

          <div className="task-next-action">
            <span className={`task-next-dot ${nextStep.tone}`} />
            <div>
              <strong>{nextStep.title}</strong>
              <p>{nextStep.body}</p>
            </div>
            <button type="button" className="primary-button" onClick={handleNextStepClick}>
              {nextStep.action}
            </button>
          </div>

          <div className="task-progress-strip" aria-label="任务阶段">
            {lifecycleSteps.map((step, index) => (
              <div key={step.key} className={`task-progress-step ${step.state}`}>
                <span>{index + 1}</span>
                <strong>{step.label}</strong>
                {step.detail ? <em>{compactStatusLabel(step.detail, 30)}</em> : null}
              </div>
            ))}
          </div>

          <div className="summary-grid task-detail-kpis">
            <article className="summary-item"><span>数据集</span><strong>{selectedTask.dataset_filename ?? "未上传"}</strong></article>
            <article className="summary-item"><span>AI 理解状态</span><strong>{formatTaskAnalysisStatus(selectedTask)}</strong></article>
            <article className="summary-item"><span>预测目标</span><strong>{selectedTask.label_column ?? "未解析"}</strong></article>
            <article className="summary-item"><span>问题类型</span><strong>{formatProblemType(selectedTask.problem_type)}</strong></article>
            <article className="summary-item"><span>建议指标</span><strong>{formatMetricName(getTaskMetricName(selectedTask))}</strong></article>
            <article className="summary-item"><span>理解可信度</span><strong>{formatConfidence(getTaskConfidence(selectedTask))}</strong></article>
          </div>
          {rerunStage ? (
            <div className="callout">
              <strong>下一次运行会从{formatWorkflowStage(rerunStage)}开始</strong>
              <p>系统会尽量复用前面已经完成的结果，只重新执行后面需要更新的部分。</p>
            </div>
          ) : null}
          {taskRunProgressError ? <div className="error-banner">{taskRunProgressError}</div> : null}
          {taskDiagnosis && ["blocked", "failed", "stale"].includes(runtimeStatus) ? (
            <div className="callout">
              <strong>系统诊断</strong>
              <p>{taskDiagnosis}</p>
            </div>
          ) : null}
          {runProgress ? (
            <section className={`task-linked-summary ${runProgress.stale ? "danger" : ""}`}>
              <div>
                <span className={`runtime-pill ${getProgressTone(runProgress)}`}>{runtimeProgressLabel}</span>
                <h3>运行状态</h3>
                <p>{runProgressActivity || taskDiagnosis || "系统正在读取运行进度，请稍后刷新任务状态。"}</p>
              </div>
              <div className="task-linked-summary-meta">
                <span>{formatWorkflowStage(runProgress.current_stage)}</span>
                <span>{runProgress.current_model ?? (runProgress.completed_model_count != null ? `候选 ${runProgress.completed_model_count}/${runProgress.total_model_count ?? "?"}` : "暂无候选")}</span>
              </div>
            </section>
          ) : ["running", "repairing"].includes(runtimeStatus) || taskRunProgressState === "loading" ? (
            <section className="task-linked-summary">
              <div>
                <span className="runtime-pill info">读取中</span>
                <h3>运行状态</h3>
                <p>正在读取真实运行记录和生成文件状态。</p>
              </div>
            </section>
          ) : null}

          {agentLoop ? (
            <section className="agent-loop-detail">
              <div className="showcase-section-head">
                <h2>自动建模复盘</h2>
                <p>系统会记录检查清单、简单对照、结果检查和优化建议。</p>
              </div>
              <div className="agent-loop-summary-grid">
                <article><span>简单对照</span><strong>{formatAgentMetric(agentLoopSummary?.baseline)}</strong></article>
                <article><span>待处理风险</span><strong>{agentLoopSummary?.blocked ?? 0} 个问题 / {agentLoopSummary?.warning ?? 0} 个提醒</strong></article>
                <article><span>优化尝试</span><strong>{agentLoopSummary?.attemptCount ?? 0} 条</strong></article>
              </div>

              {Array.isArray(agentLoop.checklist) && agentLoop.checklist.length ? (
                <details className="task-detail-fold">
                  <summary>任务检查清单</summary>
                  <div className="agent-loop-list">
                    {agentLoop.checklist.map((item) => (
                      <article key={item.id}>
                        <span className={`runtime-pill ${getAgentLoopStatusTone(item.status)}`}>{getAgentLoopStatusLabel(item.status)}</span>
                        <div>
                          <strong>{item.title}</strong>
                          <p>{item.detail}</p>
                        </div>
                      </article>
                    ))}
                  </div>
                </details>
              ) : null}

              {Array.isArray(agentLoop.tuning_attempts) && agentLoop.tuning_attempts.length ? (
                <details className="task-detail-fold">
                  <summary>优化记录</summary>
                  <div className="agent-loop-list">
                    {agentLoop.tuning_attempts.slice(-6).map((attempt, index) => (
                      <article key={attempt.correlation_key || `${attempt.kind}-${index}`}>
                        <span className={`runtime-pill ${getAgentLoopStatusTone(attempt.status)}`}>{getAgentLoopStatusLabel(attempt.status)}</span>
                        <div>
                          <strong>{attempt.kind || "attempt"} · 第 {attempt.attempt_index ?? index} 次</strong>
                          <p>{attempt.hypothesis}</p>
                          {attempt.action ? <em>{attempt.action}</em> : null}
                          {attempt.notes ? <small>{attempt.notes}</small> : null}
                        </div>
                      </article>
                    ))}
                  </div>
                </details>
              ) : null}
            </section>
          ) : null}

          <div className="button-row task-action-row">
            <button type="button" className="ghost-button" onClick={() => void handleAnalyzeTask(selectedTask.id)} disabled={!canAnalyzeSelectedTask}>{analyzingTaskId === selectedTask.id ? "理解中..." : "重新理解"}</button>
            <button type="button" className="primary-button" onClick={() => void handleRunTask(selectedTask.id)} disabled={!canRunSelectedTask}>{getTaskRunButtonLabel(selectedTask, runningTaskId === selectedTask.id)}</button>
            <button type="button" className="chip-button" onClick={() => setActivePage("report")}>模型报告</button>
          </div>
        </section>
      </div>
    );
  }

  if (!supabaseReady) {
    return <main className="auth-shell"><section className="auth-card"><SystemPanel health={health} loading={healthLoading} error={healthError} onRefresh={() => void loadHealth()} /></section></main>;
  }
  if (!session) {
    return <AuthScreen mode={authMode} busy={authBusy} error={authError} message={authMessage} requiresEmailVerification={requiresEmailVerification} onModeChange={setAuthMode} onLogin={handleLogin} onRegister={handleRegister} />;
  }
  if (teamBusy && !memberships.length) {
    return <main className="auth-shell"><section className="auth-card"><div className="auth-copy"><p className="eyebrow">团队加载中</p><h1>正在读取你的团队信息</h1></div></section></main>;
  }
  if (!memberships.length) {
    return <TeamOnboarding userLabel={getUserLabel(currentUser)} busy={teamBusy} error={teamError} message={teamMessage} onCreateTeam={handleCreateTeam} onJoinTeam={handleJoinTeam} onLogout={() => void handleLogout()} />;
  }

  return (
    <main className="app-shell">
      <div className="app-frame">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">AI</div>
            <div>
              <strong>AI4ML</strong>
              <span>智能建模小组</span>
            </div>
          </div>
          <div className="sidebar-summary">
            <span>当前团队</span>
            <strong>{activeTeam?.name ?? "未选择团队"}</strong>
            <em>{getTeamRoleLabel(activeTeam?.role)}</em>
          </div>
          <div className="beginner-path-card">
            <span>新手模式</span>
            <strong>按 6 步完成建模</strong>
            <p>少看术语，先把目标、数据、结果和复核跑通。</p>
          </div>
          <nav className="nav-list" aria-label="主导航">
            {NAV_GROUPS.map((group) => {
              const items = visibleNavItems.filter((item) => item.group === group.id);
              if (!items.length) return null;
              return (
                <section key={group.id} className="nav-group" aria-label={group.label}>
                  <p>{group.label}</p>
                  {items.map((item) => (
                    <button key={item.id} type="button" className={cn("nav-item", isNavItemActive(item) && "active")} onPointerEnter={() => warmPage(getNavItemPageId(item))} onFocus={() => warmPage(getNavItemPageId(item))} onClick={() => openNavItem(item)}>
                      <span className="nav-icon">{item.short}</span>
                      <span className="nav-copy"><strong>{item.label}</strong><em>{item.helper}</em></span>
                    </button>
                  ))}
                </section>
              );
            })}
          </nav>
        </aside>
        <div className="content">
          <header className="topbar">
            <div className="topbar-left">
              <div className="window-dots" aria-hidden="true"><span /><span /><span /></div>
              <div className="topbar-heading">
                <strong>{activeNavItem?.label ?? "工作台"}</strong>
                <span>{activeNavItem?.helper ?? "当前页面"}</span>
              </div>
              <div className={cn("runtime-pill", activeConnector ? "success" : "warning")}>
                {activeConnector ? `模型已就绪：${activeConnector.display_name}` : "模型未就绪"}
              </div>
            </div>
            <div className="topbar-right">
              {visibleExpertItems.length ? (
                <label className="expert-tool-picker">
                  <span>专家工具</span>
                  <select value={visibleExpertItems.some((item) => item.id === activePage) ? activePage : ""} onChange={(event) => openExpertPage(event.target.value)}>
                    <option value="">选择工具</option>
                    {visibleExpertItems.map((item) => (
                      <option key={item.id} value={item.id}>{item.label}</option>
                    ))}
                  </select>
                </label>
              ) : null}
              <select className="team-switcher" value={activeTeamId} onChange={(event) => setActiveTeamId(event.target.value)}>{memberships.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}</select>
              <button type="button" className="chip-button" onClick={() => void refreshWorkspaceData()}>刷新</button>
              <button type="button" className="logout-button" onClick={() => void handleLogout()}>退出登录</button>
            </div>
          </header>

          <div className="page-scroll">
            <Suspense fallback={<RouteLoading />}>
            <RoutePane pageId="tasks" activePage={activePage}>
              {taskPanelMode === "queue" ? renderTaskQueuePage() : taskPanelMode === "detail" ? renderTaskProgressPage() : renderStartTaskPage()}
            </RoutePane>

            <RoutePane pageId="agents" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">专家模式</p>
                    <h1>运行详情</h1>
                    <p className="page-copy">这里保留实时运行、训练监控和日志细节，主要给调试和汇报问答时使用。</p>
                  </div>
                </section>

                <MultiAgentCollaborationPanel
                  tasks={tasks}
                  tasksLoading={tasksState === "loading"}
                  selectedTask={selectedTask}
                  requestContext={requestContext}
                  runProgress={selectedTaskRunProgress?.task?.id === selectedTask?.id ? selectedTaskRunProgress : null}
                  runProgressState={taskRunProgressState}
                  runProgressError={taskRunProgressError}
                  onRefreshRunProgress={() => selectedTask?.id ? void loadTaskRunProgress(selectedTask.id) : undefined}
                  onSelectTask={setSelectedTaskId}
                  onOpenCodeWorkspace={() => setActivePage("code")}
                  onOpenHumanCollaboration={handleOpenHumanCollaboration}
                />
            </RoutePane>

            <RoutePane pageId="report" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">第 3 步</p>
                    <h1>结果报告</h1>
                    <p className="page-copy">把模型指标、重要影响因素和风险提示放在一起，用业务能理解的话解释这次结果是否可参考。</p>
                  </div>
                </section>

                <ModelReportPanel
                  tasks={tasks}
                  selectedTask={selectedTask}
                  report={taskModelReport}
                  reportState={taskModelReportState}
                  reportError={taskModelReportError}
                  onSelectTask={setSelectedTaskId}
                  onRefreshReport={() => selectedTask?.id ? void loadTaskModelReport(selectedTask.id) : undefined}
                  formatMetricName={formatMetricName}
                />
            </RoutePane>

            <RoutePane pageId="demo" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">专家模式</p>
                    <h1>试算一下</h1>
                    <p className="page-copy">这里用已经训练好的模型试算一条数据。没有可用模型时，页面会明确说明暂不支持。</p>
                  </div>
                </section>

                <PredictionDemoPanel
                  tasks={tasks}
                  tasksLoading={tasksState === "loading"}
                  selectedTask={selectedTask}
                  requestContext={requestContext}
                  onSelectTask={setSelectedTaskId}
                />
            </RoutePane>

            <RoutePane pageId="conversations" activePage={activePage}>
                <section className="page-header compact-page-header">
                  <div>
                    <p className="eyebrow">专家模式</p>
                    <h1>AI 记录</h1>
                  </div>
                  <div className="header-status-stack">
                    <div className="runtime-pill info">当前 AI：{activeConnector ? `${activeConnector.display_name} · ${activeConnector.model_name}` : health?.model_alias ?? "未读取"}</div>
                    <div className="runtime-pill">任务数：{tasks.length}</div>
                  </div>
                </section>

                <AIConversationPanel
                  tasks={tasks}
                  tasksLoading={tasksState === "loading"}
                  selectedTask={selectedTask}
                  conversationData={taskAIConversations}
                  loading={taskAIConversationsState === "loading"}
                  error={taskAIConversationsError}
                  chatSending={taskChatSubmitting}
                  chatError={taskChatError}
                  onSelectTask={setSelectedTaskId}
                  onRefresh={() => selectedTask?.id ? void loadTaskAIConversations(selectedTask.id) : undefined}
                  onSendInteractivePrompt={handleTaskInteractiveChat}
                  onOpenHumanCollaboration={handleOpenHumanCollaboration}
                  onOpenTaskDetails={() => setActivePage("tasks")}
                />
            </RoutePane>

            <RoutePane pageId="code" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">专家模式</p>
                    <h1>生成代码</h1>
                    <p className="page-copy">这里展示本次自动建模生成的代码。你可以浏览文件、打开代码，并把修改保存回这次结果。</p>
                  </div>
                  <div className="detail-stack">
                    <div className="runtime-pill info">当前 AI：{activeConnector ? `${activeConnector.display_name} · ${activeConnector.model_name}` : health?.model_alias ?? "未读取"}</div>
                  </div>
                </section>

                {taskError ? <div className="error-banner">{taskError}</div> : null}

                <CodeWorkspacePanel
                  tasks={tasks}
                  tasksLoading={tasksState === "loading"}
                  selectedTask={selectedTask}
                  requestContext={requestContext}
                  onSelectTask={setSelectedTaskId}
                  onOpenHumanCollaboration={handleOpenHumanCollaboration}
                  onOpenTaskDetails={() => setActivePage("tasks")}
                />
            </RoutePane>

            <RoutePane pageId="human" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">第 4 步</p>
                    <h1>复核待办</h1>
                    <p className="page-copy">当 AI 不确定、结果需要确认或任务暂停时，在这里做人工确认、补充说明或恢复执行。</p>
                  </div>
                  <div className="detail-stack">
                    <div className="runtime-pill info">当前 AI：{activeConnector ? `${activeConnector.display_name} · ${activeConnector.model_name}` : health?.model_alias ?? "未读取"}</div>
                  </div>
                </section>

                <HumanCollaborationPanel
                  tasks={tasks}
                  tasksLoading={tasksState === "loading"}
                  selectedTask={selectedTask}
                  requestContext={requestContext}
                  requestPreset={humanRequestPreset}
                  activeUserId={currentUser?.id ?? ""}
                  onSelectTask={setSelectedTaskId}
                  onTaskUpdated={handleHumanTaskUpdated}
                  onOpenTaskDetails={() => setActivePage("tasks")}
                />
            </RoutePane>

            <RoutePane pageId="usage" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">专家模式</p>
                    <h1>AI 使用记录</h1>
                    <p className="page-copy">这里显示当前团队实际使用 AI 的记录。没有采集到的数据会明确显示“未记录”，不会拿估算值冒充。</p>
                  </div>
                </section>
                <TokenUsagePanel
                  summary={usageSummary}
                  ledgers={tokenLedgers}
                  loading={usageState === "loading"}
                  ledgersLoading={tokenLedgerState === "loading"}
                  error={usageError}
                  ledgerError={tokenLedgerError}
                  canViewLedgers={teamCanManage}
                  onRefresh={() => void Promise.all([loadUsageSummary(), loadTokenLedgers()])}
                  onSelectTask={(taskId) => {
                    setSelectedTaskId(taskId);
                    setActivePage("tasks");
                  }}
                />
            </RoutePane>

            <RoutePane pageId="connectors" activePage={activePage}>
              <ConnectorManagementPanel
                activeTeamName={activeTeam?.name ?? ""}
                connectorsState={connectorsState}
                connectors={connectors}
                form={connectorForm}
                savingConnector={savingConnector}
                testingConnectorId={testingConnectorId}
                activatingConnectorId={activatingConnectorId}
                updatingConnectorId={updatingConnectorId}
                deactivatingConnectorId={deactivatingConnectorId}
                deletingConnectorId={deletingConnectorId}
                healthCheckingConnectors={healthCheckingConnectors}
                message={connectorMessage}
                error={connectorError}
                onFormChange={(field, value) => setConnectorForm((current) => ({ ...current, [field]: value }))}
                onSubmit={handleConnectorSubmit}
                onRefresh={() => void loadConnectors()}
                onTest={handleTestConnector}
                onActivate={handleActivateConnector}
                onUpdate={handleUpdateConnector}
                onDeactivate={handleDeactivateConnector}
                onDelete={handleDeleteConnector}
                onHealthCheck={handleHealthCheckConnectors}
              />
            </RoutePane>
            <RoutePane pageId="routing" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">专家模式</p>
                    <h1>默认 AI 设置</h1>
                    <p className="page-copy">这里设置每一步默认使用哪个 AI 服务。普通任务会自动沿用这些设置。</p>
                  </div>
                </section>
                <RoutingPolicyPanel
                  connectors={connectors}
                  policies={routingPolicies}
                  loading={routingState === "loading"}
                  saving={routingSaving}
                  canManage={teamCanManage}
                  message={routingMessage}
                  error={routingError}
                  onRefresh={() => void loadRoutingPolicies()}
                  onSave={handleSaveRoutingPolicies}
                />
            </RoutePane>
            <RoutePane pageId="quotas" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">专家模式</p>
                    <h1>使用上限</h1>
                    <p className="page-copy">管理员可以在这里设置团队和成员最多能使用多少 AI，并查看真实使用情况。</p>
                  </div>
                </section>
                <QuotaManagementPanel
                  quotas={quotaSummary}
                  loading={quotaState === "loading"}
                  savingQuotaKey={quotaSavingKey}
                  message={quotaMessage}
                  error={quotaError || (!teamCanManage ? "当前账号不是团队管理员，无法查看或调整成员使用上限。" : "")}
                  onRefresh={() => void loadQuotaSummary()}
                  onSave={handleSaveTeamQuota}
                />
            </RoutePane>
            <RoutePane pageId="assets" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">第 5 步</p>
                    <h1>成果库</h1>
                    <p className="page-copy">把已经生成的数据集、模型、流程或报告保存下来，方便团队后续查找、审核和复用。</p>
                  </div>
                </section>
                <AssetCenterPanel
                  assets={assetItems}
                  selectedTask={selectedTask}
                  loading={assetState === "loading"}
                  creating={assetCreating}
                  reviewingAssetId={assetReviewingId}
                  publishingAssetId={assetPublishingId}
                  forkingAssetId={assetForkingId}
                  message={assetMessage}
                  error={assetError}
                  isAdmin={teamCanManage}
                  onRefresh={() => void loadAssets()}
                  onCreate={handleCreateAsset}
                  onReview={handleReviewAsset}
                  onPublish={handlePublishAsset}
                  onFork={handleForkAsset}
                  onCreateFromTask={handleCreateAssetFromTask}
                />
            </RoutePane>
            <RoutePane pageId="team" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">第 6 步</p>
                    <h1>团队与权限</h1>
                    <p className="page-copy">管理小组成员、角色和团队设置。新人只需要知道谁能创建任务、谁能复核、谁能配置系统。</p>
                  </div>
                </section>
                {teamMessage ? <div className="notice-banner">{teamMessage}</div> : null}
                {teamError ? <div className="error-banner">{teamError}</div> : null}
                <TeamMembersPanel
                  activeTeam={activeTeam}
                  memberships={memberships}
                  teamMembers={teamMembers}
                  teamSettings={teamSettings}
                  teamSettingsLoading={teamSettingsState === "loading"}
                  teamSettingsSaving={teamSettingsSaving}
                  ownershipTransferring={ownershipTransferring}
                  loading={teamBusy}
                  activeUserId={currentUser?.id ?? ""}
                  canManage={teamCanManage}
                  canOwn={teamCanOwn}
                  inviteBusy={inviteBusy}
                  roleUpdatingUserId={roleUpdatingUserId}
                  statusUpdatingUserId={statusUpdatingUserId}
                  inviteInfo={inviteInfo}
                  onRefresh={() => void Promise.all([loadTeamMembers(), loadTeamSettings()])}
                  onSelectTeam={setActiveTeamId}
                  onPrepareInvite={handlePrepareInvite}
                  onUpdateRole={handleUpdateTeamMemberRole}
                  onUpdateStatus={handleUpdateTeamMemberStatus}
                  onUpdateSettings={handleUpdateTeamSettings}
                  onTransferOwnership={handleTransferTeamOwnership}
                />
            </RoutePane>
            <RoutePane pageId="audit" activePage={activePage}>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">专家模式</p>
                    <h1>操作记录</h1>
                    <p className="page-copy">团队里的重要操作会记录在这里，方便管理员回看是谁在什么时候做了什么。</p>
                  </div>
                </section>
                <AuditLogPanel
                  logs={auditLogs}
                  loading={auditState === "loading"}
                  error={auditError || (!teamCanManage ? "当前账号不是团队管理员，无法查看团队操作记录。" : "")}
                  onRefresh={() => void loadAuditLogs()}
                />
            </RoutePane>
            <RoutePane pageId="system" activePage={activePage}><SystemPanel health={health} loading={healthLoading} error={healthError} onRefresh={() => void loadHealth()} /></RoutePane>
            </Suspense>
          </div>
        </div>
      </div>
    </main>
  );
}
