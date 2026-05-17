import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api.js";
import { getCachedCollaborationSnapshot, setCachedCollaborationSnapshot } from "../lib/collaborationCache.js";
import { formatMetricName, getMetricDirectionLabel, getValidationScoreExplanation } from "../lib/metrics.js";
import {
  RUN_STATUS_LABELS,
  WORKFLOW_STAGE_LABELS,
  formatDateTime,
  getReadableRuntimeActivity,
  isRawRuntimeDebugText,
  sanitizeRuntimeText,
} from "../lib/taskPresentation.js";

const AGENT_DEFINITIONS = [
  {
    id: "requirement_analysis",
    name: "需求理解",
    role: "理解任务",
    shortRole: "需求",
    description: "理解业务目标，整理任务约束与输出要求。",
    x: 10,
    y: 45,
  },
  {
    id: "data_analysis",
    name: "数据检查",
    role: "检查数据",
    shortRole: "数据",
    description: "检查 CSV 字段、目标列、缺失值与任务类型。",
    x: 27,
    y: 24,
  },
  {
    id: "feature_engineering",
    name: "数据处理",
    role: "准备训练数据",
    shortRole: "特征",
    description: "生成数据处理与训练前特征逻辑。",
    x: 45,
    y: 57,
  },
  {
    id: "model_selection",
    name: "模型准备",
    role: "选择候选模型",
    shortRole: "模型",
    description: "选择候选模型并组织比较方案。",
    x: 62,
    y: 30,
  },
  {
    id: "training_validation",
    name: "训练验证",
    role: "训练并检查结果",
    shortRole: "训练",
    description: "执行训练、验证、错误修复和结果记录。",
    x: 76,
    y: 62,
  },
  {
    id: "report_generation",
    name: "报告整理",
    role: "生成报告",
    shortRole: "报告",
    description: "汇总指标、生成文件、报告快照和试算入口。",
    x: 90,
    y: 44,
  },
];

const AGENT_LINKS = [
  ["requirement_analysis", "data_analysis", "任务语义"],
  ["data_analysis", "feature_engineering", "数据画像"],
  ["feature_engineering", "model_selection", "特征逻辑"],
  ["model_selection", "training_validation", "候选方案"],
  ["training_validation", "report_generation", "结果文件"],
  ["data_analysis", "model_selection", "目标与指标"],
  ["requirement_analysis", "feature_engineering", "业务约束"],
];

const STATUS_LABELS = {
  pending: "待命",
  running: "执行中",
  waiting_human: "等待人工",
  completed: "已完成",
  failed: "失败",
};

const RUNTIME_MODE_LABELS = {
  persistent_agent_runtime: "已保存的运行记录",
  stage_agent_orchestrator: "按步骤记录",
};

const EVENT_KIND_LABELS = {
  agent: "运行记录",
  stage: "阶段事件",
  human_request: "人工确认",
};

const MESSAGE_TYPE_LABELS = {
  coordination: "步骤安排",
  handoff: "阶段交接",
  acknowledgement: "接收确认",
  blocker: "阻塞通知",
  human_review: "人工确认",
  result: "结果广播",
};

function formatDuration(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "暂无";
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  if (value < 60) return `${value.toFixed(1)} s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  return `${minutes}m ${seconds}s`;
}

function formatNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "暂无";
  const absolute = Math.abs(value);
  if (absolute !== 0 && absolute < 0.0001) return value.toExponential(3);
  if (absolute >= 1000) return value.toLocaleString();
  return Number(value.toPrecision(6)).toString();
}

function formatElapsedSeconds(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "暂无";
  if (value < 60) return `${Math.round(value)} 秒`;
  if (value < 3600) return `${Math.round(value / 60)} 分钟`;
  return `${Math.round(value / 360) / 10} 小时`;
}

function compactText(value, maxLength = 58) {
  if (!value) return "";
  const text = String(value).replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

function friendlyRuntimeText(value, fallback) {
  const text = sanitizeRuntimeText(value, fallback);
  if (!text) return text;
  return text
    .replace(/Agent-Alpha/g, "需求理解")
    .replace(/Agent-Beta/g, "数据检查")
    .replace(/Agent-Gamma/g, "数据处理")
    .replace(/Agent-Delta/g, "模型准备")
    .replace(/Agent-Epsilon/g, "训练验证")
    .replace(/Agent-Zeta/g, "报告整理")
    .replace(/Observer Agent/gi, "系统观察")
    .replace(/观察 Agent/g, "系统观察")
    .replace(/Agent 诊断/g, "系统诊断")
    .replace(/Agent 自动修复受阻/g, "自动修复受阻")
    .replace(/leaderboard/gi, "候选模型对比")
    .replace(/telemetry/gi, "训练记录")
    .replace(/token_usage/gi, "AI 使用记录")
    .replace(/run_summary/gi, "结果摘要")
    .replace(/产物/g, "生成文件")
    .replace(/人工节点/g, "人工确认");
}

function getRunDiagnosis(selectedTask, runProgress) {
  const attempt = selectedTask?.last_run_attempt;
  const parts = [attempt?.diagnosis, attempt?.diagnosis_detail].filter(Boolean);
  if (parts.length) return friendlyRuntimeText(parts.join(" "));
  const activity = getReadableRuntimeActivity(runProgress);
  if (activity) return activity;
  if (selectedTask?.notes && !isRawRuntimeDebugText(selectedTask.notes)) return friendlyRuntimeText(selectedTask.notes);
  return "";
}

function getRunErrorArtifactPath(selectedTask, runProgress) {
  return runProgress?.artifacts?.error_log_path || selectedTask?.last_run_attempt?.error_artifact_path || "";
}

function getRunPillLabel(runProgress) {
  const activity = getReadableRuntimeActivity(runProgress);
  if (activity) return compactText(activity, 24);
  if (runProgress?.current_model) return compactText(`训练 ${runProgress.current_model}`, 24);
  if (runProgress?.status === "completed" && runProgress?.artifacts?.best_model) return compactText(`最佳 ${runProgress.artifacts.best_model}`, 24);
  return RUN_STATUS_LABELS[runProgress?.status] ?? runProgress?.status ?? "未读取";
}

function getStageDisplayLabel(runProgress) {
  const stage = runProgress?.observer_stage ?? runProgress?.current_stage;
  if (stage) return WORKFLOW_STAGE_LABELS[stage] ?? stage;
  if (["running", "repairing", "blocked"].includes(runProgress?.status)) return "等待阶段信号";
  return "暂无阶段";
}

function getModelDisplayLabel(runProgress) {
  if (runProgress?.current_model) return runProgress.current_model;
  if (runProgress?.artifacts?.best_model) return runProgress.artifacts.best_model;
  if (runProgress?.status === "blocked") return "等待重试";
  if (runProgress?.status === "running") return "尚未开始模型 fit";
  return "暂无模型";
}

function getInsightTone(severity) {
  if (severity === "danger") return "failed";
  if (severity === "warning") return "waiting";
  if (severity === "success") return "success";
  return "running";
}

function getRunTone(progress) {
  if (progress?.status === "blocked") return "warning";
  if (progress?.status === "repairing") return "info";
  if (progress?.stale || progress?.status === "stale") return "danger";
  if (progress?.status === "completed") return "success";
  if (progress?.status === "failed") return "danger";
  if (progress?.status === "running") return "info";
  return "warning";
}

function compactIdentifier(value) {
  if (!value) return "未记录";
  const text = String(value);
  return text.length > 34 ? `${text.slice(0, 18)}...${text.slice(-10)}` : text;
}

function getAgentTone(status) {
  if (status === "completed") return "success";
  if (status === "running") return "running";
  if (status === "waiting_human") return "waiting";
  if (status === "failed") return "failed";
  return "pending";
}

function getStepDisplayName(stepId, fallback) {
  const definition = AGENT_DEFINITIONS.find((item) => item.id === stepId);
  if (definition?.name) return definition.name;
  const text = fallback ? String(fallback) : "";
  if (/agent/i.test(text)) return definition?.role ?? stepId ?? "步骤";
  return text || stepId || "步骤";
}

function getProgress(status) {
  if (status === "completed") return 100;
  if (status === "running") return 62;
  if (status === "waiting_human") return 48;
  if (status === "failed") return 100;
  return 0;
}

function normalizeArtifactCount(value) {
  if (!value) return 0;
  if (Array.isArray(value)) return value.length;
  if (typeof value === "string") return value ? 1 : 0;
  if (typeof value === "object") {
    return Object.values(value).reduce((count, item) => {
      if (Array.isArray(item)) return count + item.length;
      return item ? count + 1 : count;
    }, 0);
  }
  return 0;
}

function buildAgents(stages, requests) {
  const stagesByKey = new Map((stages ?? []).map((stage) => [stage.stage, stage]));
  const openRequests = new Set(
    (requests ?? [])
      .filter((request) => ["pending", "open"].includes(request.status))
      .map((request) => request.stage),
  );

  return AGENT_DEFINITIONS.map((agent) => {
    const stage = stagesByKey.get(agent.id);
    const status = openRequests.has(agent.id) ? "waiting_human" : stage?.status ?? "pending";
    return {
      ...agent,
      stage,
      status,
      tone: getAgentTone(status),
      progress: getProgress(status),
      currentTask: friendlyRuntimeText(stage?.summary, "系统已接管当前阶段状态。") || agent.description,
      modelName: stage?.model_name || "未指定",
      connector: stage?.selected_connector_id || "未指定",
      selectionSource: stage?.selection_source || "未记录",
      artifactCount: normalizeArtifactCount(stage?.artifact_refs),
      lastActionAt: stage?.updated_at || stage?.finished_at || stage?.started_at,
    };
  });
}

function buildEvents(agents, requests) {
  const stageEvents = agents
    .filter((agent) => agent.stage)
    .map((agent) => ({
      id: `stage-${agent.id}-${agent.stage.updated_at || agent.stage.created_at}`,
      time: agent.stage.updated_at || agent.stage.created_at,
      text: friendlyRuntimeText(`${agent.name}（${agent.role}）${STATUS_LABELS[agent.status] ?? agent.status}：${agent.currentTask}`),
      tone: agent.tone,
    }));
  const requestEvents = (requests ?? []).map((request) => ({
    id: `request-${request.id}`,
    time: request.updated_at || request.created_at,
    text: `人工确认 ${request.payload?.title || request.stage} 当前状态：${request.status}`,
    tone: "waiting",
  }));
  return [...stageEvents, ...requestEvents]
    .sort((left, right) => new Date(right.time || 0).getTime() - new Date(left.time || 0).getTime())
    .slice(0, 12);
}

function buildAgentsFromSnapshot(snapshot, stages, requests) {
  if (!Array.isArray(snapshot?.agents)) return [];
  return snapshot.agents.map((agent) => {
    const definition = AGENT_DEFINITIONS.find((item) => item.id === agent.id) ?? {};
    const status = agent.status ?? "pending";
    return {
      id: agent.id,
      name: getStepDisplayName(agent.id, agent.name ?? definition.name),
      role: agent.role ?? definition.role ?? agent.stage,
      shortRole: definition.shortRole ?? agent.short_role ?? agent.role ?? "步骤",
      description: definition.description ?? "",
      x: typeof agent.x === "number" ? agent.x : definition.x ?? 0,
      y: typeof agent.y === "number" ? agent.y : definition.y ?? 0,
      stage: stages.find((stage) => stage.stage === agent.stage) ?? null,
      status,
      tone: getAgentTone(status),
      progress: typeof agent.progress === "number" ? agent.progress : getProgress(status),
      currentTask: friendlyRuntimeText(agent.current_task, "系统已接管当前阶段状态。") || definition.description || "",
      modelName: agent.model_name || "未指定",
      connector: agent.connector_id || "未指定",
      selectionSource: agent.selection_source || "未记录",
      artifactCount: typeof agent.artifact_count === "number" ? agent.artifact_count : normalizeArtifactCount(agent.artifact_refs),
      artifactRefs: Array.isArray(agent.artifact_refs) ? agent.artifact_refs : [],
      lastActionAt: agent.last_action_at,
      runtimeId: agent.runtime_id ?? null,
      runtimeSource: agent.runtime_source ?? "stage_record_projection",
      workerId: agent.worker_id ?? null,
      startedAt: agent.started_at ?? null,
      finishedAt: agent.finished_at ?? null,
      durationSeconds: agent.duration_seconds ?? null,
      logExcerpt: friendlyRuntimeText(agent.log_excerpt, ""),
    };
  });
}

function buildEventsFromSnapshot(snapshot, agents, requests) {
  if (!Array.isArray(snapshot?.events)) return [];
  return snapshot.events.map((event) => ({
    id: event.id,
    time: event.time,
    text: friendlyRuntimeText(event.text),
    kind: event.kind ?? "stage",
    status: event.status ?? "",
    artifactRefs: Array.isArray(event.artifact_refs) ? event.artifact_refs : [],
    tone: event.kind === "human_request" ? "waiting" : getAgentTone(event.status),
  }));
}

function buildMessagesFromSnapshot(snapshot) {
  if (!Array.isArray(snapshot?.messages)) return [];
  return snapshot.messages.map((message) => ({
    id: message.id,
    time: message.time,
    fromAgentId: message.from_agent_id,
    toAgentId: message.to_agent_id,
    type: message.message_type ?? "coordination",
    status: message.status ?? "sent",
    content: friendlyRuntimeText(message.content),
    artifactRefs: Array.isArray(message.artifact_refs) ? message.artifact_refs : [],
    fromAgentName: getStepDisplayName(message.from_agent_id, message.payload?.from_agent_name),
    fromAgentRole: message.payload?.from_agent_role,
    toAgentName: getStepDisplayName(message.to_agent_id, message.payload?.to_agent_name),
    toAgentRole: message.payload?.to_agent_role,
  }));
}

function getAgentDisplayName(agentId, agents) {
  const agent = agents.find((item) => item.id === agentId);
  return agent?.name ?? getStepDisplayName(agentId, agentId) ?? "全体";
}

function buildAgentRuntimeSignal(agent, runProgress, modelCountLabel) {
  const observedStage = runProgress?.observer_stage ?? runProgress?.current_stage;
  const observedActivity = getReadableRuntimeActivity(runProgress);
  const isCurrentStage = Boolean(observedStage && observedStage === agent.id);
  if (isCurrentStage && observedActivity) {
    const details = [];
    if (agent.id === "training_validation" && runProgress.current_model) details.push(`模型 ${runProgress.current_model}`);
    if (agent.id === "training_validation" && modelCountLabel !== "暂无") details.push(`候选 ${modelCountLabel}`);
    if (typeof runProgress.latest_validation_score === "number") details.push(`排序分 ${formatNumber(runProgress.latest_validation_score)}`);
    if (runProgress.last_log_at) details.push(`Heartbeat ${formatDateTime(runProgress.last_log_at)}`);
    return {
      isCurrentStage,
      headline: compactText(observedActivity, 96),
      detail: details.join(" · ") || "系统根据日志、指标和生成文件综合判断",
      source: "系统观察",
      progress: Math.max(0, Math.min(100, runProgress.progress_percent ?? agent.progress ?? 0)),
    };
  }

  if (runProgress?.status === "blocked" && agent.id === observedStage) {
    return {
      isCurrentStage: true,
      headline: compactText(observedActivity || "自动修复受阻", 96),
      detail: "生成文件已保留，等待重新运行继续修复",
      source: "系统观察",
      progress: Math.max(0, Math.min(100, runProgress.progress_percent ?? agent.progress ?? 0)),
    };
  }

  if (agent.logExcerpt) {
    return {
      isCurrentStage,
      headline: compactText(friendlyRuntimeText(agent.logExcerpt), 96),
      detail: agent.currentTask ? compactText(friendlyRuntimeText(agent.currentTask), 72) : "阶段诊断",
      source: "系统诊断",
      progress: agent.progress,
    };
  }

  if (agent.currentTask && agent.currentTask !== agent.description) {
    return {
      isCurrentStage,
      headline: compactText(friendlyRuntimeText(agent.currentTask), 96),
      detail: agent.artifactCount ? `生成文件 ${agent.artifactCount} 个` : "阶段记录",
      source: "阶段摘要",
      progress: agent.progress,
    };
  }

  return {
    isCurrentStage,
    headline: agent.status === "pending" ? "等待上游阶段交付" : compactText(agent.description, 96),
    detail: STATUS_LABELS[agent.status] ?? agent.status,
    source: "阶段状态",
    progress: agent.progress,
  };
}

function isAgentSnapshot(payload) {
  return Boolean(payload) && Array.isArray(payload.agents) && Array.isArray(payload.events);
}

export default function MultiAgentCollaborationPanel({
  tasks,
  tasksLoading,
  selectedTask,
  requestContext,
  runProgress,
  runProgressState,
  runProgressError,
  onRefreshRunProgress,
  onSelectTask,
  onOpenCodeWorkspace,
  onOpenHumanCollaboration,
}) {
  const [snapshot, setSnapshot] = useState(null);
  const [state, setState] = useState("idle");
  const [error, setError] = useState("");

  const stages = useMemo(() => (Array.isArray(snapshot?.stages) ? snapshot.stages : []), [snapshot]);
  const requests = useMemo(() => (Array.isArray(snapshot?.requests) ? snapshot.requests : []), [snapshot]);
  const agents = useMemo(() => buildAgentsFromSnapshot(snapshot, stages, requests), [snapshot, stages, requests]);
  const events = useMemo(() => buildEventsFromSnapshot(snapshot, agents, requests), [snapshot, agents, requests]);
  const messages = useMemo(() => buildMessagesFromSnapshot(snapshot), [snapshot]);

  const completedCount = agents.filter((agent) => agent.status === "completed").length;
  const activeCount = agents.filter((agent) => ["running", "waiting_human"].includes(agent.status)).length;
  const artifactCount = agents.reduce((count, agent) => count + agent.artifactCount, 0);
  const messageCount = messages.length;
  const isPersistentRuntime = snapshot?.runtime_mode === "persistent_agent_runtime";
  const runtimeModeLabel = RUNTIME_MODE_LABELS[snapshot?.runtime_mode] ?? "未读取";
  const persistentAgentCount = agents.filter((agent) => agent.runtimeSource === "persistent_agent_runtime").length;
  const runEvents = Array.isArray(runProgress?.events) ? runProgress.events : [];
  const observerInsights = Array.isArray(runProgress?.insights) ? runProgress.insights : [];
  const latestObserverInsight = observerInsights.length ? observerInsights[observerInsights.length - 1] : null;
  const observerActivity = getReadableRuntimeActivity(runProgress);
  const runDiagnosis = getRunDiagnosis(selectedTask, runProgress);
  const runErrorArtifactPath = getRunErrorArtifactPath(selectedTask, runProgress);
  const runLeaderboard = Array.isArray(runProgress?.leaderboard) ? runProgress.leaderboard : [];
  const trainingMetrics = Array.isArray(runProgress?.training_metrics) ? runProgress.training_metrics : [];
  const latestMetric = trainingMetrics.length ? trainingMetrics[trainingMetrics.length - 1] : null;
  const runMetricName = selectedTask?.last_run?.metric_name ?? runProgress?.artifacts?.metric_name ?? latestMetric?.metric_name ?? "validation_score";
  const hasEpochTelemetry = trainingMetrics.some((metric) => typeof metric.epoch === "number" || typeof metric.train_loss === "number" || typeof metric.validation_loss === "number");
  const runProgressPercent = Math.max(0, Math.min(100, runProgress?.progress_percent ?? 0));
  const hasModelBudget = typeof runProgress?.current_model_elapsed_seconds === "number"
    && Number.isFinite(runProgress.current_model_elapsed_seconds)
    && typeof runProgress?.current_model_time_budget_seconds === "number"
    && Number.isFinite(runProgress.current_model_time_budget_seconds)
    && runProgress.current_model_time_budget_seconds > 0;
  const modelBudgetPercent = hasModelBudget
    ? Math.max(0, Math.min(100, (runProgress.current_model_elapsed_seconds / runProgress.current_model_time_budget_seconds) * 100))
    : null;
  const modelCountLabel = runProgress?.completed_model_count != null || runProgress?.total_model_count
    ? `${runProgress?.completed_model_count ?? 0}${runProgress?.total_model_count ? `/${runProgress.total_model_count}` : ""}`
    : "暂无";
  const agentsWithSignals = useMemo(
    () => agents.map((agent) => ({
      ...agent,
      runtimeSignal: buildAgentRuntimeSignal(agent, runProgress, modelCountLabel),
    })),
    [agents, runProgress, modelCountLabel],
  );
  const currentStageLabel = getStageDisplayLabel(runProgress);
  const iterationLabel = runProgress?.current_iteration && runProgress?.total_iterations
    ? `${runProgress.current_iteration}/${runProgress.total_iterations}`
    : "暂无";

  useEffect(() => {
    if (!selectedTask?.id || !requestContext?.accessToken || !requestContext?.teamId) {
      setSnapshot(null);
      setState("idle");
      setError("");
      return;
    }
    let active = true;
    const cachedPayload = getCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId);
    const cached = isAgentSnapshot(cachedPayload) ? cachedPayload : null;
    if (cached) setSnapshot(cached);
    setState(cached ? "ready" : "loading");
    setError("");
    api.taskAgentCollaboration(selectedTask.id, requestContext)
      .then((payload) => {
        if (!active) return;
        if (!isAgentSnapshot(payload)) throw new Error("后端运行快照缺少必要字段。");
        setCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId, payload);
        setSnapshot(payload);
        setState("ready");
      })
      .catch((loadError) => {
        if (!active) return;
        setSnapshot(null);
        setState("ready");
        setError(loadError instanceof Error ? loadError.message : String(loadError));
      });
    return () => {
      active = false;
    };
  }, [requestContext, selectedTask?.id]);

  async function handleRefresh() {
    if (!selectedTask?.id) return;
    setState("loading");
    setError("");
    try {
      const payload = await api.taskAgentCollaboration(selectedTask.id, { ...requestContext, noCache: true });
      if (!isAgentSnapshot(payload)) throw new Error("后端运行快照缺少必要字段。");
      setCachedCollaborationSnapshot(selectedTask.id, requestContext.teamId, payload);
      setSnapshot(payload);
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : String(refreshError));
    } finally {
      setState("ready");
    }
  }

  return (
    <div className="multi-agent-console">
      <section className="section-card agent-toolbar-card">
        <div className="section-head">
          <div>
            <h3>任务上下文</h3>
            <p>这里展示任务运行时的进度、日志摘要、事件、候选模型对比和训练记录。</p>
          </div>
          <div className="agent-toolbar-actions">
            {tasks?.length ? (
              <label className="agent-task-select">
                <span>当前任务</span>
                <select value={selectedTask?.id ?? ""} onChange={(event) => onSelectTask?.(event.target.value)}>
                  {tasks.map((task) => (
                    <option key={task.id} value={task.id}>
                      {task.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <button type="button" className="chip-button" onClick={handleRefresh} disabled={!selectedTask?.id || state === "loading"}>
              {state === "loading" ? "同步中..." : "同步状态"}
            </button>
            <button type="button" className="chip-button" onClick={onRefreshRunProgress} disabled={!selectedTask?.id || runProgressState === "loading" || runProgressState === "refreshing"}>
              {runProgressState === "loading" || runProgressState === "refreshing" ? "刷新运行中..." : "刷新运行"}
            </button>
          </div>
        </div>
        {!tasks?.length && !tasksLoading ? <div className="empty-state compact">当前还没有任务。</div> : null}
      </section>

      <section className={`section-card live-run-card ${runProgress?.stale ? "danger" : ""}`}>
        <div className="section-head">
          <div>
            <p className="eyebrow">系统观察</p>
            <h3>实时运行判断</h3>
            <p>{observerActivity || "系统正在等待可解释的日志、指标或生成文件信号。"}</p>
          </div>
          {runProgress ? <span className={`runtime-pill ${getRunTone(runProgress)}`}>{getRunPillLabel(runProgress)}</span> : null}
        </div>
        {runProgressError ? <div className="error-banner">{runProgressError}</div> : null}
        {!selectedTask ? <div className="empty-state compact">先选择一个任务。</div> : null}
        {selectedTask && !runProgress && !runProgressError ? <div className="empty-state compact">暂无实时运行数据。点击运行任务后，后端会持续写入 stdout/stderr 和运行事件。</div> : null}
        {runDiagnosis && ["blocked", "failed", "stale"].includes(runProgress?.status) ? (
          <div className="callout conversation-warning">
            <strong>诊断结论</strong>
            <p>{runDiagnosis}</p>
            {runErrorArtifactPath ? <p>报错文件：<span className="mono-text">{runErrorArtifactPath}</span></p> : null}
            {runErrorArtifactPath ? (
              <button type="button" className="ghost-button" onClick={() => onOpenCodeWorkspace?.()}>
                查看报错文件
              </button>
            ) : null}
          </div>
        ) : null}
        {runProgress ? (
          <>
            <div className="task-run-progress-meter live-run-meter" aria-label="运行进度">
              <span style={{ width: `${runProgressPercent}%` }} />
            </div>
            <div className="live-run-meter-caption">
              <span>模型级进度：{modelCountLabel}</span>
              <strong>{runProgressPercent}%</strong>
            </div>
            <div className="summary-grid live-run-grid">
              <article className="summary-item"><span>观察阶段</span><strong>{currentStageLabel}</strong></article>
              <article className="summary-item"><span>当前模型</span><strong>{getModelDisplayLabel(runProgress)}</strong></article>
              <article className="summary-item"><span>当前/最近模型耗时</span><strong>{formatElapsedSeconds(runProgress.current_model_elapsed_seconds)}</strong></article>
              <article className="summary-item"><span>模型时间预算</span><strong>{formatElapsedSeconds(runProgress.current_model_time_budget_seconds)}</strong></article>
              <article className="summary-item"><span>搜索轮次</span><strong>{runProgress.current_iteration && runProgress.total_iterations ? `${runProgress.current_iteration}/${runProgress.total_iterations}` : "暂无"}</strong></article>
              <article className="summary-item"><span>训练 Epoch</span><strong>{runProgress.current_epoch && runProgress.total_epochs ? `${runProgress.current_epoch}/${runProgress.total_epochs}` : "未上报"}</strong></article>
              <article className="summary-item"><span>候选模型</span><strong>{modelCountLabel}</strong></article>
              <article className="summary-item"><span>最后 Heartbeat</span><strong>{formatDateTime(runProgress.last_log_at)}</strong></article>
              <article className="summary-item"><span>无更新时间</span><strong>{formatElapsedSeconds(runProgress.seconds_since_last_update)}</strong></article>
              <article className="summary-item"><span>主要指标</span><strong>{formatMetricName(runMetricName)}</strong></article>
              <article className="summary-item"><span>判断方向</span><strong>{getMetricDirectionLabel(runMetricName)}</strong></article>
              <article className="summary-item"><span>最新候选排序分</span><strong>{formatNumber(runProgress.latest_validation_score)}</strong></article>
            </div>
            <div className="notice-banner compact">{getValidationScoreExplanation(runMetricName)}</div>
            {modelBudgetPercent !== null ? (
              <div className="runtime-detail-bars">
                <div className="runtime-detail-bar-row">
                  <span>当前模型时间预算消耗</span>
                  <div className="runtime-detail-bar"><span style={{ width: `${modelBudgetPercent}%` }} /></div>
                  <strong>{Math.round(modelBudgetPercent)}%</strong>
                </div>
                <small>这是时间预算消耗，不是 RF/KNN/ExtraTrees 内部训练百分比。</small>
              </div>
            ) : null}
            {runProgress.stale_reason ? <p className="danger-text">{runProgress.stale_reason}</p> : null}
            {runProgress.telemetry_note ? <div className="notice-banner compact">{runProgress.telemetry_note}</div> : null}
            {observerInsights.length ? (
              <div className="observer-insight-panel">
                <div className="observer-insight-head">
                  <strong>运行观察时间线</strong>
                  {latestObserverInsight?.source ? <span>最新来源：{latestObserverInsight.source}</span> : null}
                </div>
                <div className="observer-insight-list">
                  {observerInsights.slice(-8).reverse().map((insight, index) => (
                    <article key={`${insight.event_type}-${insight.headline}-${index}`} className={`observer-insight ${getInsightTone(insight.severity)}`}>
                      <div>
                        <strong>{insight.headline}</strong>
                        <span>{formatDateTime(insight.time)}</span>
                      </div>
                      {insight.detail ? <p>{insight.detail}</p> : null}
                      <small>
                        {WORKFLOW_STAGE_LABELS[insight.stage] ?? insight.stage ?? "全局"}
                        {insight.source ? ` · ${insight.source}` : ""}
                        {insight.evidence && !isRawRuntimeDebugText(insight.evidence) ? ` · 证据：${compactText(friendlyRuntimeText(insight.evidence), 110)}` : ""}
                      </small>
                    </article>
                  ))}
                </div>
              </div>
            ) : null}
            {runProgress.output_dir ? <p className="mono-text task-run-progress-path">{runProgress.output_dir}</p> : null}
          </>
        ) : null}
      </section>

      <section className="section-card agent-graph-card">
        <div className="section-head">
          <div>
            <p className="eyebrow">运行详情</p>
            <h3>自动建模执行图</h3>
            <p>这里展示系统按步骤推进任务的过程，以及每一步生成了哪些结果。</p>
          </div>
          <div className="agent-console-actions">
            {selectedTask ? <span className="runtime-pill info">{selectedTask.name}</span> : null}
            {selectedTask ? (
              <span className={`runtime-pill ${isPersistentRuntime ? "success" : "warning"}`}>
                记录方式：{runtimeModeLabel}
              </span>
            ) : null}
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {!selectedTask ? <div className="empty-state">先选择一个任务，再查看运行详情。</div> : null}

        {selectedTask ? (
          <>
            <div className="agent-graph-summary">
              <article><span>执行步骤</span><strong>{agents.length}</strong></article>
              <article><span>当前阶段</span><strong>{currentStageLabel}</strong></article>
              <article><span>候选模型</span><strong>{modelCountLabel}</strong></article>
              <article><span>搜索轮次</span><strong>{iterationLabel}</strong></article>
              <article><span>生成文件</span><strong>{artifactCount}</strong></article>
              <article><span>步骤记录</span><strong>{messageCount}</strong></article>
            </div>

            <div className="agent-network">
              <svg className="agent-link-layer" viewBox="0 0 100 76" preserveAspectRatio="none" aria-hidden="true">
                <defs>
                  <marker id="agent-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="4" markerHeight="4" orient="auto">
                    <path d="M 0 0 L 8 4 L 0 8 z" />
                  </marker>
                </defs>
                {AGENT_LINKS.map(([fromId, toId], index) => {
                  const from = agents.find((agent) => agent.id === fromId);
                  const to = agents.find((agent) => agent.id === toId);
                  if (!from || !to) return null;
                  const midX = (from.x + to.x) / 2;
                  const midY = (from.y + to.y) / 2 - (index % 2 === 0 ? 7 : -5);
                  return (
                    <g key={`${fromId}-${toId}`}>
                      <path
                        className={`agent-link ${from.status === "completed" ? "completed" : ""}`}
                        d={`M ${from.x + 3.5} ${from.y} Q ${midX} ${midY} ${to.x - 3.5} ${to.y}`}
                        markerEnd="url(#agent-arrow)"
                      />
                    </g>
                  );
                })}
              </svg>
              {agentsWithSignals.map((agent) => (
                <article
                  key={agent.id}
                  className={`agent-node ${agent.tone} ${agent.runtimeSignal.isCurrentStage ? "active-stage" : ""}`}
                  style={{ left: `${agent.x}%`, top: `${agent.y}%` }}
                >
                  <span className="agent-node-icon">{agent.shortRole}</span>
                  <strong>{agent.name}</strong>
                  <em>{agent.role}</em>
                  <p>{agent.runtimeSignal.headline}</p>
                  <small>{agent.runtimeSignal.detail || (STATUS_LABELS[agent.status] ?? agent.status)}</small>
                </article>
              ))}
            </div>
          </>
        ) : null}
      </section>

      <details className="expert-advanced-fold">
        <summary>
          <span>展开专业运行细节</span>
          <small>训练监控、候选模型对比、步骤状态、事件和日志文件</small>
        </summary>
        <div className="expert-advanced-stack">
      <div className="live-training-grid">
        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>训练监控</h3>
              <p>展示真实训练记录或候选模型对比。没有训练曲线的模型不会显示伪造曲线。</p>
            </div>
            {latestMetric ? <span className="runtime-pill info">{latestMetric.model || "训练指标"}</span> : null}
          </div>
          {hasEpochTelemetry ? (
            <div className="training-metric-list">
              {trainingMetrics.slice(-16).map((metric, index) => {
                const primaryValue = typeof metric.validation_loss === "number"
                  ? metric.validation_loss
                  : typeof metric.train_loss === "number"
                    ? metric.train_loss
                    : metric.validation_score;
                const barWidth = typeof primaryValue === "number" && Number.isFinite(primaryValue)
                  ? `${Math.max(4, Math.min(100, Math.abs(primaryValue) * 100))}%`
                  : "4%";
                return (
                  <article key={`${metric.source || "metric"}-${index}`} className="training-metric-row">
                    <div>
                      <strong>{metric.model || "未命名模型"}</strong>
                      <span>{metric.epoch ? `epoch ${metric.epoch}${metric.total_epochs ? `/${metric.total_epochs}` : ""}` : metric.iteration ? `iteration ${metric.iteration}${metric.total_iterations ? `/${metric.total_iterations}` : ""}` : "指标点"}</span>
                    </div>
                    <div className="training-metric-bar"><span style={{ width: barWidth }} /></div>
                    <small>train loss {formatNumber(metric.train_loss)} / val loss {formatNumber(metric.validation_loss)} / ranking score {formatNumber(metric.validation_score)}</small>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="empty-state compact">当前没有训练曲线。对 RF、KNN、ExtraTrees 等模型，这是正常情况；请看候选模型完成数和模型对比表。</div>
          )}
        </section>

        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>候选模型对比</h3>
              <p>这里展示系统实际比较过的候选模型结果。</p>
            </div>
          </div>
          {!runLeaderboard.length ? <div className="empty-state compact">还没有读取到候选模型对比结果。</div> : null}
          {runLeaderboard.length ? (
            <div className="table-wrap compact-table">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>模型</th>
                    <th>候选排序分</th>
                    <th>训练耗时</th>
                  </tr>
                </thead>
                <tbody>
                  {runLeaderboard.slice(0, 8).map((row, index) => (
                    <tr key={`${row.model}-${row.rank ?? index}`}>
                      <td>{row.rank ?? index + 1}</td>
                      <td>{row.model}</td>
                      <td>{formatNumber(row.validation_score)}</td>
                      <td>{formatDuration(row.fit_time)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      </div>

      <div className="agent-bottom-grid">
        <section className="section-card agent-status-card">
          <div className="section-head">
            <div>
              <h3>执行步骤状态</h3>
              <p>进度、模型、AI 服务、耗时和生成文件都来自系统真实记录。</p>
            </div>
            {selectedTask ? (
              <button type="button" className="primary-button" onClick={() => onOpenHumanCollaboration?.(selectedTask.id)}>
                处理人工节点
              </button>
            ) : null}
          </div>

          <div className="table-wrap agent-status-table">
            <table>
              <thead>
                <tr>
                  <th>步骤</th>
                  <th>角色</th>
                  <th>当前信号</th>
                  <th>来源</th>
                  <th>模型</th>
                  <th>运行记录</th>
                  <th>耗时</th>
                  <th>最后更新</th>
                </tr>
              </thead>
              <tbody>
                {agentsWithSignals.map((agent) => (
                  <tr key={agent.id}>
                    <td><span className={`agent-dot ${agent.tone}`} />{agent.name}</td>
                    <td>{agent.role}</td>
                    <td>
                      <div className="agent-task-cell">
                        <span>{agent.runtimeSignal.headline}</span>
                        {agent.runtimeSignal.detail ? <small>{agent.runtimeSignal.detail}</small> : null}
                      </div>
                    </td>
                    <td>
                      <div className="agent-runtime-cell">
                        <strong>{agent.runtimeSignal.source}</strong>
                        <small>{STATUS_LABELS[agent.status] ?? agent.status}</small>
                      </div>
                    </td>
                    <td>{agent.modelName}</td>
                    <td>
                      <div className="agent-runtime-cell">
                <strong>{agent.runtimeSource === "persistent_agent_runtime" ? "已保存" : "按阶段"}</strong>
                        <small title={agent.workerId || agent.runtimeId || ""}>{compactIdentifier(agent.workerId || agent.runtimeId)}</small>
                      </div>
                    </td>
                    <td>
                      <div className="agent-runtime-cell">
                        <strong>{formatDuration(agent.durationSeconds)}</strong>
                        <small>开始：{formatDateTime(agent.startedAt)}</small>
                      </div>
                    </td>
                    <td>{formatDateTime(agent.lastActionAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="section-card agent-event-card">
          <div className="section-head">
            <div>
              <h3>实时事件</h3>
              <p>这里保留运行事件；原始日志只在需要排查时通过报错文件查看。</p>
            </div>
          </div>
          {![...events, ...runEvents].length ? <div className="empty-state compact">当前任务还没有可展示的运行事件。</div> : null}
          {[...events, ...runEvents].length ? (
            <div className="agent-event-list">
              {[...events, ...runEvents.map((event, index) => ({
                id: `run-${index}-${event.time || event.message}`,
                time: event.time,
                text: event.message,
                kind: event.event_type,
                artifactRefs: [],
                tone: event.event_type === "error" ? "failed" : event.stage === "training_validation" ? "running" : "success",
              }))].sort((left, right) => new Date(right.time || 0).getTime() - new Date(left.time || 0).getTime()).slice(0, 24).map((event) => (
                <article key={event.id} className={`agent-event ${event.tone}`}>
                  <span>
                    {formatDateTime(event.time)}
                    <em>{EVENT_KIND_LABELS[event.kind] ?? event.kind}</em>
                    {event.artifactRefs.length ? <em>{event.artifactRefs.length} 个生成文件</em> : null}
                  </span>
                  <p>{friendlyRuntimeText(event.text)}</p>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      </div>

      <section className="section-card task-detail-fold live-log-details">
        <summary>
          <div>
            <h3>报错日志文件</h3>
            <p>运行详情只展示诊断结论；需要人工排查时再打开保留的日志文件。</p>
          </div>
          {runErrorArtifactPath ? <span className="disclosure-action">已保留</span> : null}
        </summary>
        {runErrorArtifactPath ? (
          <div className="callout compact">
            <p><span className="mono-text">{runErrorArtifactPath}</span></p>
            <button type="button" className="ghost-button" onClick={() => onOpenCodeWorkspace?.()}>
              查看报错文件
            </button>
          </div>
        ) : (
          <div className="empty-state compact">当前还没有可定位的报错日志文件。</div>
        )}
      </section>

      <section className="section-card agent-message-card">
        <div className="section-head">
          <div>
            <h3>步骤记录</h3>
            <p>展示系统在每一步推进时保存的交接、确认和阻塞消息。</p>
          </div>
        </div>
        {!messages.length ? <div className="empty-state compact">当前任务还没有步骤记录。</div> : null}
        {messages.length ? (
          <div className="agent-message-list">
            {messages.map((message) => {
              const fromName = message.fromAgentName || getAgentDisplayName(message.fromAgentId, agents);
              const toName = message.toAgentName || getAgentDisplayName(message.toAgentId, agents);
              return (
                <article key={message.id} className={`agent-message ${message.type}`}>
                  <div className="agent-message-route">
                    <strong>{fromName}</strong>
                    <span>→</span>
                    <strong>{toName}</strong>
                    <em>{MESSAGE_TYPE_LABELS[message.type] ?? message.type}</em>
                    {message.artifactRefs.length ? <em>{message.artifactRefs.length} 个生成文件</em> : null}
                  </div>
                  <p>{friendlyRuntimeText(message.content)}</p>
                  <small>{formatDateTime(message.time)}</small>
                </article>
              );
            })}
          </div>
        ) : null}
      </section>
        </div>
      </details>
    </div>
  );
}
