import { useEffect, useMemo, useState } from "react";

import AIConversationPanel from "./components/AIConversationPanel.jsx";
import AssetCenterPanel from "./components/AssetCenterPanel.jsx";
import AuditLogPanel from "./components/AuditLogPanel.jsx";
import AuthScreen from "./components/AuthScreen.jsx";
import ConnectorManagementPanel from "./components/ConnectorManagementPanel.jsx";
import CodeWorkspacePanel from "./components/CodeWorkspacePanel.jsx";
import HumanCollaborationPanel from "./components/HumanCollaborationPanel.jsx";
import LeaderboardPanel from "./components/LeaderboardPanel.jsx";
import ModelReportPanel from "./components/ModelReportPanel.jsx";
import PredictionDemoPanel from "./components/PredictionDemoPanel.jsx";
import QuotaManagementPanel from "./components/QuotaManagementPanel.jsx";
import RoutingPolicyPanel from "./components/RoutingPolicyPanel.jsx";
import SystemPanel from "./components/SystemPanel.jsx";
import TaskCard from "./components/TaskCard.jsx";
import TaskForm from "./components/TaskForm.jsx";
import TeamMembersPanel from "./components/TeamMembersPanel.jsx";
import TeamOnboarding from "./components/TeamOnboarding.jsx";
import TokenUsagePanel, { TokenUsageCard, formatTokenValue, hasTokenUsage } from "./components/TokenUsagePanel.jsx";
import WorkflowStagePanel from "./components/WorkflowStagePanel.jsx";
import { api } from "./lib/api.js";
import { readSupabaseAuthSettings, supabase, supabaseReady } from "./lib/supabase.js";

const NAV_GROUPS = [
  { id: "work", label: "建模工作台" },
  { id: "collab", label: "协同与资产" },
  { id: "admin", label: "团队治理" },
  { id: "system", label: "运行状态" },
];

const NAV_ITEMS = [
  { id: "tasks", label: "任务", short: "任", group: "work", helper: "创建、上传、运行" },
  { id: "workflow", label: "工作流", short: "流", group: "work", helper: "阶段进度" },
  { id: "report", label: "报告", short: "报", group: "work", helper: "结果解释" },
  { id: "demo", label: "Web Demo", short: "测", group: "work", helper: "在线预测" },
  { id: "conversations", label: "AI 对话", short: "话", group: "work", helper: "Prompt / Response" },
  { id: "code", label: "代码工作区", short: "码", group: "work", helper: "真实工件", requiresDeveloper: true },
  { id: "human", label: "人机协同", short: "协", group: "collab", helper: "复核与恢复" },
  { id: "usage", label: "Token 用量", short: "耗", group: "collab", helper: "消耗追踪" },
  { id: "assets", label: "资产", short: "资", group: "collab", helper: "登记与审核" },
  { id: "connectors", label: "连接器", short: "连", group: "admin", helper: "模型来源", requiresAdmin: true },
  { id: "routing", label: "默认 AI", short: "由", group: "admin", helper: "阶段路由", requiresAdmin: true },
  { id: "quotas", label: "配额", short: "额", group: "admin", helper: "成员额度", requiresAdmin: true },
  { id: "team", label: "团队", short: "团", group: "admin", helper: "成员权限" },
  { id: "audit", label: "审计", short: "审", group: "admin", helper: "治理日志", requiresAdmin: true },
  { id: "system", label: "系统", short: "系", group: "system", helper: "健康检查" },
];

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
const DEFAULT_RUN_TIME_LIMIT = 20;

const PROBLEM_TYPE_LABELS = { classification: "分类", regression: "回归" };
const METRIC_LABELS = {
  validation_score: "验证分数",
  accuracy: "准确率",
  rmse: "RMSE",
  mae: "MAE",
  roc_auc: "ROC AUC",
  auc: "AUC",
  f1: "F1",
};
const TASK_STATUS_LABELS = {
  draft: "草稿",
  uploaded: "已上传数据集",
  planning: "规划中",
  paused_for_review: "等待复核",
  waiting_human: "等待人工协同",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  published: "已发布",
};
const TASK_STATUS_TONES = {
  draft: "warning",
  uploaded: "info",
  planning: "info",
  paused_for_review: "warning",
  waiting_human: "warning",
  running: "info",
  completed: "success",
  failed: "danger",
  published: "success",
};
const WORKFLOW_STAGE_LABELS = {
  requirement_analysis: "需求解析",
  data_analysis: "数据分析",
  feature_engineering: "特征工程",
  model_selection: "模型选择",
  training_validation: "训练验证",
  report_generation: "报告生成",
};
const TEAM_ROLE_LABELS = {
  team_owner: "团队所有者",
  admin: "管理员",
  business_user: "业务成员",
  developer_user: "开发成员",
  member: "成员",
};

function cn(...parts) { return parts.filter(Boolean).join(" "); }
function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
function formatMetricValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}
function formatMetricName(name) { return name ? METRIC_LABELS[name] ?? name : "暂无"; }
function formatProblemType(problemType) { return problemType ? PROBLEM_TYPE_LABELS[problemType] ?? problemType : "未解析"; }
function formatTaskStatus(status) { return TASK_STATUS_LABELS[status] ?? status; }
function getTaskStatusTone(status) { return TASK_STATUS_TONES[status] ?? "warning"; }
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
function getTaskRerunStage(task) {
  const humanLoop = task?.structured_requirements?.human_loop;
  if (!humanLoop || humanLoop.rerun_requested !== true) return null;
  const stage = typeof humanLoop.rerun_from_stage === "string" ? humanLoop.rerun_from_stage : "";
  return stage || null;
}
function formatWorkflowStage(stage) { return WORKFLOW_STAGE_LABELS[stage] ?? stage ?? "未知阶段"; }
function getTaskRunButtonLabel(task, running) {
  if (running) return "MLZero 运行中...";
  const rerunStage = getTaskRerunStage(task);
  if (rerunStage) return `从${formatWorkflowStage(rerunStage)}重跑（${DEFAULT_RUN_TIME_LIMIT} 分钟）`;
  return `运行 MLZero（${DEFAULT_RUN_TIME_LIMIT} 分钟）`;
}
function getTaskRunAttempt(task) { return task?.last_run_attempt && typeof task.last_run_attempt === "object" ? task.last_run_attempt : null; }
function getTaskRunUsage(task) {
  const lastAttempt = getTaskRunAttempt(task);
  if (hasTokenUsage(lastAttempt?.token_usage)) return lastAttempt.token_usage;
  return hasTokenUsage(task?.last_run?.token_usage) ? task.last_run.token_usage : null;
}
function getTaskAnalysisStatus(task) {
  if (task?.label_column && task?.problem_type) return "AI 已解析";
  if (task?.dataset_filename) return "待 AI 解析";
  return "未上传数据";
}
function getTaskSummary(task) {
  if (!task?.label_column && !task?.problem_type) return "当前还没有拿到 AI 解析结果。";
  if (task?.label_column && task?.problem_type) return `目标列 ${task.label_column}，任务类型 ${formatProblemType(task.problem_type)}。`;
  if (task?.label_column) return `已识别目标列 ${task.label_column}，任务类型待补全。`;
  return `已识别任务类型 ${formatProblemType(task.problem_type)}，目标列待补全。`;
}
function getAnalysisSourceLabel(task) {
  const source = getTaskAnalysis(task)?.analysis_source;
  if (!source) return "未标注";
  return source === "ai_connector" ? "当前运行时 AI 连接器" : String(source);
}
function getTeamRoleLabel(role) { return TEAM_ROLE_LABELS[role] ?? role ?? "未识别角色"; }
function mergeTaskIntoList(items, nextTask) { return [nextTask, ...items.filter((task) => task.id !== nextTask.id)]; }
function mergeConnectorIntoList(items, nextConnector) {
  const nextItems = items.map((item) => item.id === nextConnector.id ? nextConnector : nextConnector.is_active ? { ...item, is_active: false } : item);
  return nextItems.some((item) => item.id === nextConnector.id) ? nextItems : [nextConnector, ...nextItems];
}
function getUserLabel(user) { return user?.user_metadata?.display_name || user?.email || user?.id || ""; }
function buildTaskCreationMessage(task) {
  if (task.status === "paused_for_review") return "任务已创建，但根据任务策略自动进入人工复核。请先处理人机协同节点。";
  return task.label_column && task.problem_type
    ? "任务已创建，CSV 已上传，并且阶段路由对应的 AI 已完成任务解析。"
    : "任务已创建，CSV 已上传，但 AI 解析还未完成。请检查阶段路由或当前激活连接器后重试。";
}
function translateServerMessage(message) {
  const lowered = message.toLowerCase();
  if (lowered.includes("invalid login credentials")) return "邮箱或密码不正确。";
  if (lowered.includes("user already registered")) return "这个邮箱已经注册过了，可以直接登录。";
  if (lowered.includes("invite code not found")) return "没有找到对应的邀请码。";
  if (lowered.includes("team name is required")) return "请先填写团队名称。";
  if (lowered.includes("dataset has not been uploaded")) return "请先上传 CSV 数据集。";
  if (lowered.includes("only csv uploads are supported")) return "目前只支持 CSV 文件。";
  if (lowered.includes("task not found")) return "没有找到对应任务。";
  if (lowered.includes("connector not found")) return "没有找到对应连接器。";
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
  if (lowered.includes("connector storage request")) return "连接器相关请求被 Supabase 拒绝，请检查当前团队权限。";
  if (lowered.includes("governance request")) return "团队治理请求被 Supabase 拒绝，请检查当前团队权限。";
  if (lowered.includes("waiting for human collaboration")) return "当前任务正在等待人工协同，请先处理协同请求或恢复任务。";
  if (lowered.includes("open human collaboration requests")) return "当前任务还有未处理的人机协同请求，请先处理。";
  if (lowered.includes("still in progress")) return "当前任务仍在运行中，暂时不能创建人机协同请求。";
  if (lowered.includes("quota")) return message;
  return message;
}
function getErrorMessage(error) { return error instanceof Error && error.message ? translateServerMessage(error.message) : `收到未知错误：${String(error)}`; }

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
  const [taskForm, setTaskForm] = useState(EMPTY_TASK_FORM);
  const [taskFile, setTaskFile] = useState(null);
  const [taskUploadToken, setTaskUploadToken] = useState(0);
  const [submittingTask, setSubmittingTask] = useState(false);
  const [runningTaskId, setRunningTaskId] = useState("");
  const [analyzingTaskId, setAnalyzingTaskId] = useState("");
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
  const [quotaSavingMemberId, setQuotaSavingMemberId] = useState("");
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
    () => NAV_ITEMS.filter((item) => (!item.requiresAdmin || teamCanManage) && (!item.requiresDeveloper || teamCanDevelop)),
    [teamCanDevelop, teamCanManage],
  );
  const activeNavItem = useMemo(() => visibleNavItems.find((item) => item.id === activePage) ?? visibleNavItems[0] ?? null, [activePage, visibleNavItems]);

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
    try { setTasks((await api.listTasks(requestContext)).items ?? []); } catch (error) { setTaskError(getErrorMessage(error)); } finally { setTasksState("ready"); }
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

  async function refreshWorkspaceData() {
    await Promise.all([
      loadHealth(),
      loadTasks(),
      loadUsageSummary(),
      loadTokenLedgers(),
      loadConnectors(),
      loadTeamMembers(),
      loadTeamSettings(),
      loadQuotaSummary(),
      loadRoutingPolicies(),
      loadAssets(),
      loadAuditLogs(),
    ]);
    await loadTaskAIConversations();
    await loadTaskModelReport();
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
    void Promise.all([
      loadTasks(),
      loadUsageSummary(),
      loadTokenLedgers(),
      loadConnectors(),
      loadTeamMembers(),
      loadTeamSettings(),
      loadQuotaSummary(),
      loadRoutingPolicies(),
      loadAssets(),
      loadAuditLogs(),
    ]);
  }, [activeTeamId, session?.access_token, teamCanManage]);

  useEffect(() => {
    if (!tasks.length) {
      setSelectedTaskId("");
      return;
    }
    if (!tasks.some((task) => task.id === selectedTaskId)) setSelectedTaskId(tasks[0].id);
  }, [selectedTaskId, tasks]);

  useEffect(() => {
    if (!visibleNavItems.some((item) => item.id === activePage)) {
      setActivePage(visibleNavItems[0]?.id ?? "tasks");
    }
  }, [activePage, visibleNavItems]);

  useEffect(() => {
    setTaskChatError("");
  }, [selectedTask?.id]);

  useEffect(() => {
    if (!selectedTask?.id || !session?.access_token || !activeTeamId) {
      setTaskAIConversations(null);
      setTaskAIConversationsState("idle");
      setTaskAIConversationsError("");
      return;
    }
    void loadTaskAIConversations(selectedTask.id);
  }, [
    activeTeamId,
    selectedTask?.id,
    selectedTask?.updated_at,
    selectedTask?.last_run?.output_dir,
    selectedTask?.last_run_attempt?.output_dir,
    session?.access_token,
  ]);

  useEffect(() => {
    if (!selectedTask?.id || !session?.access_token || !activeTeamId) {
      setTaskModelReport(null);
      setTaskModelReportState("idle");
      setTaskModelReportError("");
      return;
    }
    void loadTaskModelReport(selectedTask.id);
  }, [
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
      return setTaskError("阶段 AI 覆盖中不能只填写模型名；请同时选择连接器，或清空该阶段覆盖。");
    }
    setSubmittingTask(true);
    setTaskError("");
    setTaskMessage("");
    let createdTaskId = "";
    try {
      const createdTask = await api.createTask({
        name: taskForm.name.trim(),
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
      const uploadedTask = await api.uploadDataset(createdTask.id, taskFile, requestContext);
      setTasks((current) => mergeTaskIntoList(current, uploadedTask));
      setSelectedTaskId(uploadedTask.id);
      setTaskForm(EMPTY_TASK_FORM);
      setTaskFile(null);
      setTaskUploadToken((current) => current + 1);
      await Promise.all([loadUsageSummary(), loadTokenLedgers(), loadTaskAIConversations(uploadedTask.id), loadTaskModelReport(uploadedTask.id)]);
      setTaskMessage(buildTaskCreationMessage(uploadedTask));
    } catch (error) {
      await Promise.allSettled([
        loadTasks(),
        loadUsageSummary(),
        loadTokenLedgers(),
        createdTaskId ? loadTaskAIConversations(createdTaskId) : Promise.resolve(),
        createdTaskId ? loadTaskModelReport(createdTaskId) : Promise.resolve(),
      ]);
      if (createdTaskId) setSelectedTaskId(createdTaskId);
      setTaskError(getErrorMessage(error));
    } finally {
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
      await Promise.all([loadUsageSummary(), loadTokenLedgers(), loadTaskAIConversations(updatedTask.id), loadTaskModelReport(updatedTask.id)]);
      setTaskMessage(`任务“${updatedTask.name}”已通过当前运行时 AI 重新解析。`);
    } catch (error) {
      await Promise.allSettled([loadTasks(), loadUsageSummary(), loadTokenLedgers(), loadTaskAIConversations(taskId), loadTaskModelReport(taskId)]);
      setTaskError(getErrorMessage(error));
    } finally {
      setAnalyzingTaskId("");
    }
  }

  async function handleRunTask(taskId) {
    setRunningTaskId(taskId);
    setTaskError("");
    setTaskMessage("");
    try {
      const updatedTask = await api.runTask(taskId, DEFAULT_RUN_TIME_LIMIT, requestContext);
      setTasks((current) => mergeTaskIntoList(current, updatedTask));
      setSelectedTaskId(updatedTask.id);
      await Promise.all([loadUsageSummary(), loadTokenLedgers(), loadTaskAIConversations(updatedTask.id), loadTaskModelReport(updatedTask.id)]);
      if (updatedTask.status === "paused_for_review") {
        setTaskMessage("任务已根据人工参与策略自动暂停，等待处理协同节点。");
      } else if (updatedTask.last_run) {
        setTaskMessage(`MLZero 运行完成。${formatMetricName(updatedTask.last_run?.metric_name)}：${formatMetricValue(updatedTask.last_run?.metric_value)}。`);
      } else {
        setTaskMessage("任务状态已更新。");
      }
    } catch (error) {
      await Promise.allSettled([loadTasks(), loadUsageSummary(), loadTokenLedgers(), loadTaskAIConversations(taskId), loadTaskModelReport(taskId)]);
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
      setConnectorMessage("连接器已保存。建议先测试连接，再设为当前运行时。");
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
      setConnectorMessage("当前运行时已切换。之后任务上传、AI 解析和 MLZero 都会走这个连接器。");
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
      setConnectorMessage("连接器配置已更新。请重新测试后再作为稳定运行时使用。");
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
      setConnectorMessage(`${response.detail} ${passedCount}/${results.length} 个连接器通过。`);
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
    if (!connector || !window.confirm(`确定删除连接器“${connector.display_name}”吗？删除后任务路由不能再引用它。`)) return false;
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

  async function handleSaveTeamQuota(memberId, payload) {
    setQuotaSavingMemberId(memberId);
    setQuotaError("");
    setQuotaMessage("");
    try {
      await api.adjustTeamQuota(memberId, payload, requestContext);
      await Promise.all([loadQuotaSummary(), loadAuditLogs()]);
      setQuotaMessage("成员配额已更新。");
    } catch (error) {
      setQuotaError(getErrorMessage(error));
    } finally {
      setQuotaSavingMemberId("");
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
      if (!selectedTask.last_run?.output_dir) return setAssetError("当前任务还没有成功运行产物，不能登记模型资产。");
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
      if (!selectedTask.last_run?.output_dir) return setAssetError("当前任务还没有成功运行产物，不能登记报告资产。");
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
          report_api: `/api/tasks/${selectedTask.id}/report`,
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

  function renderTaskDetail() {
    if (!selectedTask) return <div className="empty-state">先从左侧任务列表选择一个任务，或先创建新任务。</div>;
    const analysis = getTaskAnalysis(selectedTask);
    const analysisUsage = selectedTask.analysis_token_usage ?? null;
    const runUsage = getTaskRunUsage(selectedTask);
    const combinedUsage = combineTokenUsageReports(analysisUsage, runUsage);
    const lastRunAttempt = getTaskRunAttempt(selectedTask);
    const showingFailedAttempt = selectedTask.status === "failed" && lastRunAttempt;
    const rerunStage = getTaskRerunStage(selectedTask);
    const conversationCount = Array.isArray(taskAIConversations?.items) ? taskAIConversations.items.length : 0;
    const datasetProfile = getTaskDatasetProfile(selectedTask);
    const datasetColumns = Array.isArray(datasetProfile?.columns) ? datasetProfile.columns : [];
    const previewRows = Array.isArray(datasetProfile?.preview_rows) ? datasetProfile.preview_rows : [];
    return (
      <div className="detail-stack task-detail-panel">
        <section className="section-card task-detail-hero">
          <div className="section-head">
            <div><p className="eyebrow">任务详情</p><h3>{selectedTask.name}</h3><p className="task-description-large">{selectedTask.description}</p></div>
            <span className={`runtime-pill ${getTaskStatusTone(selectedTask.status)}`}>{formatTaskStatus(selectedTask.status)}</span>
          </div>
          <div className="summary-grid task-detail-kpis">
            <article className="summary-item"><span>数据集</span><strong>{selectedTask.dataset_filename ?? "未上传"}</strong></article>
            <article className="summary-item"><span>AI 解析状态</span><strong>{getTaskAnalysisStatus(selectedTask)}</strong></article>
            <article className="summary-item"><span>目标列</span><strong>{selectedTask.label_column ?? "未解析"}</strong></article>
            <article className="summary-item"><span>任务类型</span><strong>{formatProblemType(selectedTask.problem_type)}</strong></article>
            <article className="summary-item"><span>建议指标</span><strong>{formatMetricName(getTaskMetricName(selectedTask))}</strong></article>
            <article className="summary-item"><span>AI 置信度</span><strong>{formatConfidence(getTaskConfidence(selectedTask))}</strong></article>
          </div>
          {rerunStage ? (
            <div className="callout">
              <strong>下一次运行会从{formatWorkflowStage(rerunStage)}开始</strong>
              <p>后端会执行严格增量重跑：上游阶段复用已有真实产物，下游阶段写入新的运行目录和 `incremental_rerun_manifest.json`。</p>
            </div>
          ) : null}
          <p className="section-subtitle">{getTaskSummary(selectedTask)}</p>
          <div className="button-row connector-actions">
            <button type="button" className="ghost-button" onClick={() => void handleAnalyzeTask(selectedTask.id)} disabled={!selectedTask.dataset_filename || analyzingTaskId === selectedTask.id || runningTaskId === selectedTask.id}>{analyzingTaskId === selectedTask.id ? "AI 解析中..." : "AI 解析"}</button>
            <button type="button" className="primary-button" onClick={() => void handleRunTask(selectedTask.id)} disabled={!selectedTask.dataset_filename || runningTaskId === selectedTask.id || ["waiting_human", "paused_for_review"].includes(selectedTask.status)}>{getTaskRunButtonLabel(selectedTask, runningTaskId === selectedTask.id)}</button>
            <button type="button" className="chip-button" onClick={() => setActivePage("conversations")}>查看 AI 对话</button>
            <button type="button" className="chip-button" onClick={() => setActivePage("demo")}>Web Demo</button>
            {teamCanDevelop ? <button type="button" className="chip-button" onClick={() => setActivePage("code")}>查看 AI 代码</button> : null}
            <button type="button" className="chip-button" onClick={() => setActivePage("human")}>人机协同</button>
          </div>
        </section>

        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>数据集画像</h3>
              <p>上传 CSV 后由后端读取真实文件生成列名、样例行和缺失值概览。</p>
            </div>
            {datasetProfile ? <span className="runtime-pill success">已生成</span> : <span className="runtime-pill warning">未记录</span>}
          </div>
          {datasetProfile ? (
            <div className="detail-stack">
              <div className="summary-grid">
                <article className="summary-item"><span>文件名</span><strong>{datasetProfile.filename || selectedTask.dataset_filename || "未记录"}</strong></article>
                <article className="summary-item"><span>行数</span><strong>{Number(datasetProfile.row_count ?? 0).toLocaleString("zh-CN")}</strong></article>
                <article className="summary-item"><span>列数</span><strong>{Number(datasetProfile.column_count ?? 0).toLocaleString("zh-CN")}</strong></article>
                <article className="summary-item"><span>目标列</span><strong>{datasetProfile.target_column || selectedTask.label_column || "待解析"}</strong></article>
              </div>
              {datasetColumns.length ? (
                <div className="table-wrap compact-table">
                  <table>
                    <thead><tr><th>列名</th><th>类型</th><th>非空</th><th>缺失率</th><th>样例</th></tr></thead>
                    <tbody>
                      {datasetColumns.slice(0, 12).map((column) => (
                        <tr key={column.name}>
                          <td>{column.name}</td>
                          <td>{column.inferred_type}</td>
                          <td>{Number(column.non_empty_count ?? 0).toLocaleString("zh-CN")}</td>
                          <td>{formatRatio(column.missing_ratio)}</td>
                          <td>{Array.isArray(column.sample_values) && column.sample_values.length ? column.sample_values.join(" / ") : "暂无"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
              {previewRows.length ? (
                <details className="callout">
                  <summary>查看样例行</summary>
                  <pre className="code-block">{JSON.stringify(previewRows.slice(0, 8), null, 2)}</pre>
                </details>
              ) : null}
            </div>
          ) : (
            <div className="empty-state">当前任务还没有数据集画像。重新上传 CSV 后会写入真实预览信息。</div>
          )}
        </section>

        <section className="section-card">
          <div className="section-head"><div><h3>AI 解析说明</h3><p>这里展示的是当前运行时 AI 返回并写回任务记录的结果。</p></div></div>
          {analysis ? (
            <div className="detail-stack">
              <div className="summary-grid">
                <article className="summary-item"><span>解析来源</span><strong>{getAnalysisSourceLabel(selectedTask)}</strong></article>
                <article className="summary-item"><span>解析模型</span><strong>{analysis.analysis_model ?? "未记录"}</strong></article>
                <article className="summary-item"><span>解析时间</span><strong>{formatDateTime(analysis.analyzed_at)}</strong></article>
                <article className="summary-item"><span>列名数量</span><strong>{Array.isArray(analysis.column_names) ? analysis.column_names.length : 0}</strong></article>
              </div>
              <div className="callout"><strong>AI 推断理由</strong><p>{analysis.reasoning ?? "暂无"}</p></div>
              {analysis.raw_response ? <details className="callout"><summary>查看 AI 原始返回</summary><pre className="code-block">{analysis.raw_response}</pre></details> : null}
            </div>
          ) : <div className="empty-state">这个任务还没有拿到 AI 解析结果。先确认连接器可用，再点击“AI 解析”。</div>}
        </section>

        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>AI 对话记录</h3>
              <p>对话日志已经移到独立页面展示，会按 Prompt / Response 的聊天形式展开，不再挤占任务详情区。</p>
            </div>
            <button type="button" className="primary-button" onClick={() => setActivePage("conversations")}>
              打开 AI 对话页
            </button>
          </div>
          {taskAIConversationsError ? <div className="error-banner">{taskAIConversationsError}</div> : null}
          <div className="summary-grid">
            <article className="summary-item"><span>已记录问答</span><strong>{taskAIConversationsState === "loading" ? "刷新中..." : conversationCount ? `${conversationCount} 组` : "暂无"}</strong></article>
            <article className="summary-item"><span>当前查看方式</span><strong>独立聊天页</strong></article>
            <article className="summary-item"><span>覆盖范围</span><strong>任务分析 + 最新 MLZero 尝试</strong></article>
            <article className="summary-item"><span>建议操作</span><strong>切到 AI 对话页查看完整问答流</strong></article>
          </div>
        </section>

        <section className="section-card">
          <div className="section-head"><div><h3>MLZero 运行结果</h3><p>成功运行会展示指标、最佳候选和候选对比；失败尝试也会保留输出目录与 token，方便继续排查。</p></div></div>
          {showingFailedAttempt ? (
            <div className="detail-stack">
              <div className="summary-grid">
                <article className="summary-item"><span>最近一次尝试</span><strong>{formatTaskStatus(selectedTask.status)}</strong></article>
                <article className="summary-item"><span>输出目录</span><strong className="mono-text">{lastRunAttempt.output_dir}</strong></article>
                <article className="summary-item"><span>MLZero Token</span><strong>{hasTokenUsage(runUsage) ? formatTokenValue(runUsage.total_tokens) : "未记录"}</strong></article>
                <article className="summary-item"><span>运行状态</span><strong>这次尝试没有产出成功总结</strong></article>
              </div>
              {selectedTask.notes ? <div className="callout"><strong>失败说明</strong><p>{selectedTask.notes}</p></div> : null}
              {selectedTask.last_run ? (
                <div className="callout">
                  <strong>最近一次成功结果仍保留</strong>
                  <p>{formatMetricName(selectedTask.last_run.metric_name)}：{formatMetricValue(selectedTask.last_run.metric_value)}，最佳候选 {selectedTask.last_run.best_model}</p>
                </div>
              ) : null}
            </div>
          ) : selectedTask.last_run ? (
            <div className="detail-stack">
              <div className="summary-grid">
                <article className="summary-item"><span>结果指标</span><strong>{formatMetricName(selectedTask.last_run.metric_name)}</strong></article>
                <article className="summary-item"><span>指标数值</span><strong>{formatMetricValue(selectedTask.last_run.metric_value)}</strong></article>
                <article className="summary-item"><span>最佳候选</span><strong>{selectedTask.last_run.best_model}</strong></article>
                <article className="summary-item"><span>输出目录</span><strong className="mono-text">{selectedTask.last_run.output_dir}</strong></article>
              </div>
            </div>
          ) : lastRunAttempt ? (
            <div className="detail-stack">
              <div className="summary-grid">
                <article className="summary-item"><span>最近一次尝试</span><strong>{formatTaskStatus(selectedTask.status)}</strong></article>
                <article className="summary-item"><span>输出目录</span><strong className="mono-text">{lastRunAttempt.output_dir}</strong></article>
                <article className="summary-item"><span>MLZero Token</span><strong>{hasTokenUsage(runUsage) ? formatTokenValue(runUsage.total_tokens) : "未记录"}</strong></article>
                <article className="summary-item"><span>运行状态</span><strong>{selectedTask.notes ?? "暂无"}</strong></article>
              </div>
            </div>
          ) : <div className="empty-state">还没有运行结果。真正成功时，你会在这里看到指标、候选对比和输出目录，而不只是一个“已完成”状态。</div>}
        </section>

        {selectedTask.last_run ? (
          <details className="section-card task-detail-disclosure">
            <summary>
              <div>
                <h3>候选模型对比</h3>
                <p>最佳候选 {selectedTask.last_run.best_model}。完整 leaderboard 默认收起，避免任务详情右栏过长。</p>
              </div>
              <span className="disclosure-action">查看详细</span>
            </summary>
            <div className="disclosure-preview-grid">
              <article className="summary-item"><span>最佳候选</span><strong>{selectedTask.last_run.best_model}</strong></article>
              <article className="summary-item"><span>候选数量</span><strong>{Array.isArray(selectedTask.last_run.leaderboard) ? `${selectedTask.last_run.leaderboard.length} 个` : "未记录"}</strong></article>
              <article className="summary-item"><span>指标</span><strong>{formatMetricName(selectedTask.last_run.metric_name)}</strong></article>
            </div>
            <LeaderboardPanel
              run={selectedTask.last_run}
              formatMetricName={formatMetricName}
              formatMetricValue={formatMetricValue}
              embedded
            />
          </details>
        ) : null}

        <details className="section-card task-detail-disclosure">
          <summary>
            <div>
              <h3>Token 用量明细</h3>
              <p>合计 {hasTokenUsage(combinedUsage) ? formatTokenValue(combinedUsage.total_tokens) : "未记录"}。只在需要排查消耗时展开查看 AI 解析与 MLZero 运行 token。</p>
            </div>
            <span className="disclosure-action">查看详细</span>
          </summary>
          <div className="summary-grid disclosure-summary-grid">
            <article className="summary-item">
              <span>AI 解析总 Token</span>
              <strong>{hasTokenUsage(analysisUsage) ? formatTokenValue(analysisUsage.total_tokens) : "未记录"}</strong>
            </article>
            <article className="summary-item">
              <span>MLZero 总 Token</span>
              <strong>{hasTokenUsage(runUsage) ? formatTokenValue(runUsage.total_tokens) : "未记录"}</strong>
            </article>
            <article className="summary-item">
              <span>任务合计 Token</span>
              <strong>{hasTokenUsage(combinedUsage) ? formatTokenValue(combinedUsage.total_tokens) : "未记录"}</strong>
            </article>
          </div>

          <div className="disclosure-content-stack">
            <TokenUsageCard
              title="AI 解析 Token"
              report={analysisUsage}
              description="这里记录的是任务上传后或手动点击“AI 解析”时，当前运行时连接器实际返回的 token 使用量。"
              emptyText="当前还没有记录到 AI 解析 token。老任务如果是在这个模块完成之前创建的，也可能没有历史数据。"
              embedded
            />

            <TokenUsageCard
              title="MLZero 运行 Token"
              report={runUsage}
              description="这里读取的是最近一次 MLZero 尝试输出目录里的真实 token_usage.json，不是前端估算值。失败但已经产生日志和 token_usage.json 的尝试，也会显示。"
              emptyText="当前还没有记录到 MLZero 运行 token。只有对应输出目录里生成了 token_usage.json，系统才会显示。"
              showBreakdown
              embedded
            />
          </div>
        </details>
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
              <span>智能建模工作台</span>
            </div>
          </div>
          <div className="sidebar-summary">
            <span>当前团队</span>
            <strong>{activeTeam?.name ?? "未选择团队"}</strong>
            <em>{getTeamRoleLabel(activeTeam?.role)}</em>
          </div>
          <nav className="nav-list" aria-label="主导航">
            {NAV_GROUPS.map((group) => {
              const items = visibleNavItems.filter((item) => item.group === group.id);
              if (!items.length) return null;
              return (
                <section key={group.id} className="nav-group" aria-label={group.label}>
                  <p>{group.label}</p>
                  {items.map((item) => (
                    <button key={item.id} type="button" className={cn("nav-item", activePage === item.id && "active")} onClick={() => setActivePage(item.id)}>
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
              <div className="topbar-heading">
                <strong>{activeNavItem?.label ?? "工作台"}</strong>
                <span>{activeNavItem?.helper ?? "当前页面"}</span>
              </div>
              <div className={cn("runtime-pill", activeConnector ? "success" : "warning")}>
                {activeConnector ? `运行时：${activeConnector.display_name}` : "未激活连接器"}
              </div>
            </div>
            <div className="topbar-right">
              <select className="team-switcher" value={activeTeamId} onChange={(event) => setActiveTeamId(event.target.value)}>{memberships.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}</select>
              <button type="button" className="chip-button" onClick={() => void refreshWorkspaceData()}>刷新</button>
              <button type="button" className="logout-button" onClick={() => void handleLogout()}>退出登录</button>
            </div>
          </header>

          <div className="page-scroll">
            {activePage === "tasks" ? (
              <>
                <section className="page-header workbench-header">
                  <div>
                    <p className="eyebrow">Tasks</p>
                    <h1>任务上传与 AI 解析</h1>
                    <p className="page-copy">把自然语言需求、CSV 数据集、阶段 AI 路由和人工复核策略放在一条清晰链路里。上传后系统会调用当前团队的运行时 AI 填充目标列、任务类型和指标。</p>
                  </div>
                  <div className="header-status-stack">
                    <div className="runtime-pill info">当前运行时：{activeConnector ? `${activeConnector.display_name} · ${activeConnector.model_name}` : health?.model_alias ?? "未读取"}</div>
                    <div className="runtime-pill">任务数：{tasks.length}</div>
                  </div>
                </section>
                {taskMessage ? <div className="notice-banner">{taskMessage}</div> : null}
                {taskError ? <div className="error-banner">{taskError}</div> : null}
                <div className="task-workspace-grid">
                  <div className="detail-stack">
                    <TaskForm form={taskForm} connectors={connectors} selectedFile={taskFile} fileInputKey={taskUploadToken} submitting={submittingTask} onFieldChange={handleTaskFormFieldChange} onStageRoutingChange={handleTaskStageRoutingChange} onAddPolicy={handleAddTaskPolicy} onPolicyChange={handleTaskPolicyChange} onRemovePolicy={handleRemoveTaskPolicy} onFileChange={(event) => setTaskFile(event.target.files?.[0] ?? null)} onSubmit={handleTaskSubmit} />
                    <section className="section-card task-list-card"><div className="section-head"><div><h3>任务列表</h3><p>按任务状态、AI 解析和最近运行结果快速判断下一步动作。</p></div></div>{tasksState === "loading" && !tasks.length ? <div className="empty-state">正在读取任务列表...</div> : null}{!tasks.length && tasksState !== "loading" ? <div className="empty-state">还没有任务。先上传一个 CSV 任务。</div> : null}{tasks.length ? <div className="task-cards">{tasks.map((task) => <TaskCard key={task.id} task={task} selected={selectedTask?.id === task.id} running={runningTaskId === task.id} analyzing={analyzingTaskId === task.id} deleting={deletingTaskId === task.id} onSelect={setSelectedTaskId} onAnalyze={handleAnalyzeTask} onRun={handleRunTask} onDelete={handleDeleteTask} onOpenHumanCollaboration={(nextTaskId) => handleOpenHumanCollaboration(nextTaskId)} />)}</div> : null}</section>
                  </div>
                  {renderTaskDetail()}
                </div>
              </>
            ) : null}

            {activePage === "workflow" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Workflow</p>
                    <h1>工作流进度</h1>
                    <p className="page-copy">这里单独展示任务阶段状态、当前连接器/模型来源，以及待处理人工节点，避免把这些过程信息都挤在任务详情里。</p>
                  </div>
                </section>

                <WorkflowStagePanel
                  tasks={tasks}
                  tasksLoading={tasksState === "loading"}
                  selectedTask={selectedTask}
                  requestContext={requestContext}
                  onSelectTask={setSelectedTaskId}
                  onOpenHumanCollaboration={handleOpenHumanCollaboration}
                />
              </>
            ) : null}

            {activePage === "report" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Report</p>
                    <h1>模型分析报告</h1>
                    <p className="page-copy">当前版本的报告页基于真实任务记录汇总任务语义、AI 解析结论和 MLZero 成功结果，不再只是说明“待实现”。</p>
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
              </>
            ) : null}

            {activePage === "demo" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Web Demo</p>
                    <h1>在线预测 Demo</h1>
                    <p className="page-copy">这里调用真实任务运行产物做单行预测。没有可加载模型或预测合约时，页面会明确说明暂不支持。</p>
                  </div>
                </section>

                <PredictionDemoPanel
                  tasks={tasks}
                  tasksLoading={tasksState === "loading"}
                  selectedTask={selectedTask}
                  requestContext={requestContext}
                  onSelectTask={setSelectedTaskId}
                />
              </>
            ) : null}

            {activePage === "conversations" ? (
              <>
                <section className="page-header compact-page-header">
                  <div>
                    <p className="eyebrow">Conversations</p>
                    <h1>AI 对话</h1>
                  </div>
                  <div className="header-status-stack">
                    <div className="runtime-pill info">运行时：{activeConnector ? `${activeConnector.display_name} · ${activeConnector.model_name}` : health?.model_alias ?? "未读取"}</div>
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
              </>
            ) : null}

            {activePage === "code" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Code Workspace</p>
                    <h1>AI 代码工作区</h1>
                    <p className="page-copy">这里按最新一次 MLZero 运行目录来展示真实代码工件。你可以像在编辑器里一样浏览文件树、打开 AI 生成代码，并把修改保存回这次运行产物。</p>
                  </div>
                  <div className="detail-stack">
                    <div className="runtime-pill info">当前运行时：{activeConnector ? `${activeConnector.display_name} · ${activeConnector.model_name}` : health?.model_alias ?? "未读取"}</div>
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
              </>
            ) : null}

            {activePage === "human" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Human In The Loop</p>
                    <h1>人机协同</h1>
                    <p className="page-copy">这里把“人工介入”做成显式工作流，而不是只靠聊天文本。你可以创建协同请求、给出人工决策、让任务进入等待状态，再决定何时恢复。</p>
                  </div>
                  <div className="detail-stack">
                    <div className="runtime-pill info">当前运行时：{activeConnector ? `${activeConnector.display_name} · ${activeConnector.model_name}` : health?.model_alias ?? "未读取"}</div>
                  </div>
                </section>

                <HumanCollaborationPanel
                  tasks={tasks}
                  tasksLoading={tasksState === "loading"}
                  selectedTask={selectedTask}
                  requestContext={requestContext}
                  requestPreset={humanRequestPreset}
                  onSelectTask={setSelectedTaskId}
                  onTaskUpdated={handleHumanTaskUpdated}
                  onOpenTaskDetails={() => setActivePage("tasks")}
                />
              </>
            ) : null}

            {activePage === "usage" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Usage</p>
                    <h1>Token 用量统计</h1>
                    <p className="page-copy">这里显示的是当前团队在两条真实链路上的 token 消耗：任务 AI 解析，以及 MLZero 运行。没有采集到的数据会明确显示“未记录”，不会拿估算值冒充。</p>
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
              </>
            ) : null}

            {activePage === "connectors" ? (
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
            ) : null}
            {activePage === "routing" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Routing</p>
                    <h1>默认 AI 组合</h1>
                    <p className="page-copy">这里按阶段保存团队默认 AI 连接器和模型，让任务可以继承团队路由策略。</p>
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
              </>
            ) : null}
            {activePage === "quotas" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Quotas</p>
                    <h1>配额管理</h1>
                    <p className="page-copy">管理员可以在这里按成员调整 token 总额度，当前版本先做真实额度记录与人工调整。</p>
                  </div>
                </section>
                <QuotaManagementPanel
                  quotas={quotaSummary}
                  loading={quotaState === "loading"}
                  savingMemberId={quotaSavingMemberId}
                  message={quotaMessage}
                  error={quotaError || (!teamCanManage ? "当前账号不是团队管理员，无法查看或调整成员配额。" : "")}
                  onRefresh={() => void loadQuotaSummary()}
                  onSave={handleSaveTeamQuota}
                />
              </>
            ) : null}
            {activePage === "assets" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Assets</p>
                    <h1>资产中心</h1>
                    <p className="page-copy">这里统一登记数据集、模型、工作流和报告资产，并支持基础审核流转。</p>
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
              </>
            ) : null}
            {activePage === "team" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Team</p>
                    <h1>团队与权限</h1>
                    <p className="page-copy">这里除了切换团队和查看成员，还可以由团队所有者维护团队设置、转移所有权，并由管理员调整成员角色和状态。</p>
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
              </>
            ) : null}
            {activePage === "audit" ? (
              <>
                <section className="page-header">
                  <div>
                    <p className="eyebrow">Audit</p>
                    <h1>审计日志</h1>
                    <p className="page-copy">团队治理动作会写入审计日志。当前页面直接读取真实日志记录，不再只是文档要求。</p>
                  </div>
                </section>
                <AuditLogPanel
                  logs={auditLogs}
                  loading={auditState === "loading"}
                  error={auditError || (!teamCanManage ? "当前账号不是团队管理员，无法查看团队审计日志。" : "")}
                  onRefresh={() => void loadAuditLogs()}
                />
              </>
            ) : null}
            {activePage === "system" ? <SystemPanel health={health} loading={healthLoading} error={healthError} onRefresh={() => void loadHealth()} /> : null}
          </div>
        </div>
      </div>
    </main>
  );
}
